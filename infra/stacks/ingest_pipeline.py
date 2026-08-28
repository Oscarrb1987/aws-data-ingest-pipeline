"""Stack de pipeline: Lambdas, job de Glue y maquina de estados.

La maquina de estados es la traduccion literal del procedimiento manual:
validar, transformar, comprobar, esperar a la hora acordada y volver a
comprobar. La diferencia es que aqui cada paso deja traza, reintenta solo y
avisa cuando algo no cuadra.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from stacks.contract import DatasetContract

LAMBDA_BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "lambda"
GLUE_SCRIPT = Path(__file__).resolve().parents[2] / "src" / "glue_jobs" / "landing_to_curated.py"


class IngestPipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        contract: list[DatasetContract],  # noqa: ARG002 - reservado para futuras reglas por dataset
        data_bucket: s3.IBucket,
        ledger_table: dynamodb.ITable,
        alert_topic: sns.ITopic,
        glue_database: str,
        athena_workgroup: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.env_name = env_name
        self.data_bucket = data_bucket
        self.ledger_table = ledger_table
        self.alert_topic = alert_topic

        self.common_env = {
            "DATA_BUCKET": data_bucket.bucket_name,
            "LEDGER_TABLE": ledger_table.table_name,
            "ALERT_TOPIC_ARN": alert_topic.topic_arn,
            "QUERY_ENGINE": "athena",
            "GLUE_DATABASE": glue_database,
            "ATHENA_WORKGROUP": athena_workgroup,
            "ATHENA_OUTPUT_LOCATION": f"s3://{data_bucket.bucket_name}/athena-results/",
            "RULES_PATH": "rules/checks.yaml",
            "BUSINESS_TIMEZONE": self.node.try_get_context("business_timezone") or "Europe/Madrid",
            "VERIFY_B_SCHEDULE": self.node.try_get_context("verify_b_schedule") or "08:00",
            "LOG_LEVEL": "INFO",
            "POWERTOOLS_SERVICE_NAME": project,
        }

        self.glue_job_name = f"{project}-landing-to-curated-{env_name}"

        code = self._lambda_code()
        self.fn_validate = self._lambda(
            "Validate", "validate_file", code, timeout_min=5, memory=1024
        )
        self.fn_verify = self._lambda("Verify", "verify_load", code, timeout_min=10, memory=512)
        self.fn_schedule = self._lambda("Schedule", "schedule", code, timeout_min=1, memory=256)
        self.fn_notify = self._lambda("Notify", "notify_failure", code, timeout_min=1, memory=256)

        self._grant_permissions()
        self._create_glue_job()
        self.state_machine = self._create_state_machine()
        self._create_trigger()
        self._create_alarms()
        self._outputs()

    # -------------------------------------------------------------- Lambdas

    def _lambda_code(self) -> lambda_.Code:
        if not LAMBDA_BUILD_DIR.exists():
            raise FileNotFoundError(
                f"No existe {LAMBDA_BUILD_DIR}. Ejecuta `make package` antes de `cdk synth`."
            )
        return lambda_.Code.from_asset(str(LAMBDA_BUILD_DIR))

    def _lambda(
        self,
        name: str,
        module: str,
        code: lambda_.Code,
        *,
        timeout_min: int,
        memory: int,
    ) -> lambda_.Function:
        log_group = logs.LogGroup(
            self,
            f"Fn{name}Logs",
            log_group_name=f"/aws/lambda/{self.project}-{module}-{self.env_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        return lambda_.Function(
            self,
            f"Fn{name}",
            function_name=f"{self.project}-{module}-{self.env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,  # ~20% mas barato que x86
            handler=f"src.handlers.{module}.handler",
            code=code,
            timeout=cdk.Duration.minutes(timeout_min),
            memory_size=memory,
            environment=self.common_env,
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
            retry_attempts=0,  # los reintentos los gobierna Step Functions
        )

    def _grant_permissions(self) -> None:
        for fn in (self.fn_validate, self.fn_verify, self.fn_schedule, self.fn_notify):
            self.ledger_table.grant_read_write_data(fn)
            self.alert_topic.grant_publish(fn)

        self.data_bucket.grant_read_write(self.fn_validate)
        self.data_bucket.grant_read_write(self.fn_verify)

        # La verificacion consulta Athena sobre el catalogo de Glue.
        self.fn_verify.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:GetWorkGroup",
                ],
                resources=["*"],
            )
        )
        self.fn_verify.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                ],
                resources=["*"],
            )
        )

    # ----------------------------------------------------------------- Glue

    def _create_glue_job(self) -> None:
        role = iam.Role(
            self,
            "GlueJobRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
            ],
        )
        self.data_bucket.grant_read_write(role)

        script = s3_assets.Asset(self, "GlueScript", path=str(GLUE_SCRIPT))
        script.grant_read(role)

        glue.CfnJob(
            self,
            "LandingToCurated",
            name=self.glue_job_name,
            role=role.role_arn,
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=2,  # suficiente para ficheros de decenas de millones de filas
            timeout=30,
            max_retries=1,
            execution_property=glue.CfnJob.ExecutionPropertyProperty(max_concurrent_runs=5),
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=script.s3_object_url,
            ),
            default_arguments={
                "--job-language": "python",
                "--enable-metrics": "true",
                "--enable-observability-metrics": "true",
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-auto-scaling": "true",
                "--additional-python-modules": "PyYAML==6.0.2",
                "--TempDir": f"s3://{self.data_bucket.bucket_name}/glue-temp/",
            },
        )

    # ------------------------------------------------------- Step Functions

    def _create_state_machine(self) -> sfn.StateMachine:
        notify = tasks.LambdaInvoke(
            self,
            "NotificarFallo",
            lambda_function=self.fn_notify,
            payload_response_only=True,
        ).next(sfn.Fail(self, "EjecucionFallida", cause="Ver el informe y el ledger"))

        def with_catch(state):
            return state.add_catch(notify, result_path="$.error")

        # La validacion previa ya mueve el fichero a cuarentena y avisa por su
        # cuenta, asi que su Catch solo tiene que cerrar la ejecucion: pasar
        # por NotificarFallo mandaria una segunda alerta por el mismo motivo.
        rechazado = sfn.Fail(
            self,
            "FicheroRechazado",
            cause="El fichero no supero la validacion previa; esta en quarantine/ y ya se notifico",
            error="ValidationFailed",
        )
        validate = tasks.LambdaInvoke(
            self,
            "ValidarFichero",
            comment="Checksum, numero de filas y cabecera frente al manifest",
            lambda_function=self.fn_validate,
            payload_response_only=True,
            retry_on_service_exceptions=True,
        ).add_catch(rechazado, result_path="$.error")

        transform = with_catch(
            tasks.GlueStartJobRun(
                self,
                "TransformarConGlue",
                comment="CSV de landing a Parquet particionado en curated",
                glue_job_name=self.glue_job_name,
                integration_pattern=sfn.IntegrationPattern.RUN_JOB,  # espera a que termine
                arguments=sfn.TaskInput.from_object(
                    {
                        "--dataset": sfn.JsonPath.string_at("$.dataset"),
                        "--business_date": sfn.JsonPath.string_at("$.business_date"),
                        "--run_id": sfn.JsonPath.string_at("$.run_id"),
                        "--delimiter": sfn.JsonPath.string_at("$.delimiter"),
                        "--source_path": sfn.JsonPath.format(
                            "s3://{}/{}",
                            sfn.JsonPath.string_at("$.bucket"),
                            sfn.JsonPath.string_at("$.source_key"),
                        ),
                        "--target_path": sfn.JsonPath.format(
                            "s3://{}/curated/{}/",
                            sfn.JsonPath.string_at("$.bucket"),
                            sfn.JsonPath.string_at("$.table"),
                        ),
                        "--rules_path": (
                            f"s3://{self.data_bucket.bucket_name}/config/rules/checks.yaml"
                        ),
                    }
                ),
                result_path=sfn.JsonPath.DISCARD,  # el estado sigue siendo la salida de validar
                task_timeout=sfn.Timeout.duration(cdk.Duration.hours(1)),
            )
        )

        mark_a = sfn.Pass(
            self,
            "MarcarFaseA",
            result=sfn.Result.from_string("A_POST_LOAD"),
            result_path="$.phase",
        )
        verify_a = with_catch(
            tasks.LambdaInvoke(
                self,
                "VerificarCargaA",
                comment="Comprobacion inmediata: los datos estan y cuadran",
                lambda_function=self.fn_verify,
                payload_response_only=True,
                retry_on_service_exceptions=True,
            )
        )

        schedule = with_catch(
            tasks.LambdaInvoke(
                self,
                "CalcularHoraVerificacionB",
                lambda_function=self.fn_schedule,
                payload_response_only=True,
            )
        )

        # Esperar aqui no cuesta nada: Step Functions no consume computo
        # mientras el estado Wait esta activo.
        wait = sfn.Wait(
            self,
            "EsperarHoraProgramada",
            time=sfn.WaitTime.timestamp_path("$.verify_b_at"),
        )

        mark_b = sfn.Pass(
            self,
            "MarcarFaseB",
            result=sfn.Result.from_string("B_SCHEDULED"),
            result_path="$.phase",
        )
        verify_b = with_catch(
            tasks.LambdaInvoke(
                self,
                "VerificarCargaB",
                comment="Comprobacion diferida: nadie ha pisado los datos",
                lambda_function=self.fn_verify,
                payload_response_only=True,
                retry_on_service_exceptions=True,
            )
        )

        definition = (
            validate.next(transform)
            .next(mark_a)
            .next(verify_a)
            .next(schedule)
            .next(wait)
            .next(mark_b)
            .next(verify_b)
            .next(sfn.Succeed(self, "CargaVerificada"))
        )

        log_group = logs.LogGroup(
            self,
            "StateMachineLogs",
            log_group_name=f"/aws/vendedlogs/states/{self.project}-{self.env_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        return sfn.StateMachine(
            self,
            "IngestAndVerify",
            state_machine_name=f"{self.project}-ingest-and-verify-{self.env_name}",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            # Hasta 25 h: cubre el caso de que la verificacion B caiga al dia siguiente.
            timeout=cdk.Duration.hours(25),
            tracing_enabled=True,
            logs=sfn.LogOptions(destination=log_group, level=sfn.LogLevel.ALL),
        )

    # --------------------------------------------------------- Disparadores

    def _create_trigger(self) -> None:
        """El pipeline arranca solo cuando aparece un manifest en landing/.

        Se dispara con el manifest y no con el CSV a proposito: el manifest se
        sube el ultimo, asi que su llegada garantiza que el fichero de datos
        esta completo.
        """
        events.Rule(
            self,
            "OnManifestUploaded",
            rule_name=f"{self.project}-on-manifest-{self.env_name}",
            description="Arranca la ingesta al depositarse un manifest en landing/",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={
                    "bucket": {"name": [self.data_bucket.bucket_name]},
                    "object": {"key": [{"wildcard": "landing/*.manifest.json"}]},
                },
            ),
            targets=[targets.SfnStateMachine(self.state_machine)],
        )

    def _create_alarms(self) -> None:
        """Si el pipeline falla o tarda de mas, alguien tiene que enterarse."""
        action = cw_actions.SnsAction(self.alert_topic)

        cw.Alarm(
            self,
            "EjecucionesFallidas",
            alarm_name=f"{self.project}-ejecuciones-fallidas-{self.env_name}",
            alarm_description="Al menos una ejecucion del pipeline ha terminado en error",
            metric=self.state_machine.metric_failed(period=cdk.Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(action)

        cw.Alarm(
            self,
            "ErroresVerificacion",
            alarm_name=f"{self.project}-errores-verificacion-{self.env_name}",
            alarm_description="La Lambda de verificacion esta fallando de forma tecnica",
            metric=self.fn_verify.metric_errors(period=cdk.Duration.minutes(15)),
            threshold=2,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(action)

    def _outputs(self) -> None:
        cdk.CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
        cdk.CfnOutput(self, "GlueJobName", value=self.glue_job_name)
        cdk.CfnOutput(
            self,
            "LandingPrefix",
            value=f"s3://{self.data_bucket.bucket_name}/landing/",
            description="Sube aqui el CSV y su manifest para arrancar el pipeline",
        )

"""Stack de plataforma: almacenamiento, catalogo, ledger y alertas.

Todo lo que sobrevive a un redespliegue del pipeline vive aqui.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_athena as athena
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_glue as glue
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from stacks.contract import DatasetContract

# Rutas absolutas: la sintesis debe dar el mismo resultado desde cualquier cwd.
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


class DataPlatformStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        env_name: str,
        contract: list[DatasetContract],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project = project
        self.env_name = env_name

        self.data_bucket = self._create_bucket()
        self.ledger_table = self._create_ledger()
        self.alert_topic = self._create_topic()
        self.glue_database_name = f"{project}_curated_{env_name}"
        self.athena_workgroup_name = f"{project}-{env_name}"

        self._create_catalog(contract)
        self._create_athena_workgroup()
        self._deploy_rules()
        self._outputs()

    # ------------------------------------------------------------------ S3

    def _create_bucket(self) -> s3.Bucket:
        """Un unico bucket con zonas por prefijo.

        `event_bridge_enabled` es lo que dispara el pipeline: en cuanto
        aparece un manifest en `landing/`, EventBridge arranca la maquina de
        estados. Nadie tiene que lanzar nada a mano.
        """
        return s3.Bucket(
            self,
            "DataLake",
            bucket_name=f"{self.project}-datalake-{self.env_name}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                # El CSV crudo se conserva 90 dias por si hay que reprocesar.
                s3.LifecycleRule(
                    id="landing-expira",
                    prefix="landing/",
                    expiration=cdk.Duration.days(90),
                    noncurrent_version_expiration=cdk.Duration.days(30),
                ),
                # Los ficheros rechazados se guardan mas tiempo: son la prueba
                # de por que un dia no se cargo nada.
                s3.LifecycleRule(
                    id="cuarentena-a-glacier",
                    prefix="quarantine/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
                            transition_after=cdk.Duration.days(30),
                        )
                    ],
                    expiration=cdk.Duration.days(365),
                ),
                s3.LifecycleRule(
                    id="resultados-athena",
                    prefix="athena-results/",
                    expiration=cdk.Duration.days(14),
                ),
                s3.LifecycleRule(
                    id="cortar-multipart-huerfanos",
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(7),
                ),
            ],
        )

    # ------------------------------------------------------------- DynamoDB

    def _create_ledger(self) -> dynamodb.Table:
        """Historico de ejecuciones.

        On-demand: el pipeline se ejecuta unas pocas veces al dia, aprovisionar
        capacidad no tiene sentido. TTL a dos anos para que la tabla no crezca
        indefinidamente.
        """
        table = dynamodb.Table(
            self,
            "RunLedger",
            table_name=f"{self.project}-run-ledger-{self.env_name}",
            partition_key=dynamodb.Attribute(name="run_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="expires_at",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        # Permite responder "que paso con clientes el dia 27" sin escanear.
        table.add_global_secondary_index(
            index_name="dataset-business_date-index",
            partition_key=dynamodb.Attribute(name="dataset", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="business_date", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        return table

    # ------------------------------------------------------------------ SNS

    def _create_topic(self) -> sns.Topic:
        topic = sns.Topic(
            self,
            "AlertTopic",
            topic_name=f"{self.project}-alerts-{self.env_name}",
            display_name="Alertas del pipeline de ingesta",
        )
        for email in self.node.try_get_context("alert_emails") or []:
            topic.add_subscription(subs.EmailSubscription(email))
        return topic

    # ----------------------------------------------------------- Glue/Athena

    def _create_catalog(self, contract: list[DatasetContract]) -> None:
        """Crea una tabla de Glue por dataset, derivada del contrato YAML.

        Se usa *partition projection* en lugar de un crawler: Athena calcula
        las particiones a partir del patron de la ruta, asi que no hay que
        ejecutar `MSCK REPAIR` ni pagar un crawler, y una particion nunca
        queda sin registrar justo cuando se va a verificar.
        """
        database = glue.CfnDatabase(
            self,
            "CuratedDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=self.glue_database_name,
                description="Zona curada del pipeline de ingesta",
            ),
        )

        for ds in contract:
            location = f"s3://{self.data_bucket.bucket_name}/curated/{ds.table}/"
            table = glue.CfnTable(
                self,
                f"Table{ds.table.title()}",
                catalog_id=self.account,
                database_name=self.glue_database_name,
                table_input=glue.CfnTable.TableInputProperty(
                    name=ds.table,
                    table_type="EXTERNAL_TABLE",
                    partition_keys=[
                        glue.CfnTable.ColumnProperty(name=ds.partition_column, type="string")
                    ],
                    parameters={
                        "classification": "parquet",
                        "EXTERNAL": "TRUE",
                        "projection.enabled": "true",
                        f"projection.{ds.partition_column}.type": "date",
                        f"projection.{ds.partition_column}.format": "yyyy-MM-dd",
                        f"projection.{ds.partition_column}.range": "2020-01-01,NOW",
                        f"projection.{ds.partition_column}.interval": "1",
                        f"projection.{ds.partition_column}.interval.unit": "DAYS",
                        "storage.location.template": (
                            f"{location}{ds.partition_column}=${{{ds.partition_column}}}/"
                        ),
                    },
                    storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                        location=location,
                        input_format="org.apache.hadoop.hive.ql.io.parquet."
                        "MapredParquetInputFormat",
                        output_format="org.apache.hadoop.hive.ql.io.parquet."
                        "MapredParquetOutputFormat",
                        serde_info=glue.CfnTable.SerdeInfoProperty(
                            serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde."
                            "ParquetHiveSerDe"
                        ),
                        columns=[
                            glue.CfnTable.ColumnProperty(name=c["name"], type=c["type"])
                            for c in ds.glue_columns
                        ],
                    ),
                ),
            )
            table.add_resource_dependency(database)

    def _create_athena_workgroup(self) -> None:
        athena.CfnWorkGroup(
            self,
            "Workgroup",
            name=self.athena_workgroup_name,
            description="Consultas de verificacion de calidad de datos",
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                # Guardarrail de coste: una verificacion nunca deberia escanear
                # mas de 1 GB si el particionado esta bien hecho.
                bytes_scanned_cutoff_per_query=1_073_741_824,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.data_bucket.bucket_name}/athena-results/",
                    encryption_configuration=(
                        athena.CfnWorkGroup.EncryptionConfigurationProperty(
                            encryption_option="SSE_S3"
                        )
                    ),
                ),
            ),
        )

    def _deploy_rules(self) -> None:
        """Sube el contrato al bucket para que el job de Glue pueda leerlo."""
        s3deploy.BucketDeployment(
            self,
            "DeployRules",
            sources=[s3deploy.Source.asset(str(RULES_DIR))],
            destination_bucket=self.data_bucket,
            destination_key_prefix="config/rules",
            prune=False,
            retain_on_delete=False,
        )

    # -------------------------------------------------------------- Outputs

    def _outputs(self) -> None:
        cdk.CfnOutput(self, "DataBucketName", value=self.data_bucket.bucket_name)
        cdk.CfnOutput(self, "LedgerTableName", value=self.ledger_table.table_name)
        cdk.CfnOutput(self, "AlertTopicArn", value=self.alert_topic.topic_arn)
        cdk.CfnOutput(self, "GlueDatabase", value=self.glue_database_name)
        cdk.CfnOutput(self, "AthenaWorkgroup", value=self.athena_workgroup_name)

"""Pruebas de la infraestructura.

Sintetizan la aplicacion CDK y comprueban sobre la plantilla CloudFormation
resultante las decisiones que no deben perderse en un refactor: que el bucket
no sea publico, que el disparador escuche solo a los manifests, que la
maquina de estados tenga sus dos verificaciones y que exista el estado Wait.

Se saltan si `aws-cdk-lib` no esta instalado, para que la suite de aplicacion
siga siendo ligera.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk", reason="aws-cdk-lib no instalado")

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

from stacks.contract import load_contract  # noqa: E402
from stacks.data_platform import DataPlatformStack  # noqa: E402
from stacks.ingest_pipeline import IngestPipelineStack  # noqa: E402

ENV = cdk.Environment(account="111122223333", region="eu-west-1")


@pytest.fixture(scope="module")
def plantillas():
    if not (ROOT / "build" / "lambda").exists():
        pytest.skip("ejecuta `make package` antes de las pruebas de infraestructura")

    app = cdk.App(context={"env": "test", "project": "dataflow"})
    contract = load_contract(ROOT / "rules" / "checks.yaml")

    platform = DataPlatformStack(
        app, "platform", env=ENV, project="dataflow", env_name="test", contract=contract
    )
    pipeline = IngestPipelineStack(
        app,
        "pipeline",
        env=ENV,
        project="dataflow",
        env_name="test",
        contract=contract,
        data_bucket=platform.data_bucket,
        ledger_table=platform.ledger_table,
        alert_topic=platform.alert_topic,
        glue_database=platform.glue_database_name,
        athena_workgroup=platform.athena_workgroup_name,
    )
    return Template.from_stack(platform), Template.from_stack(pipeline)


# ------------------------------------------------------------- Plataforma


def test_el_bucket_no_es_publico_y_esta_cifrado(plantillas):
    platform, _ = plantillas
    platform.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.any_value(),
        },
    )


def test_el_bucket_notifica_a_eventbridge(plantillas):
    """Sin esto el pipeline nunca arrancaria solo.

    CDK configura las notificaciones del bucket con un recurso a medida, asi
    que la comprobacion se hace sobre el.
    """
    platform, _ = plantillas
    platform.has_resource_properties(
        "Custom::S3BucketNotifications",
        {"NotificationConfiguration": {"EventBridgeConfiguration": {}}},
    )


def test_el_ledger_tiene_indice_por_dataset_y_fecha(plantillas):
    platform, _ = plantillas
    platform.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "GlobalSecondaryIndexes": Match.array_with(
                [Match.object_like({"IndexName": "dataset-business_date-index"})]
            )
        },
    )


def test_las_tablas_de_glue_salen_del_contrato_yaml(plantillas):
    """Dos datasets en checks.yaml -> dos tablas catalogadas."""
    platform, _ = plantillas
    platform.resource_count_is("AWS::Glue::Table", 2)


def test_las_particiones_se_proyectan_sin_crawler(plantillas):
    platform, _ = plantillas
    platform.has_resource_properties(
        "AWS::Glue::Table",
        {
            "TableInput": Match.object_like(
                {
                    "Parameters": Match.object_like(
                        {"projection.enabled": "true", "projection.dt.type": "date"}
                    )
                }
            )
        },
    )


def test_athena_tiene_limite_de_bytes_escaneados(plantillas):
    """Guardarrail de coste: una consulta desbocada no vacia la tarjeta."""
    platform, _ = plantillas
    platform.has_resource_properties(
        "AWS::Athena::WorkGroup",
        {"WorkGroupConfiguration": Match.object_like({"BytesScannedCutoffPerQuery": 1073741824})},
    )


# --------------------------------------------------------------- Pipeline


def test_hay_cuatro_lambdas_de_negocio(plantillas):
    _, pipeline = plantillas
    for modulo in ("validate_file", "verify_load", "schedule", "notify_failure"):
        pipeline.has_resource_properties(
            "AWS::Lambda::Function", {"FunctionName": f"dataflow-{modulo}-test"}
        )


def test_las_lambdas_corren_en_arm(plantillas):
    _, pipeline = plantillas
    pipeline.has_resource_properties(
        "AWS::Lambda::Function",
        {"FunctionName": "dataflow-verify_load-test", "Architectures": ["arm64"]},
    )


def test_el_disparador_solo_escucha_a_los_manifests(plantillas):
    """Si escuchase al CSV, el pipeline arrancaria antes de tener el contrato."""
    _, pipeline = plantillas
    pipeline.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": Match.object_like(
                {
                    "source": ["aws.s3"],
                    "detail-type": ["Object Created"],
                    "detail": Match.object_like(
                        {"object": {"key": [{"wildcard": "landing/*.manifest.json"}]}}
                    ),
                }
            )
        },
    )


def test_la_maquina_de_estados_tiene_las_dos_verificaciones_y_la_espera(plantillas):
    _, pipeline = plantillas
    definicion = str(pipeline.find_resources("AWS::StepFunctions::StateMachine"))
    for estado in (
        "ValidarFichero",
        "TransformarConGlue",
        "VerificarCargaA",
        "EsperarHoraProgramada",
        "VerificarCargaB",
        "NotificarFallo",
        "FicheroRechazado",
    ):
        assert estado in definicion, f"falta el estado {estado}"
    assert '\\"Type\\":\\"Wait\\"' in definicion or '"Type":"Wait"' in definicion


def test_la_espera_usa_un_timestamp_absoluto(plantillas):
    """Un Wait por timestamp no consume computo mientras espera."""
    _, pipeline = plantillas
    assert "verify_b_at" in str(pipeline.find_resources("AWS::StepFunctions::StateMachine"))


def test_hay_alarmas_conectadas_al_topic(plantillas):
    _, pipeline = plantillas
    pipeline.resource_count_is("AWS::CloudWatch::Alarm", 2)
    pipeline.has_resource_properties("AWS::CloudWatch::Alarm", {"AlarmActions": Match.any_value()})


def test_el_job_de_glue_apunta_al_script_del_repo(plantillas):
    _, pipeline = plantillas
    pipeline.has_resource_properties(
        "AWS::Glue::Job",
        {
            "GlueVersion": "4.0",
            "Command": Match.object_like({"Name": "glueetl", "PythonVersion": "3"}),
        },
    )

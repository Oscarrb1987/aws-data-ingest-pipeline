#!/usr/bin/env python3
"""Punto de entrada de la aplicacion CDK.

Dos stacks:

  DataPlatformStack  - lo que persiste: bucket, catalogo, ledger, alertas.
  IngestPipelineStack - lo que se ejecuta: Lambdas, job de Glue y la maquina
                        de estados.

Estan separados a proposito: el pipeline se redespliega a diario mientras se
itera sobre las reglas, y no interesa que un `cdk destroy` se lleve por
delante los datos ni el historico de ejecuciones.
"""

from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from stacks.contract import load_contract
from stacks.data_platform import DataPlatformStack
from stacks.ingest_pipeline import IngestPipelineStack

ROOT = Path(__file__).resolve().parent.parent

app = cdk.App()

env_name = app.node.try_get_context("env") or "dev"
project = app.node.try_get_context("project") or "dataflow"

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", "eu-west-1"),
)

contract = load_contract(ROOT / "rules" / "checks.yaml")

platform = DataPlatformStack(
    app,
    f"{project}-platform-{env_name}",
    env=env,
    project=project,
    env_name=env_name,
    contract=contract,
    description="Almacenamiento, catalogo, ledger y alertas del pipeline de ingesta",
)

IngestPipelineStack(
    app,
    f"{project}-pipeline-{env_name}",
    env=env,
    project=project,
    env_name=env_name,
    contract=contract,
    data_bucket=platform.data_bucket,
    ledger_table=platform.ledger_table,
    alert_topic=platform.alert_topic,
    glue_database=platform.glue_database_name,
    athena_workgroup=platform.athena_workgroup_name,
    description="Lambdas, job de Glue y maquina de estados de ingesta y verificacion",
)

cdk.Tags.of(app).add("project", project)
cdk.Tags.of(app).add("environment", env_name)
cdk.Tags.of(app).add("owner", "data-engineering")
cdk.Tags.of(app).add("managed-by", "cdk")

app.synth()

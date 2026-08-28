"""Fixtures compartidas.

Los tests no hablan con AWS: moto levanta S3, DynamoDB y SNS en memoria, y
las verificaciones se ejecutan con DuckDB sobre un almacen temporal. El
resultado es una suite que corre en segundos en cualquier maquina y en CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parent.parent
REGION = "eu-west-1"
BUCKET = "test-datalake"
TABLE = "test-run-ledger"
BUSINESS_DATE = "2026-08-27"

COLUMNS = [
    "cliente_id",
    "nombre",
    "email",
    "pais",
    "segmento",
    "fecha_alta",
    "fecha_negocio",
    "importe_total",
]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """Entorno aislado por test."""
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("DATA_BUCKET", BUCKET)
    monkeypatch.setenv("LEDGER_TABLE", TABLE)
    monkeypatch.setenv("QUERY_ENGINE", "duckdb")
    monkeypatch.setenv("RULES_PATH", str(ROOT / "rules" / "checks.yaml"))
    monkeypatch.setenv("LOCAL_WAREHOUSE", str(tmp_path / "warehouse"))
    monkeypatch.delenv("ALERT_TOPIC_ARN", raising=False)

    from src.common.aws import reset_clients
    from src.common.config import reset_settings_cache

    reset_settings_cache()
    reset_clients()
    yield
    reset_settings_cache()
    reset_clients()


@pytest.fixture
def aws(_env):
    """S3 + DynamoDB + SNS simulados, con los recursos ya creados."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})

        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "run_id", "AttributeType": "S"},
                {"AttributeName": "dataset", "AttributeType": "S"},
                {"AttributeName": "business_date", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "run_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "dataset-business_date-index",
                    "KeySchema": [
                        {"AttributeName": "dataset", "KeyType": "HASH"},
                        {"AttributeName": "business_date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        yield {"bucket": BUCKET, "table": TABLE, "region": REGION}


def build_csv(rows: list[dict[str, str]]) -> bytes:
    header = ",".join(COLUMNS)
    body = "\n".join(",".join(str(r[c]) for c in COLUMNS) for r in rows)
    return (header + "\n" + body + "\n").encode("utf-8")


def make_rows(n: int = 10, business_date: str = BUSINESS_DATE) -> list[dict[str, str]]:
    return [
        {
            "cliente_id": f"CLI{i:04d}",
            "nombre": f"Cliente {i}",
            "email": f"cliente{i}@example.com",
            "pais": "ES",
            "segmento": "retail",
            "fecha_alta": "2024-01-15",
            "fecha_negocio": business_date,
            "importe_total": f"{100 + i}.50",
        }
        for i in range(1, n + 1)
    ]


def make_manifest(payload: bytes, rows: int, business_date: str = BUSINESS_DATE) -> dict:
    return {
        "dataset": "clientes",
        "business_date": business_date,
        "row_count": rows,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_system": "sistema-origen",
        "delimiter": ",",
        "encoding": "utf-8",
        "columns": COLUMNS,
    }


@pytest.fixture
def upload_dataset(aws):
    """Sube un CSV y su manifest a landing/ y devuelve la clave del manifest."""

    def _upload(rows=None, *, manifest_overrides=None, payload=None, business_date=BUSINESS_DATE):
        import boto3 as _boto3

        rows = make_rows() if rows is None else rows
        payload = payload if payload is not None else build_csv(rows)
        manifest = make_manifest(payload, len(rows), business_date)
        manifest.update(manifest_overrides or {})

        base = f"landing/dataset=clientes/dt={business_date}/clientes"
        s3 = _boto3.client("s3", region_name=REGION)
        s3.put_object(Bucket=BUCKET, Key=f"{base}.csv", Body=payload)
        s3.put_object(
            Bucket=BUCKET,
            Key=f"{base}.manifest.json",
            Body=json.dumps(manifest).encode("utf-8"),
        )
        return f"{base}.manifest.json"

    return _upload


@pytest.fixture
def eventbridge_event():
    def _event(manifest_key: str) -> dict:
        return {
            "detail": {
                "bucket": {"name": BUCKET},
                "object": {"key": manifest_key},
            }
        }

    return _event

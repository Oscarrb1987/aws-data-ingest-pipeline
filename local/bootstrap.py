#!/usr/bin/env python3
"""Crea en LocalStack los recursos que en AWS crea CDK.

Equivalente reducido de `DataPlatformStack`: bucket, tabla del ledger con su
indice y topic de alertas.

Uso:  python local/bootstrap.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local import env  # noqa: E402

env.configure()

from src.common.aws import client  # noqa: E402
from src.common.config import get_settings  # noqa: E402


def create_bucket(settings) -> None:
    s3 = client("s3")
    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if settings.data_bucket in existing:
        print(f"  bucket ya existe: {settings.data_bucket}")
        return
    kwargs = {"Bucket": settings.data_bucket}
    if settings.region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.region}
    s3.create_bucket(**kwargs)
    print(f"  bucket creado: {settings.data_bucket}")


def create_table(settings) -> None:
    ddb = client("dynamodb")
    if settings.ledger_table in ddb.list_tables().get("TableNames", []):
        print(f"  tabla ya existe: {settings.ledger_table}")
        return
    ddb.create_table(
        TableName=settings.ledger_table,
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
    ddb.get_waiter("table_exists").wait(TableName=settings.ledger_table)
    print(f"  tabla creada: {settings.ledger_table}")


def create_topic(_settings) -> None:
    arn = env.resolve_alert_topic()
    print(f"  topic listo: {arn}")


def reset_warehouse(settings) -> None:
    warehouse = Path(settings.local_warehouse)
    if warehouse.exists():
        shutil.rmtree(warehouse)
    warehouse.mkdir(parents=True, exist_ok=True)
    print(f"  almacen local limpio: {warehouse}")


def main() -> int:
    settings = get_settings()
    print(f"Preparando entorno local en {settings.endpoint_url}")
    try:
        create_bucket(settings)
        create_table(settings)
        create_topic(settings)
        reset_warehouse(settings)
    except Exception as exc:
        print(f"\nERROR: no se pudo contactar con LocalStack ({exc})")
        print("Levantalo con:  make up")
        return 1
    print("\nEntorno listo. Ejecuta:  make demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

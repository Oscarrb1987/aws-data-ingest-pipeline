"""Configuracion de entorno para la demo local.

Apunta los clientes boto3 a LocalStack y selecciona DuckDB como motor de
consulta. Nada mas: el codigo del pipeline es identico al que se ejecuta en
AWS.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "AWS_REGION": "eu-west-1",
    "AWS_DEFAULT_REGION": "eu-west-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "AWS_ENDPOINT_URL": "http://localhost:4566",
    "DATA_BUCKET": "dataflow-datalake-local",
    "LEDGER_TABLE": "dataflow-run-ledger",
    "QUERY_ENGINE": "duckdb",
    "RULES_PATH": str(ROOT / "rules" / "checks.yaml"),
    "LOCAL_WAREHOUSE": str(ROOT / "local" / "out" / "warehouse"),
    "VERIFY_B_DELAY_SECONDS": "5",
    "LOG_LEVEL": "INFO",
}


ALERT_TOPIC_NAME = "dataflow-alerts"


def configure(**overrides: str) -> None:
    """Aplica la configuracion local sin pisar lo que ya venga del entorno."""
    _load_dotenv()
    for key, value in {**DEFAULTS, **overrides}.items():
        os.environ.setdefault(key, str(value))
    _reset()


def resolve_alert_topic() -> str | None:
    """Descubre el ARN del topic en vez de suponer el numero de cuenta.

    `create_topic` es idempotente, asi que sirve tanto para crearlo como para
    resolverlo, y el codigo funciona igual contra LocalStack o contra AWS.
    """
    if os.getenv("ALERT_TOPIC_ARN"):
        return os.environ["ALERT_TOPIC_ARN"]

    from src.common.aws import client

    try:
        arn = client("sns").create_topic(Name=ALERT_TOPIC_NAME)["TopicArn"]
    except Exception:
        return None

    os.environ["ALERT_TOPIC_ARN"] = arn
    _reset()
    return arn


def _reset() -> None:
    from src.common.aws import reset_clients
    from src.common.config import reset_settings_cache

    reset_settings_cache()
    reset_clients()


def _load_dotenv() -> None:
    dotenv = ROOT / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

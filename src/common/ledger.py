"""Registro de ejecuciones en DynamoDB.

Sustituye a la hoja de calculo o al correo donde hoy se anota "cargado, ok".
Cada ejecucion deja rastro consultable: quien, que fichero, cuantas filas,
que reglas pasaron y en que momento se verifico cada fase.

Clave de particion `run_id`; ademas un GSI por dataset+fecha permite
responder a "que paso con clientes el dia 27" sin escanear la tabla.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from src.common.aws import resource
from src.common.config import get_settings
from src.common.models import RunStatus, utcnow

GSI_NAME = "dataset-business_date-index"


def new_run_id(dataset: str, business_date: str) -> str:
    return f"{dataset}-{business_date}-{uuid.uuid4().hex[:8]}"


def _table():
    return resource("dynamodb").Table(get_settings().ledger_table)


def _to_dynamo(value: Any) -> Any:
    """DynamoDB no acepta float: se convierte a Decimal de forma recursiva."""
    if isinstance(value, float):
        return Decimal(str(round(value, 6)))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def register(run_id: str, dataset: str, business_date: str, source_key: str, **extra: Any) -> None:
    item = {
        "run_id": run_id,
        "dataset": dataset,
        "business_date": business_date,
        "source_key": source_key,
        "status": str(RunStatus.RECEIVED),
        "created_at": utcnow(),
        "updated_at": utcnow(),
        **extra,
    }
    _table().put_item(Item=_to_dynamo(item))


def update(run_id: str, status: RunStatus | None = None, **fields: Any) -> None:
    """Actualiza el registro. `status` es palabra reservada en DynamoDB."""
    payload: dict[str, Any] = {"updated_at": utcnow(), **fields}
    if status is not None:
        payload["status"] = str(status)

    names = {f"#f{i}": k for i, k in enumerate(payload)}
    values = {f":v{i}": _to_dynamo(v) for i, v in enumerate(payload.values())}
    expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(payload)))

    _table().update_item(
        Key={"run_id": run_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def get(run_id: str) -> dict[str, Any] | None:
    item = _table().get_item(Key={"run_id": run_id}).get("Item")
    return _from_dynamo(item) if item else None


def find_by_dataset(dataset: str, business_date: str) -> list[dict[str, Any]]:
    """Consulta el GSI. Usado por el informe diario y para detectar recargas."""
    from boto3.dynamodb.conditions import Key

    response = _table().query(
        IndexName=GSI_NAME,
        KeyConditionExpression=Key("dataset").eq(dataset) & Key("business_date").eq(business_date),
    )
    return [_from_dynamo(i) for i in response.get("Items", [])]

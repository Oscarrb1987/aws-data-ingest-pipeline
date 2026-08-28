"""Motor Athena: el que se usa en AWS.

Athena consulta el Parquet que deja el job de Glue sobre S3, usando el Glue
Data Catalog como metastore. No hay servidores que mantener y se paga por
byte escaneado, que con particionado por fecha es del orden de centimos por
verificacion.
"""

from __future__ import annotations

import time
from typing import Any

from src.common.aws import client
from src.common.config import get_settings
from src.common.logging import get_logger, log_event
from src.common.rules import DatasetRules
from src.engines.base import QueryEngine

logger = get_logger(__name__)

_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AthenaQueryError(RuntimeError):
    pass


class AthenaEngine(QueryEngine):
    def __init__(
        self,
        database: str | None = None,
        workgroup: str | None = None,
        output_location: str | None = None,
        poll_seconds: float = 1.0,
        timeout_seconds: float = 300.0,
    ) -> None:
        settings = get_settings()
        self.database = database or settings.glue_database
        self.workgroup = workgroup or settings.athena_workgroup
        self.output_location = output_location or settings.athena_output_location
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def table_ref(self, rules: DatasetRules) -> str:
        return f'"{self.database}"."{rules.table}"'

    def scalar(self, sql: str) -> Any:
        rows = self._execute(sql)
        if not rows:
            return None
        return rows[0][0] if rows[0] else None

    def _execute(self, sql: str) -> list[list[Any]]:
        athena = client("athena")
        kwargs: dict[str, Any] = {
            "QueryString": sql,
            "QueryExecutionContext": {"Database": self.database},
            "WorkGroup": self.workgroup,
        }
        if self.output_location:
            kwargs["ResultConfiguration"] = {"OutputLocation": self.output_location}

        execution_id = athena.start_query_execution(**kwargs)["QueryExecutionId"]
        state, reason = self._wait(athena, execution_id)
        if state != "SUCCEEDED":
            raise AthenaQueryError(f"consulta Athena {state}: {reason} | SQL: {sql}")

        result = athena.get_query_results(QueryExecutionId=execution_id, MaxResults=100)
        rows = result["ResultSet"]["Rows"][1:]  # la primera fila es la cabecera
        return [[c.get("VarCharValue") for c in r.get("Data", [])] for r in rows]

    def _wait(self, athena: Any, execution_id: str) -> tuple[str, str]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            info = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]
            status = info["Status"]
            if status["State"] in _TERMINAL:
                log_event(
                    logger,
                    "consulta athena finalizada",
                    execution_id=execution_id,
                    state=status["State"],
                    scanned_bytes=info.get("Statistics", {}).get("DataScannedInBytes"),
                )
                return status["State"], status.get("StateChangeReason", "")
            time.sleep(self.poll_seconds)
        raise AthenaQueryError(f"timeout esperando la consulta {execution_id}")

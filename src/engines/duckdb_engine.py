"""Motor DuckDB: el que se usa en la demo local.

Lee el mismo Parquet particionado que produciria Glue, pero desde disco, de
forma que las reglas SQL que se ejecutan en local son literalmente las mismas
que se ejecutan contra Athena en AWS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.config import get_settings
from src.common.rules import DatasetRules
from src.engines.base import QueryEngine


class DuckDBEngine(QueryEngine):
    def __init__(self, warehouse: str | Path | None = None) -> None:
        import duckdb  # import diferido: no es dependencia de las Lambdas

        self.warehouse = Path(warehouse or get_settings().local_warehouse)
        self._conn = duckdb.connect(":memory:")

    def table_ref(self, rules: DatasetRules) -> str:
        """DuckDB puede leer un arbol de Parquet particionado como si fuese una tabla."""
        pattern = (self.warehouse / rules.table / "**" / "*.parquet").as_posix()
        return f"read_parquet('{pattern}', hive_partitioning = true)"

    def scalar(self, sql: str) -> Any:
        row = self._conn.execute(sql).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self._conn.close()

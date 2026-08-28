"""Equivalente local del job de Glue, implementado con DuckDB.

Mantiene el mismo contrato de comportamiento que `glue_jobs/landing_to_curated.py`:

  - esquema explicito tomado del YAML (nunca inferido)
  - cadenas vacias normalizadas a NULL
  - columna de particion `dt` y metadatos de trazabilidad
  - escritura idempotente: reejecutar sobreescribe la particion

Gracias a esto, la demo sin cuenta de AWS ejercita el mismo camino logico que
la version desplegada.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.common import storage
from src.common.logging import get_logger, log_event
from src.common.rules import DatasetRules

logger = get_logger(__name__)

_DUCK_TYPES = {
    "string": "VARCHAR",
    "int": "INTEGER",
    "integer": "INTEGER",
    "double": "DOUBLE",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
}


def run_local_transform(
    *,
    bucket: str,
    source_key: str,
    rules: DatasetRules,
    business_date: str,
    run_id: str,
    warehouse: str | Path,
    delimiter: str = ",",
) -> int:
    """Convierte el CSV de landing en Parquet particionado. Devuelve las filas escritas."""
    import duckdb

    warehouse = Path(warehouse)
    target = warehouse / rules.table
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "landing.csv"
        csv_path.write_bytes(storage.get_bytes(bucket, source_key))

        conn = duckdb.connect(":memory:")
        try:
            columns = ", ".join(
                f"'{c.name}': '{_DUCK_TYPES.get(c.type, 'VARCHAR')}'" for c in rules.columns
            )
            reader = (
                f"read_csv('{csv_path.as_posix()}', header = true, "
                f"delim = '{delimiter}', columns = {{{columns}}}, "
                f"ignore_errors = false, all_varchar = false)"
            )

            projection = ", ".join(_project(c.name, c.type) for c in rules.columns)
            select = (
                f"SELECT {projection}, "
                f"'{business_date}' AS dt, "
                f"'{run_id}' AS _run_id, "
                f"now() AS _ingested_at "
                f"FROM {reader}"
            )

            rows = conn.execute(f"SELECT COUNT(*) FROM ({select})").fetchone()[0]

            _clear_partition(target, business_date)
            conn.execute(
                f"COPY ({select}) TO '{target.as_posix()}' "
                f"(FORMAT PARQUET, PARTITION_BY (dt), OVERWRITE_OR_IGNORE 1)"
            )
        finally:
            conn.close()

    log_event(
        logger,
        "transformacion local completada",
        dataset=rules.name,
        business_date=business_date,
        rows=rows,
        target=str(target),
    )
    return int(rows)


def _project(name: str, type_: str) -> str:
    """Normaliza como lo hace el job de Glue: trim + vacio -> NULL."""
    if _DUCK_TYPES.get(type_, "VARCHAR") == "VARCHAR":
        return f'NULLIF(TRIM("{name}"), \'\') AS "{name}"'
    return f'"{name}"'


def _clear_partition(target: Path, business_date: str) -> None:
    """Sobrescritura dinamica de particion: solo se borra la fecha afectada."""
    partition = target / f"dt={business_date}"
    if partition.exists():
        for file in partition.glob("*"):
            file.unlink()

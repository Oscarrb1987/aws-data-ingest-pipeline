"""Transformacion landing -> curated.

En AWS la ejecuta un job de Glue (PySpark). En la demo local la ejecuta
DuckDB, aplicando exactamente las mismas reglas de esquema y normalizacion,
para que el resultado que verifican las reglas SQL sea equivalente.
"""

from src.transform.local_transform import run_local_transform

__all__ = ["run_local_transform"]

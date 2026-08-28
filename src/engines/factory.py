"""Seleccion del motor de consulta segun entorno."""

from __future__ import annotations

from src.common.config import get_settings
from src.engines.base import QueryEngine


def get_engine(name: str | None = None) -> QueryEngine:
    engine = (name or get_settings().query_engine).lower()
    if engine == "athena":
        from src.engines.athena import AthenaEngine

        return AthenaEngine()
    if engine == "duckdb":
        from src.engines.duckdb_engine import DuckDBEngine

        return DuckDBEngine()
    raise ValueError(f"motor de consulta desconocido: '{engine}' (usa 'athena' o 'duckdb')")

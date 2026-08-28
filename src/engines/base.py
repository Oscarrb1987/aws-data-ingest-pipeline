"""Interfaz comun de los motores de consulta."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.common.models import Fingerprint
from src.common.rules import DatasetRules, _escape, _ident


class QueryEngine(ABC):
    """Puerto: ejecuta SQL y sabe como se referencia una tabla curada."""

    @abstractmethod
    def table_ref(self, rules: DatasetRules) -> str:
        """Nombre completamente cualificado de la tabla curada."""

    @abstractmethod
    def scalar(self, sql: str) -> Any:
        """Ejecuta un SQL que devuelve una unica fila y columna."""

    def close(self) -> None:  # noqa: B027 - cierre opcional segun motor
        """Libera recursos si el motor los mantiene abiertos (Athena no los tiene)."""

    def fingerprint(self, rules: DatasetRules, business_date: str) -> Fingerprint:
        """Huella de la particion, usada para detectar cambios entre A y B."""
        table = self.table_ref(rules)
        where = rules.partition_filter(business_date)

        row_count = int(self.scalar(f"SELECT COUNT(*) AS value FROM {table} WHERE {where}") or 0)

        if rules.numeric_columns:
            total = " + ".join(
                f"COALESCE(CAST({_ident(c)} AS DOUBLE), 0)" for c in rules.numeric_columns
            )
            checksum = float(
                self.scalar(f"SELECT COALESCE(SUM({total}), 0) AS value FROM {table} WHERE {where}")
                or 0.0
            )
        else:
            checksum = 0.0

        if rules.primary_key:
            keys = ", ".join(f"CAST({_ident(c)} AS VARCHAR)" for c in rules.primary_key)
            concat = keys if len(rules.primary_key) == 1 else f"CONCAT_WS('|', {keys})"
            distinct = int(
                self.scalar(f"SELECT COUNT(DISTINCT {concat}) AS value FROM {table} WHERE {where}")
                or 0
            )
        else:
            distinct = row_count

        return Fingerprint(row_count=row_count, numeric_checksum=checksum, distinct_keys=distinct)

    def partition_exists(self, rules: DatasetRules, business_date: str) -> bool:
        table = self.table_ref(rules)
        where = f"\"{rules.partition_column}\" = '{_escape(business_date)}'"
        return int(self.scalar(f"SELECT COUNT(*) AS value FROM {table} WHERE {where}") or 0) > 0

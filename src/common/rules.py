"""Motor de reglas de calidad declarativas.

Las reglas viven en YAML, no en el codigo: anadir una comprobacion nueva a un
dataset es un cambio de configuracion revisable en un pull request, no un
despliegue de logica.

Cada regla se compila a una sentencia SQL que devuelve una sola columna
`value`. El motor de consulta (Athena en AWS, DuckDB en local) es
intercambiable porque solo tiene que saber ejecutar ese SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.common.models import CheckResult, Severity


class RulesError(ValueError):
    """Error de configuracion en el fichero de reglas."""


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str = "string"
    required: bool = False


@dataclass(frozen=True, slots=True)
class Assertion:
    """Regla ya compilada: un SQL y como interpretar su resultado."""

    check_id: str
    severity: Severity
    sql: str
    comparator: str  # "zero" -> se espera 0 violaciones | "equals" -> valor exacto
    expected: Any
    description: str

    def evaluate(self, observed: Any) -> CheckResult:
        observed = _coerce(observed)
        passed = observed == 0 if self.comparator == "zero" else observed == self.expected
        detail = (
            f"{self.description}: OK"
            if passed
            else f"{self.description}: observado {observed}, esperado {self.expected}"
        )
        return CheckResult(
            check_id=self.check_id,
            passed=passed,
            severity=self.severity,
            observed=observed,
            expected=self.expected,
            message=detail,
            sql=self.sql,
        )


@dataclass(slots=True)
class DatasetRules:
    """Contrato completo de un dataset."""

    name: str
    table: str
    primary_key: list[str]
    business_date_column: str
    columns: list[Column]
    checks: list[dict[str, Any]] = field(default_factory=list)
    numeric_columns: list[str] = field(default_factory=list)
    partition_column: str = "dt"

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def required_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.required]

    def partition_filter(self, business_date: str) -> str:
        return f"\"{self.partition_column}\" = '{_escape(business_date)}'"

    def compile(self, table_ref: str, business_date: str, expected_rows: int) -> list[Assertion]:
        """Traduce las reglas YAML a sentencias SQL ejecutables."""
        where = self.partition_filter(business_date)
        assertions: list[Assertion] = []
        for raw in self.checks:
            assertions.extend(
                self._compile_one(raw, table_ref, where, business_date, expected_rows)
            )
        return assertions

    def _compile_one(
        self,
        raw: dict[str, Any],
        table: str,
        where: str,
        business_date: str,
        expected_rows: int,
    ) -> list[Assertion]:
        try:
            kind = raw["type"]
            base_id = raw["id"]
        except KeyError as exc:  # pragma: no cover - error de configuracion
            raise RulesError(f"regla sin '{exc.args[0]}': {raw}") from exc

        severity = Severity(raw.get("severity", "critical"))
        out: list[Assertion] = []

        match kind:
            case "row_count":
                out.append(
                    Assertion(
                        check_id=base_id,
                        severity=severity,
                        sql=f"SELECT COUNT(*) AS value FROM {table} WHERE {where}",
                        comparator="equals",
                        expected=expected_rows,
                        description="filas cargadas frente al manifest",
                    )
                )

            case "not_null":
                for col in raw.get("columns") or self.required_columns:
                    c = _ident(col)
                    out.append(
                        Assertion(
                            check_id=f"{base_id}__{col}",
                            severity=severity,
                            sql=(
                                f"SELECT COUNT(*) AS value FROM {table} "
                                f"WHERE {where} AND ({c} IS NULL OR CAST({c} AS VARCHAR) = '')"
                            ),
                            comparator="zero",
                            expected=0,
                            description=f"nulos en columna obligatoria '{col}'",
                        )
                    )

            case "unique":
                cols = raw.get("columns") or self.primary_key
                keys = ", ".join(_ident(c) for c in cols)
                out.append(
                    Assertion(
                        check_id=base_id,
                        severity=severity,
                        sql=(
                            f"SELECT COALESCE(SUM(dups), 0) AS value FROM ("
                            f"SELECT COUNT(*) - 1 AS dups FROM {table} WHERE {where} "
                            f"GROUP BY {keys} HAVING COUNT(*) > 1) t"
                        ),
                        comparator="zero",
                        expected=0,
                        description=f"duplicados en clave ({', '.join(cols)})",
                    )
                )

            case "expression":
                expr = raw["expression"]
                out.append(
                    Assertion(
                        check_id=base_id,
                        severity=severity,
                        sql=(
                            f"SELECT COUNT(*) AS value FROM {table} WHERE {where} AND NOT ({expr})"
                        ),
                        comparator="zero",
                        expected=0,
                        description=raw.get("description", f"expresion '{expr}'"),
                    )
                )

            case "accepted_values":
                col = _ident(raw["column"])
                values = ", ".join(f"'{_escape(str(v))}'" for v in raw["values"])
                out.append(
                    Assertion(
                        check_id=base_id,
                        severity=severity,
                        sql=(
                            f"SELECT COUNT(*) AS value FROM {table} "
                            f"WHERE {where} AND {col} IS NOT NULL AND {col} NOT IN ({values})"
                        ),
                        comparator="zero",
                        expected=0,
                        description=f"valores fuera del dominio en '{raw['column']}'",
                    )
                )

            case "business_date_matches_partition":
                col = _ident(self.business_date_column)
                out.append(
                    Assertion(
                        check_id=base_id,
                        severity=severity,
                        sql=(
                            f"SELECT COUNT(*) AS value FROM {table} WHERE {where} "
                            f"AND CAST({col} AS VARCHAR) <> '{_escape(business_date)}'"
                        ),
                        comparator="zero",
                        expected=0,
                        description="filas cuya fecha de negocio no cuadra con la particion",
                    )
                )

            case _:
                raise RulesError(f"tipo de regla no soportado: '{kind}'")

        return out


def load_rules(path: str | Path) -> dict[str, DatasetRules]:
    """Carga y valida el fichero de reglas."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    datasets = raw.get("datasets")
    if not datasets:
        raise RulesError(f"{path}: no hay ningun dataset definido")

    result: dict[str, DatasetRules] = {}
    for name, cfg in datasets.items():
        columns = [
            Column(
                name=c["name"],
                type=c.get("type", "string"),
                required=bool(c.get("required", False)),
            )
            for c in cfg.get("schema", [])
        ]
        if not columns:
            raise RulesError(f"dataset '{name}': el esquema no puede estar vacio")
        result[name] = DatasetRules(
            name=name,
            table=cfg.get("table", name),
            primary_key=cfg.get("primary_key", []),
            business_date_column=cfg.get("business_date_column", "fecha_negocio"),
            columns=columns,
            checks=cfg.get("checks", []),
            numeric_columns=cfg.get("numeric_columns", []),
            partition_column=cfg.get("partition_column", "dt"),
        )
    return result


def get_dataset_rules(path: str | Path, dataset: str) -> DatasetRules:
    rules = load_rules(path)
    if dataset not in rules:
        raise RulesError(f"dataset '{dataset}' no definido en {path}")
    return rules[dataset]


def _ident(name: str) -> str:
    """Cita un identificador para evitar colisiones con palabras reservadas."""
    if not name.replace("_", "").isalnum():
        raise RulesError(f"nombre de columna no valido: '{name}'")
    return f'"{name}"'


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _coerce(value: Any) -> Any:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value) if float(value).is_integer() else value
    try:
        return int(str(value))
    except ValueError:
        return value

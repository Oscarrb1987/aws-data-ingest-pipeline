"""Lectura del contrato de datos desde la infraestructura.

El mismo `rules/checks.yaml` que usan las Lambdas para verificar define aqui
las tablas del Glue Data Catalog. Un dataset nuevo son unas lineas de YAML:
no hay que tocar ni el pipeline ni el catalogo a mano, y es imposible que el
esquema declarado y el esquema catalogado se desincronicen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Tipos del contrato -> tipos de Glue/Athena
GLUE_TYPES = {
    "string": "string",
    "int": "int",
    "integer": "int",
    "double": "double",
    "date": "date",
    "timestamp": "timestamp",
}


@dataclass(frozen=True)
class DatasetContract:
    name: str
    table: str
    partition_column: str
    columns: list[tuple[str, str]]

    @property
    def glue_columns(self) -> list[dict[str, str]]:
        """Columnas de datos mas los metadatos que anade el job de Glue."""
        cols = [{"name": n, "type": GLUE_TYPES.get(t, "string")} for n, t in self.columns]
        cols.append({"name": "_run_id", "type": "string"})
        cols.append({"name": "_ingested_at", "type": "timestamp"})
        return cols


def load_contract(path: str | Path) -> list[DatasetContract]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    contracts: list[DatasetContract] = []
    for name, cfg in raw["datasets"].items():
        contracts.append(
            DatasetContract(
                name=name,
                table=cfg.get("table", name),
                partition_column=cfg.get("partition_column", "dt"),
                columns=[(c["name"], c.get("type", "string")) for c in cfg["schema"]],
            )
        )
    return contracts

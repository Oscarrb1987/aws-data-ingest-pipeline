#!/usr/bin/env python3
"""Genera los ficheros de ejemplo y sus manifests.

Tres casos, uno por cada camino de la maquina de estados:

  clientes_ok     -> pasa validacion y verificacion
  clientes_ko     -> el manifest no cuadra con el fichero: cuarentena
  clientes_sucio  -> el manifest cuadra, pero los datos incumplen reglas
                     criticas: la verificacion A lo detiene

Ejecutar: python scripts/make_sample_data.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data"
BUSINESS_DATE = "2026-08-27"
COLUMNS = [
    "cliente_id",
    "nombre",
    "email",
    "pais",
    "segmento",
    "fecha_alta",
    "fecha_negocio",
    "importe_total",
]
NOMBRES = ["Ana", "Luis", "Marta", "Diego", "Sofia", "Pablo", "Elena", "Hugo", "Carla", "Ivan"]
APELLIDOS = ["Garcia", "Lopez", "Martin", "Ruiz", "Sanz", "Vidal", "Ortega", "Bravo"]
PAISES = ["ES", "PT", "FR", "IT", "DE", "NL", "BE"]
SEGMENTOS = ["retail", "premium", "corporate"]


def make_row(i: int, rng: random.Random) -> dict[str, str]:
    nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
    return {
        "cliente_id": f"CLI{i:06d}",
        "nombre": nombre,
        "email": f"{nombre.split()[0].lower()}.{i}@example.com",
        "pais": rng.choice(PAISES),
        "segmento": rng.choice(SEGMENTOS),
        "fecha_alta": f"20{rng.randint(20, 25)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        "fecha_negocio": BUSINESS_DATE,
        "importe_total": f"{rng.uniform(10, 5000):.2f}",
    }


def to_csv(rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def write(name: str, payload: bytes, *, declared_rows: int | None = None, sha: str | None = None):
    csv_path = OUT / f"{name}.csv"
    csv_path.write_bytes(payload)

    manifest = {
        "dataset": "clientes",
        "business_date": BUSINESS_DATE,
        "row_count": declared_rows if declared_rows is not None else payload.count(b"\n") - 1,
        "sha256": sha or hashlib.sha256(payload).hexdigest(),
        "source_system": "sistema-origen",
        "delimiter": ",",
        "encoding": "utf-8",
        "columns": COLUMNS,
        "generated_at": f"{BUSINESS_DATE}T06:15:00Z",
    }
    (OUT / f"{name}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  {name}.csv ({len(payload)} bytes, {manifest['row_count']} filas declaradas)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260827)
    rows = [make_row(i, rng) for i in range(1, 201)]

    print("Generando datos de ejemplo:")

    # 1) Caso correcto
    write("clientes_ok", to_csv(rows))

    # 2) Manifest que no cuadra: faltan filas y el checksum es de otro fichero
    truncated = to_csv(rows[:198])
    write("clientes_ko", truncated, declared_rows=200, sha=hashlib.sha256(b"otro").hexdigest())

    # 3) Manifest correcto, datos sucios: PK duplicada, pais fuera de dominio,
    #    importe negativo y un obligatorio a nulo.
    dirty = [dict(r) for r in rows]
    dirty[10]["cliente_id"] = dirty[9]["cliente_id"]  # duplicado
    dirty[20]["pais"] = "XX"  # fuera de dominio
    dirty[30]["importe_total"] = "-42.00"  # negativo
    dirty[40]["email"] = ""  # obligatorio vacio
    write("clientes_sucio", to_csv(dirty))

    print(f"\nListo en {OUT}")


if __name__ == "__main__":
    main()

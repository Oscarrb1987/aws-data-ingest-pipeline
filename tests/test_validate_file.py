"""Validacion previa a la carga: la puerta que evita arrancar Glue en balde."""

from __future__ import annotations

import pytest

from src.common import ledger, storage
from src.handlers import validate_file
from src.handlers.errors import ValidationFailed
from tests.conftest import BUCKET, build_csv, make_rows


def test_fichero_correcto_pasa_y_queda_registrado(upload_dataset, eventbridge_event):
    key = upload_dataset(make_rows(10))
    result = validate_file.handler(eventbridge_event(key))

    assert result["dataset"] == "clientes"
    assert result["expected_rows"] == 10
    assert result["status"] == "VALIDATED"
    assert result["table"] == "clientes"

    registro = ledger.get(result["run_id"])
    assert registro["status"] == "VALIDATED"
    assert registro["expected_rows"] == 10


def test_checksum_que_no_cuadra_manda_el_fichero_a_cuarentena(upload_dataset, eventbridge_event):
    key = upload_dataset(make_rows(10), manifest_overrides={"sha256": "0" * 64})

    with pytest.raises(ValidationFailed, match="checksum"):
        validate_file.handler(eventbridge_event(key))

    cuarentena = storage.list_keys(BUCKET, "quarantine/")
    assert any(k.endswith("clientes.csv") for k in cuarentena)
    assert any(k.endswith(".motivo.txt") for k in cuarentena)
    # y el CSV ya no esta en landing
    assert not any(k.endswith(".csv") for k in storage.list_keys(BUCKET, "landing/"))


def test_numero_de_filas_distinto_al_declarado(upload_dataset, eventbridge_event):
    rows = make_rows(10)
    payload = build_csv(rows[:8])  # el fichero llega truncado
    # El manifest declara 10 filas y el checksum del payload real, asi que el
    # unico incumplimiento es el conteo.
    key = upload_dataset(rows, payload=payload)

    with pytest.raises(ValidationFailed, match="filas"):
        validate_file.handler(eventbridge_event(key))


def test_falta_una_columna_obligatoria(upload_dataset, eventbridge_event):
    rows = make_rows(5)
    header = "cliente_id,nombre,pais,segmento,fecha_alta,fecha_negocio,importe_total"
    body = "\n".join(
        ",".join(
            [
                r["cliente_id"],
                r["nombre"],
                r["pais"],
                r["segmento"],
                r["fecha_alta"],
                r["fecha_negocio"],
                r["importe_total"],
            ]
        )
        for r in rows
    )
    payload = (header + "\n" + body + "\n").encode()
    key = upload_dataset(rows, payload=payload)

    with pytest.raises(ValidationFailed, match="columnas obligatorias"):
        validate_file.handler(eventbridge_event(key))


def test_columna_no_declarada_en_el_contrato(upload_dataset, eventbridge_event):
    rows = make_rows(3)
    header = (
        "cliente_id,nombre,email,pais,segmento,fecha_alta,fecha_negocio,importe_total,columna_nueva"
    )
    body = "\n".join(",".join([*r.values(), "extra"]) for r in rows)
    payload = (header + "\n" + body + "\n").encode()
    key = upload_dataset(rows, payload=payload)

    with pytest.raises(ValidationFailed, match="no declaradas"):
        validate_file.handler(eventbridge_event(key))


def test_manifest_que_apunta_a_un_csv_inexistente(aws, eventbridge_event):
    import json

    manifest = {
        "dataset": "clientes",
        "business_date": "2026-08-27",
        "row_count": 5,
        "sha256": "a" * 64,
    }
    key = "landing/dataset=clientes/dt=2026-08-27/fantasma.manifest.json"
    storage.put_bytes(BUCKET, key, json.dumps(manifest).encode(), "application/json")

    with pytest.raises(ValidationFailed, match="no existe"):
        validate_file.handler(eventbridge_event(key))


def test_acepta_evento_de_s3_y_llamada_directa():
    s3_event = {
        "Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "landing/a%20b.json"}}}]
    }
    assert validate_file.extract_location(s3_event) == ("b", "landing/a b.json")
    assert validate_file.extract_location({"bucket": "b", "manifest_key": "k"}) == ("b", "k")

    with pytest.raises(ValidationFailed):
        validate_file.extract_location({"algo": "raro"})

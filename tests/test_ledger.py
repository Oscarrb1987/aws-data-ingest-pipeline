"""Ledger de ejecuciones en DynamoDB."""

from __future__ import annotations

from src.common import ledger
from src.common.models import RunStatus


def test_registrar_y_recuperar(aws):
    ledger.register("r1", "clientes", "2026-08-27", "landing/x.csv", expected_rows=200)
    registro = ledger.get("r1")

    assert registro["status"] == "RECEIVED"
    assert registro["expected_rows"] == 200
    assert registro["created_at"].endswith("Z")


def test_actualizar_estado_y_campos(aws):
    ledger.register("r1", "clientes", "2026-08-27", "landing/x.csv")
    ledger.update("r1", RunStatus.LOADED, rows_written=200)

    registro = ledger.get("r1")
    assert registro["status"] == "LOADED"
    assert registro["rows_written"] == 200


def test_los_decimales_no_rompen_dynamodb(aws):
    """DynamoDB no acepta float: la huella lleva un checksum decimal."""
    ledger.register("r1", "clientes", "2026-08-27", "landing/x.csv")
    ledger.update(
        "r1",
        RunStatus.LOADED,
        fingerprint_a={"row_count": 200, "numeric_checksum": 12345.678, "distinct_keys": 200},
    )

    huella = ledger.get("r1")["fingerprint_a"]
    assert huella["row_count"] == 200
    assert abs(huella["numeric_checksum"] - 12345.678) < 0.001


def test_consulta_por_dataset_y_fecha(aws):
    for i in range(3):
        ledger.register(f"r{i}", "clientes", "2026-08-27", f"landing/x{i}.csv")
    ledger.register("otro", "transacciones", "2026-08-27", "landing/t.csv")

    assert len(ledger.find_by_dataset("clientes", "2026-08-27")) == 3
    assert len(ledger.find_by_dataset("transacciones", "2026-08-27")) == 1


def test_el_run_id_lleva_dataset_y_fecha(aws):
    run_id = ledger.new_run_id("clientes", "2026-08-27")
    assert run_id.startswith("clientes-2026-08-27-")
    assert ledger.new_run_id("clientes", "2026-08-27") != run_id

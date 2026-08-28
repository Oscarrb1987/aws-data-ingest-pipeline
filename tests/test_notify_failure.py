"""Notificacion de fallos: el destino de todos los Catch de la maquina."""

from __future__ import annotations

import json

from src.common import ledger
from src.handlers import notify_failure


def test_traduce_el_error_tecnico_a_un_motivo_legible(aws):
    ledger.register("r1", "clientes", "2026-08-27", "landing/x.csv")

    out = notify_failure.handler(
        {
            "run_id": "r1",
            "dataset": "clientes",
            "business_date": "2026-08-27",
            "error": {
                "Error": "VerificationFailed",
                "Cause": json.dumps({"errorMessage": "duplicados en clave (cliente_id)"}),
            },
        }
    )

    assert out["reason"] == "los datos cargados incumplen reglas criticas"
    registro = ledger.get("r1")
    assert registro["status"] == "FAILED"
    assert "duplicados" in registro["error_cause"]


def test_la_divergencia_deja_un_estado_propio_en_el_ledger(aws):
    ledger.register("r2", "clientes", "2026-08-27", "landing/x.csv")

    notify_failure.handler(
        {
            "run_id": "r2",
            "dataset": "clientes",
            "business_date": "2026-08-27",
            "error": {"Error": "DriftDetected", "Cause": "row_count 200 -> 400"},
        }
    )

    assert ledger.get("r2")["status"] == "DRIFT_DETECTED"


def test_funciona_aunque_no_haya_run_id(aws):
    out = notify_failure.handler({"error": {"Error": "States.TaskFailed", "Cause": "boom"}})
    assert out["notified"] is True
    assert out["reason"] == "fallo la tarea de transformacion"


def test_causa_no_json_se_pasa_tal_cual(aws):
    out = notify_failure.handler({"error": {"Error": "Cualquiera", "Cause": "texto plano"}})
    assert out["error_type"] == "Cualquiera"

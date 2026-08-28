"""Verificacion de la carga: las dos comprobaciones del proceso original.

Estos tests recorren el camino completo -CSV en S3, transformacion a Parquet,
reglas SQL sobre la tabla curada- usando DuckDB como motor. Es el mismo SQL
que ejecuta Athena en AWS.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.common import ledger, storage
from src.common.config import get_settings
from src.common.models import Fingerprint, Phase
from src.common.rules import get_dataset_rules
from src.engines.duckdb_engine import DuckDBEngine
from src.handlers import validate_file, verify_load
from src.handlers.errors import DriftDetected, VerificationFailed
from src.transform import run_local_transform
from tests.conftest import build_csv, make_rows


@pytest.fixture
def cargado(upload_dataset, eventbridge_event):
    """Deja una particion curada lista para verificar y devuelve el estado."""

    def _cargar(rows=None, payload=None):
        rows = make_rows(20) if rows is None else rows
        key = upload_dataset(rows, payload=payload)
        state = validate_file.handler(eventbridge_event(key))

        settings = get_settings()
        rules = get_dataset_rules(settings.rules_path, state["dataset"])
        run_local_transform(
            bucket=state["bucket"],
            source_key=state["source_key"],
            rules=rules,
            business_date=state["business_date"],
            run_id=state["run_id"],
            warehouse=settings.local_warehouse,
        )
        return state

    return _cargar


# --------------------------------------------------------------- Fase A


def test_carga_correcta_supera_la_verificacion_a(cargado):
    state = cargado()
    result = verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})

    assert result["passed"] is True
    assert result["failed_checks"] == []
    assert result["fingerprint"]["row_count"] == 20
    assert result["fingerprint"]["distinct_keys"] == 20
    assert result["report_uri"].startswith("s3://")


def test_el_informe_se_guarda_en_s3_en_json_y_markdown(cargado, aws):
    state = cargado()
    verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})

    informes = storage.list_keys(aws["bucket"], "reports/")
    assert any(k.endswith("_A_POST_LOAD.json") for k in informes)
    assert any(k.endswith("_A_POST_LOAD.md") for k in informes)


def test_la_huella_de_la_fase_a_queda_en_el_ledger(cargado):
    state = cargado()
    verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})

    registro = ledger.get(state["run_id"])
    assert registro["status"] == "LOADED"
    assert registro["fingerprint_a"]["row_count"] == 20


def test_clave_primaria_duplicada_detiene_el_pipeline(cargado):
    rows = make_rows(20)
    rows[5]["cliente_id"] = rows[4]["cliente_id"]
    state = cargado(rows)

    with pytest.raises(VerificationFailed, match="duplicados"):
        verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})

    assert ledger.get(state["run_id"])["status"] == "FAILED"


def test_valor_fuera_del_dominio_detiene_el_pipeline(cargado):
    rows = make_rows(20)
    rows[3]["pais"] = "XX"
    state = cargado(rows)

    with pytest.raises(VerificationFailed, match="dominio"):
        verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})


def test_obligatorio_vacio_se_detecta_como_nulo(cargado):
    """El CSV trae "" y el contrato dice NOT NULL: tiene que fallar."""
    rows = make_rows(20)
    rows[7]["email"] = ""
    state = cargado(rows)

    with pytest.raises(VerificationFailed, match="nulos"):
        verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})


def test_importe_negativo_detiene_el_pipeline(cargado):
    rows = make_rows(20)
    rows[2]["importe_total"] = "-15.00"
    state = cargado(rows)

    with pytest.raises(VerificationFailed):
        verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})


def test_un_warning_no_detiene_el_pipeline(cargado):
    """Segmento desconocido esta marcado como warning en el contrato."""
    rows = make_rows(20)
    rows[1]["segmento"] = "desconocido"
    state = cargado(rows)

    result = verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})
    assert result["passed"] is True
    assert "segmento_conocido" in result["failed_checks"]


def test_faltan_filas_en_curated_frente_al_manifest(cargado, aws):
    """La transformacion pierde filas por el camino.

    El fichero de origen era correcto (la validacion previa lo dejo pasar),
    pero en curated solo han acabado 15 de las 20 filas. Es exactamente el
    caso que la comprobacion manual busca a ojo.
    """
    rows = make_rows(20)
    state = cargado(rows)

    # Se sobreescribe la particion con un resultado incompleto.
    settings = get_settings()
    truncado = "landing/dataset=clientes/dt=2026-08-27/parcial.csv"
    storage.put_bytes(aws["bucket"], truncado, build_csv(rows[:15]), "text/csv")
    run_local_transform(
        bucket=aws["bucket"],
        source_key=truncado,
        rules=get_dataset_rules(settings.rules_path, "clientes"),
        business_date=state["business_date"],
        run_id=state["run_id"],
        warehouse=settings.local_warehouse,
    )

    with pytest.raises(VerificationFailed, match="manifest"):
        verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})


# --------------------------------------------------------------- Fase B


def test_verificacion_b_pasa_si_nadie_ha_tocado_los_datos(cargado):
    state = cargado()
    state = verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})
    result = verify_load.handler({**state, "phase": str(Phase.B_SCHEDULED)})

    assert result["passed"] is True
    assert result["drift"] == []
    assert ledger.get(state["run_id"])["status"] == "VERIFIED"


def test_verificacion_b_detecta_un_reproceso_que_pisa_la_particion(cargado):
    """Este es el caso que la comprobacion manual no ve.

    Entre la fase A y la B, otro proceso vuelve a escribir la particion y
    duplica las filas. Las reglas de conteo podrian pasar por casualidad, pero
    la comparacion de huella no.
    """
    state = cargado()
    state = verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})

    settings = get_settings()
    partition = Path(settings.local_warehouse) / "clientes" / f"dt={state['business_date']}"
    original = next(partition.glob("*.parquet"))
    shutil.copy(original, partition / "reproceso.parquet")

    with pytest.raises(DriftDetected, match="cambiaron"):
        verify_load.handler({**state, "phase": str(Phase.B_SCHEDULED)})

    assert ledger.get(state["run_id"])["status"] == "DRIFT_DETECTED"


def test_sin_huella_previa_la_fase_b_no_inventa_divergencias(cargado):
    """Si la fase A no dejo huella (ejecucion antigua), B no debe fallar por eso."""
    state = cargado()
    result = verify_load.handler({**state, "phase": str(Phase.B_SCHEDULED)})
    assert result["drift"] == []


# ---------------------------------------------------------- Nucleo puro


def test_run_verification_no_necesita_aws(cargado):
    """El nucleo de la verificacion es una funcion pura sobre un QueryEngine."""
    state = cargado()
    engine = DuckDBEngine()
    try:
        report = verify_load.run_verification(
            engine=engine,
            rules_path=get_settings().rules_path,
            run_id=state["run_id"],
            dataset="clientes",
            business_date=state["business_date"],
            expected_rows=20,
            phase=Phase.B_SCHEDULED,
            previous_fingerprint=Fingerprint(
                row_count=999, numeric_checksum=0.0, distinct_keys=999
            ),
        )
    finally:
        engine.close()

    assert report.passed is False
    assert any("row_count 999 -> 20" in d for d in report.drift)

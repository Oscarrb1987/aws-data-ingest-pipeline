"""Modelos de dominio: manifest, huella e informe."""

from __future__ import annotations

import json

import pytest

from src.common.models import (
    CheckResult,
    Fingerprint,
    Manifest,
    Phase,
    Severity,
    VerificationReport,
)


def test_manifest_se_parsea_e_ignora_campos_extra():
    raw = json.dumps(
        {
            "dataset": "clientes",
            "business_date": "2026-08-27",
            "row_count": 200,
            "sha256": "abc123",
            "campo_futuro": "no deberia romper nada",
        }
    )
    manifest = Manifest.from_json(raw)
    assert manifest.dataset == "clientes"
    assert manifest.row_count == 200
    assert manifest.delimiter == ","  # valor por defecto


@pytest.mark.parametrize("falta", ["dataset", "business_date", "row_count", "sha256"])
def test_manifest_rechaza_campos_obligatorios_ausentes(falta):
    data = {
        "dataset": "clientes",
        "business_date": "2026-08-27",
        "row_count": 10,
        "sha256": "abc",
    }
    del data[falta]
    with pytest.raises(ValueError, match="manifest incompleto"):
        Manifest.from_json(json.dumps(data))


def test_huella_identica_no_produce_diferencias():
    a = Fingerprint(row_count=200, numeric_checksum=1234.56, distinct_keys=200)
    b = Fingerprint(row_count=200, numeric_checksum=1234.56, distinct_keys=200)
    assert a.differs_from(b) == []


def test_huella_detecta_filas_de_mas():
    antes = Fingerprint(row_count=200, numeric_checksum=1000.0, distinct_keys=200)
    despues = Fingerprint(row_count=400, numeric_checksum=2000.0, distinct_keys=200)
    diffs = despues.differs_from(antes)
    assert any("row_count" in d for d in diffs)
    assert any("numeric_checksum" in d for d in diffs)


def test_huella_tolera_ruido_decimal():
    a = Fingerprint(row_count=10, numeric_checksum=100.000001, distinct_keys=10)
    b = Fingerprint(row_count=10, numeric_checksum=100.0, distinct_keys=10)
    assert a.differs_from(b) == []


def _result(passed: bool, severity: Severity = Severity.CRITICAL) -> CheckResult:
    return CheckResult(
        check_id="regla",
        passed=passed,
        severity=severity,
        observed=0 if passed else 3,
        expected=0,
        message="",
    )


def test_informe_pasa_si_solo_falla_un_warning():
    report = VerificationReport(
        run_id="r1",
        dataset="clientes",
        business_date="2026-08-27",
        phase=Phase.A_POST_LOAD,
        results=[_result(True), _result(False, Severity.WARNING)],
    )
    assert report.passed is True
    assert len(report.failed_checks) == 1


def test_informe_falla_si_falla_una_regla_critica():
    report = VerificationReport(
        run_id="r1",
        dataset="clientes",
        business_date="2026-08-27",
        phase=Phase.A_POST_LOAD,
        results=[_result(False)],
    )
    assert report.passed is False


def test_informe_falla_si_hay_divergencia_aunque_pasen_las_reglas():
    report = VerificationReport(
        run_id="r1",
        dataset="clientes",
        business_date="2026-08-27",
        phase=Phase.B_SCHEDULED,
        results=[_result(True)],
        drift=["row_count 200 -> 400"],
    )
    assert report.passed is False
    assert "Divergencia" in report.to_markdown()


def test_informe_serializa_a_dict_y_markdown():
    report = VerificationReport(
        run_id="r1",
        dataset="clientes",
        business_date="2026-08-27",
        phase=Phase.A_POST_LOAD,
        results=[_result(True)],
        fingerprint=Fingerprint(10, 1.0, 10),
    )
    data = report.to_dict()
    assert data["checks_total"] == 1
    assert data["fingerprint"]["row_count"] == 10
    assert "| `regla` | PASS" in report.to_markdown()

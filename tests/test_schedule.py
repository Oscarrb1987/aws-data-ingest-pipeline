"""Calculo del instante de la verificacion diferida."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.handlers.schedule import handler, next_occurrence


def _madrid(y, m, d, h, mi) -> datetime:
    """Instante UTC equivalente a una hora local de Madrid en verano (UTC+2)."""
    return datetime(y, m, d, h - 2, mi, tzinfo=UTC)


def test_si_la_hora_aun_no_ha_pasado_se_programa_hoy():
    ahora = _madrid(2026, 8, 27, 6, 0)
    assert next_occurrence("08:00", "Europe/Madrid", now=ahora) == _madrid(2026, 8, 27, 8, 0)


def test_si_la_hora_ya_paso_se_programa_manana():
    ahora = _madrid(2026, 8, 27, 9, 30)
    assert next_occurrence("08:00", "Europe/Madrid", now=ahora) == _madrid(2026, 8, 28, 8, 0)


def test_justo_en_la_hora_se_va_al_dia_siguiente():
    """Margen de seguridad: no se programa una espera de cero segundos."""
    ahora = _madrid(2026, 8, 27, 8, 0)
    assert next_occurrence("08:00", "Europe/Madrid", now=ahora).day == 28


def test_cambio_de_hora_de_invierno():
    """En invierno Madrid es UTC+1: las 08:00 locales son las 07:00 UTC."""
    ahora = datetime(2026, 1, 15, 5, 0, tzinfo=UTC)
    resultado = next_occurrence("08:00", "Europe/Madrid", now=ahora)
    assert (resultado.hour, resultado.day) == (7, 15)


@pytest.mark.parametrize("valor", ["ocho", "25:00:00", "", "8"])
def test_formato_invalido_da_error(valor):
    with pytest.raises(ValueError, match="VERIFY_B_SCHEDULE"):
        next_occurrence(valor, "Europe/Madrid")


def test_el_handler_devuelve_un_timestamp_iso(monkeypatch):
    monkeypatch.setenv("VERIFY_B_SCHEDULE", "08:00")
    monkeypatch.setenv("VERIFY_B_DELAY_SECONDS", "0")
    out = handler({"run_id": "r1"})
    assert out["run_id"] == "r1"
    assert out["verify_b_at"].endswith("Z")


def test_en_local_se_puede_acortar_la_espera(monkeypatch):
    monkeypatch.setenv("VERIFY_B_DELAY_SECONDS", "5")
    out = handler({})
    programado = datetime.fromisoformat(out["verify_b_at"].replace("Z", "+00:00"))
    assert 0 < (programado - datetime.now(UTC)).total_seconds() <= 6

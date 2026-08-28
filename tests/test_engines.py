"""Motores de consulta: seleccion e implementacion Athena.

Athena no se puede simular con moto de forma util, asi que se prueba contra un
doble que reproduce su protocolo: arrancar consulta, sondear estado, leer
resultados.
"""

from __future__ import annotations

import pytest

from src.common.rules import get_dataset_rules
from src.engines import get_engine
from src.engines.athena import AthenaEngine, AthenaQueryError
from src.engines.duckdb_engine import DuckDBEngine
from tests.conftest import ROOT


class FakeAthena:
    """Doble de `boto3.client('athena')` con estados encadenados."""

    def __init__(self, states: list[str], value: str | None = "42", reason: str = ""):
        self.states = list(states)
        self.value = value
        self.reason = reason
        self.queries: list[str] = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs["QueryString"])
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, **_):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {
            "QueryExecution": {
                "Status": {"State": state, "StateChangeReason": self.reason},
                "Statistics": {"DataScannedInBytes": 1024},
            }
        }

    def get_query_results(self, **_):
        return {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "value"}]},
                    {"Data": [{"VarCharValue": self.value}]},
                ]
            }
        }


@pytest.fixture
def athena(monkeypatch):
    def _build(fake: FakeAthena) -> AthenaEngine:
        monkeypatch.setattr("src.engines.athena.client", lambda _service: fake)
        return AthenaEngine(
            database="db", workgroup="wg", output_location="s3://b/r/", poll_seconds=0
        )

    return _build


def test_referencia_de_tabla_cualificada(athena):
    engine = athena(FakeAthena(["SUCCEEDED"]))
    rules = get_dataset_rules(ROOT / "rules" / "checks.yaml", "clientes")
    assert engine.table_ref(rules) == '"db"."clientes"'


def test_devuelve_el_escalar_de_la_primera_fila(athena):
    fake = FakeAthena(["SUCCEEDED"], value="7")
    engine = athena(fake)
    assert engine.scalar("SELECT COUNT(*) AS value FROM t") == "7"
    assert fake.queries == ["SELECT COUNT(*) AS value FROM t"]


def test_sondea_hasta_que_la_consulta_termina(athena):
    fake = FakeAthena(["QUEUED", "RUNNING", "SUCCEEDED"], value="3")
    assert athena(fake).scalar("SELECT 1") == "3"


def test_consulta_fallida_lanza_error_con_el_motivo(athena):
    fake = FakeAthena(["FAILED"], reason="COLUMN_NOT_FOUND")
    with pytest.raises(AthenaQueryError, match="COLUMN_NOT_FOUND"):
        athena(fake).scalar("SELECT malo FROM t")


def test_timeout_de_consulta(athena, monkeypatch):
    monkeypatch.setattr("src.engines.athena.client", lambda _s: FakeAthena(["RUNNING"]))
    engine = AthenaEngine(database="db", workgroup="wg", poll_seconds=0, timeout_seconds=0)
    with pytest.raises(AthenaQueryError, match="timeout"):
        engine.scalar("SELECT 1")


def test_resultado_vacio_devuelve_none(athena, monkeypatch):
    fake = FakeAthena(["SUCCEEDED"])
    monkeypatch.setattr("src.engines.athena.client", lambda _s: fake)
    fake.get_query_results = lambda **_: {"ResultSet": {"Rows": [{"Data": []}]}}
    engine = AthenaEngine(database="db", workgroup="wg", poll_seconds=0)
    assert engine.scalar("SELECT 1") is None


def test_la_fabrica_respeta_la_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("QUERY_ENGINE", "duckdb")
    from src.common.config import reset_settings_cache

    reset_settings_cache()
    assert isinstance(get_engine(), DuckDBEngine)
    assert isinstance(get_engine("athena"), AthenaEngine)


def test_motor_desconocido_da_error_claro():
    with pytest.raises(ValueError, match="motor de consulta desconocido"):
        get_engine("postgres")

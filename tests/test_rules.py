"""Motor de reglas: compilacion a SQL y evaluacion."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.common.models import Severity
from src.common.rules import RulesError, get_dataset_rules, load_rules

RULES = Path(__file__).resolve().parent.parent / "rules" / "checks.yaml"


def test_se_cargan_los_datasets_del_contrato():
    rules = load_rules(RULES)
    assert "clientes" in rules
    assert rules["clientes"].primary_key == ["cliente_id"]
    assert "email" in rules["clientes"].required_columns
    assert "segmento" not in rules["clientes"].required_columns


def test_dataset_inexistente_da_error_claro():
    with pytest.raises(RulesError, match="no definido"):
        get_dataset_rules(RULES, "no_existe")


def test_compilacion_genera_una_asercion_por_columna_obligatoria():
    rules = get_dataset_rules(RULES, "clientes")
    assertions = rules.compile('"db"."clientes"', "2026-08-27", 200)
    ids = [a.check_id for a in assertions]

    # `not_null` con cinco columnas produce cinco comprobaciones independientes
    assert ids.count("sin_nulos_obligatorios__email") == 1
    assert len([i for i in ids if i.startswith("sin_nulos_obligatorios__")]) == 5
    assert "clave_primaria_unica" in ids


def test_todas_las_sentencias_filtran_por_particion():
    rules = get_dataset_rules(RULES, "clientes")
    for assertion in rules.compile('"db"."clientes"', "2026-08-27", 200):
        assert "\"dt\" = '2026-08-27'" in assertion.sql


def test_row_count_compara_contra_el_manifest():
    rules = get_dataset_rules(RULES, "clientes")
    check = next(
        a for a in rules.compile('"t"', "2026-08-27", 200) if a.check_id == "filas_vs_manifest"
    )
    assert check.comparator == "equals"
    assert check.expected == 200
    assert check.evaluate(200).passed
    assert not check.evaluate(198).passed


def test_reglas_de_violaciones_esperan_cero():
    rules = get_dataset_rules(RULES, "clientes")
    check = next(
        a for a in rules.compile('"t"', "2026-08-27", 200) if a.check_id == "clave_primaria_unica"
    )
    assert check.evaluate(0).passed
    assert not check.evaluate(3).passed
    assert check.evaluate(3).blocking is True


def test_un_warning_que_falla_no_bloquea():
    rules = get_dataset_rules(RULES, "clientes")
    check = next(
        a for a in rules.compile('"t"', "2026-08-27", 200) if a.check_id == "email_con_arroba"
    )
    assert check.severity is Severity.WARNING
    assert check.evaluate(5).blocking is False


def test_columna_con_nombre_peligroso_se_rechaza(tmp_path):
    """El nombre de columna acaba en el SQL: no puede colarse cualquier cosa."""
    contrato = {
        "datasets": {
            "malo": {
                "schema": [{"name": "id; DROP TABLE x", "type": "string", "required": True}],
                "checks": [{"id": "nulos", "type": "not_null", "columns": ["id; DROP TABLE x"]}],
            }
        }
    }
    path = tmp_path / "checks.yaml"
    path.write_text(yaml.safe_dump(contrato), encoding="utf-8")

    rules = get_dataset_rules(path, "malo")
    with pytest.raises(RulesError, match="no valido"):
        rules.compile('"t"', "2026-08-27", 1)


def test_tipo_de_regla_desconocido_se_rechaza(tmp_path):
    contrato = {
        "datasets": {
            "x": {
                "schema": [{"name": "id", "type": "string"}],
                "checks": [{"id": "raro", "type": "telepatia"}],
            }
        }
    }
    path = tmp_path / "checks.yaml"
    path.write_text(yaml.safe_dump(contrato), encoding="utf-8")
    with pytest.raises(RulesError, match="no soportado"):
        get_dataset_rules(path, "x").compile('"t"', "2026-08-27", 1)


def test_esquema_vacio_se_rechaza(tmp_path):
    path = tmp_path / "checks.yaml"
    path.write_text(yaml.safe_dump({"datasets": {"x": {"schema": []}}}), encoding="utf-8")
    with pytest.raises(RulesError, match="esquema no puede estar vacio"):
        load_rules(path)

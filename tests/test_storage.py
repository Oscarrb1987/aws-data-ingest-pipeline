"""Utilidades de S3: checksum y conteo en streaming."""

from __future__ import annotations

import hashlib

from src.common import storage
from tests.conftest import BUCKET


def test_checksum_en_streaming_coincide_con_hashlib(aws):
    payload = b"a,b,c\n" + b"1,2,3\n" * 5000
    storage.put_bytes(BUCKET, "x.csv", payload, "text/csv")
    assert storage.sha256_of_object(BUCKET, "x.csv") == hashlib.sha256(payload).hexdigest()


def test_conteo_de_filas_ignora_la_cabecera(aws):
    storage.put_bytes(BUCKET, "x.csv", b"a,b\n1,2\n3,4\n5,6\n", "text/csv")
    assert storage.count_data_lines(BUCKET, "x.csv") == 3


def test_conteo_con_ultima_linea_sin_salto(aws):
    storage.put_bytes(BUCKET, "x.csv", b"a,b\n1,2\n3,4", "text/csv")
    assert storage.count_data_lines(BUCKET, "x.csv") == 2


def test_fichero_solo_con_cabecera_cuenta_cero(aws):
    storage.put_bytes(BUCKET, "x.csv", b"a,b\n", "text/csv")
    assert storage.count_data_lines(BUCKET, "x.csv") == 0


def test_cabecera_se_lee_en_minusculas_y_sin_bom(aws):
    storage.put_bytes(BUCKET, "x.csv", "﻿ID,Nombre\n1,a\n".encode(), "text/csv")
    assert storage.read_header(BUCKET, "x.csv") == ["id", "nombre"]


def test_mover_a_cuarentena_borra_el_origen(aws):
    storage.put_bytes(BUCKET, "landing/x.csv", b"datos", "text/csv")
    storage.move(BUCKET, "landing/x.csv", "quarantine/x.csv")

    assert storage.exists(BUCKET, "quarantine/x.csv")
    assert not storage.exists(BUCKET, "landing/x.csv")


def test_listado_por_prefijo(aws):
    for i in range(3):
        storage.put_bytes(BUCKET, f"reports/r{i}.json", b"{}", "application/json")
    assert len(storage.list_keys(BUCKET, "reports/")) == 3

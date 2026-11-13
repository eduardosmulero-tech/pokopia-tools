"""`tools/rdb_names.py`: estructura del `root.rdb` y las cuentas de la tarjeta.

Primero con bytes sinteticos (siempre corren), y despues contra el dump real cuando
esta configurado (`PKP_ROMFS`). En el dump se comprueba lo que decide el informe:
que la cola de 13 B de las entradas `name` es la **direccion del dato** y no una
cadena, y que el cruce objdb -> `.g1s` da 108.909 referencias resueltas.
"""

from __future__ import annotations

import os
import struct

import pytest

from pokopia import paths
from tools import rdb_names

# ---------------------------------------------------------------------------
# Bytes sinteticos
# ---------------------------------------------------------------------------

MAGIA = b"_DRK0000"
CABECERA = 0x20


def _entrada(name_hash: int, tkid: int, cuerpo: bytes, entry_size: int | None = None) -> bytes:
    """Entrada IDRK completa: 48 B de cabecera + cuerpo (extras + cola de 13 B)."""
    tam = entry_size if entry_size is not None else 0x30 + len(cuerpo)
    buf = bytearray(tam)
    buf[:8] = b"IDRK0000"
    struct.pack_into("<3Q", buf, 8, tam, 0x0D, 1024)
    struct.pack_into("<4I", buf, 32, 1, name_hash, tkid, 0x400000)
    buf[0x30:0x30 + len(cuerpo)] = cuerpo
    return bytes(buf)


def _cola(fdata_offset: int, entry_off: int, index: int) -> bytes:
    """Los 13 B utiles de la cola: `0x401 | fdata_offset | entry_off | index | 0`."""
    return struct.pack("<HIIHB", 0x401, fdata_offset, entry_off, index, 0)


def _rdb(entradas: list[bytes], declaradas: int | None = None) -> bytes:
    buf = bytearray(CABECERA)
    buf[:8] = MAGIA
    struct.pack_into("<I", buf, 8, CABECERA)
    struct.pack_into("<I", buf, 16, len(entradas) if declaradas is None else declaradas)
    partes = [bytes(buf)]
    for e in entradas:
        partes.append(e)
        resto = len(e) % rdb_names.RDB_ALIGN
        if resto:
            partes.append(b"\x00" * (rdb_names.RDB_ALIGN - resto))
    return b"".join(partes)


def _escribir(tmp_path, datos: bytes) -> str:
    ruta = tmp_path / "root.rdb"
    ruta.write_bytes(datos)
    return str(ruta)


def test_iter_entries_lee_cabecera_y_cola(tmp_path):
    cuerpo = b"\x00" * 8 + _cola(0x1094C80, 247, 13)
    ruta = _escribir(tmp_path, _rdb([_entrada(0x8B081C30, 0x20A6A0BB, cuerpo)]))

    entradas = list(rdb_names.iter_entries(ruta))
    assert len(entradas) == 1
    e = entradas[0]
    assert e.offset == CABECERA
    assert e.entry_size == 0x30 + len(cuerpo)
    assert e.constante == 0x0D
    assert e.file_size == 1024
    assert e.name_hash == 0x8B081C30
    assert e.tkid == 0x20A6A0BB
    assert e.tipo == "kidsobjdb"
    assert e.magia_cola == 0x401
    assert e.fdata_offset == 0x1094C80
    assert e.entry_off == 247
    assert e.fdata_index == 13
    assert e.cola == cuerpo[-13:]


def test_entrada_name_tiene_entry_size_69(tmp_path):
    cuerpo = b"\x00" * 8 + _cola(0x880A04, 0xD700, 11)
    ruta = _escribir(tmp_path, _rdb([_entrada(0xAE19, rdb_names.NAME_KTID, cuerpo)]))
    e = list(rdb_names.iter_entries(ruta))[0]
    assert e.entry_size == 69
    assert len(e.cola) == 13
    assert e.tipo == "name"


def test_alineacion_a_cuatro_no_a_dieci_sais(tmp_path):
    """Dos entradas de 69 B dejan 3 B de relleno: la segunda empieza en 0x20+72."""
    una = b"\x00" * 8 + _cola(1, 2, 3)
    ruta = _escribir(tmp_path, _rdb([
        _entrada(0x11, rdb_names.NAME_KTID, una),
        _entrada(0x22, rdb_names.NAME_KTID, una),
    ]))
    entradas = list(rdb_names.iter_entries(ruta))
    assert [e.offset for e in entradas] == [CABECERA, CABECERA + 72]


def test_firma_de_cabecera(tmp_path):
    ruta = _escribir(tmp_path, b"PDRK0000" + b"\x00" * 64)
    with pytest.raises(rdb_names.RdbError, match="_DRK0000"):
        list(rdb_names.iter_entries(ruta))


def test_firma_de_entrada(tmp_path):
    datos = bytearray(_rdb([_entrada(1, rdb_names.NAME_KTID, b"\x00" * 21)]))
    datos[CABECERA:CABECERA + 8] = b"XXXX0000"
    ruta = _escribir(tmp_path, bytes(datos))
    with pytest.raises(rdb_names.RdbError, match="IDRK0000"):
        list(rdb_names.iter_entries(ruta))


def test_cuenta_declarada_no_cuadra(tmp_path):
    ruta = _escribir(tmp_path, _rdb(
        [_entrada(1, rdb_names.NAME_KTID, b"\x00" * 21)], declaradas=2))
    with pytest.raises(rdb_names.RdbError, match="declara 2"):
        list(rdb_names.iter_entries(ruta))


def test_entry_size_imposible(tmp_path):
    mala = _entrada(1, rdb_names.NAME_KTID, b"\x00" * 21)
    datos = bytearray(_rdb([mala]))
    struct.pack_into("<Q", datos, CABECERA + 8, 0x30)  # sin sitio para la cola
    ruta = _escribir(tmp_path, bytes(datos))
    with pytest.raises(rdb_names.RdbError, match="entry_size"):
        list(rdb_names.iter_entries(ruta))


def test_puntuacion_texto_es_la_fraccion_imprimible():
    assert rdb_names._puntuacion_texto(["abc"]) == 1.0
    assert rdb_names._puntuacion_texto(["\x00\x00"]) == 0.0
    assert rdb_names._puntuacion_texto(["ab\x00\x00"]) == 0.5


def test_hipotesis_devuelve_las_cinco_del_encargo():
    candidatos = [bytes(range(13)), bytes(range(3, 16)), b"\xff" * 13]
    salida = rdb_names.hipotesis(candidatos)
    assert [r["nombre"].split()[0] for r in salida] == ["H1", "H2", "H3", "H4", "H5"]
    for r in salida:
        assert len(r["texto"]) == len(candidatos)
        assert 0.0 <= r["puntuacion"] <= 1.0


# ---------------------------------------------------------------------------
# El dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
RDB = os.path.join(ROMFS, "motor_asset_re", "KIDS_PLATFORM_OUNCE", "root.rdb")
HAY_DUMP = os.path.isfile(RDB)
necesita_dump = pytest.mark.skipif(
    not HAY_DUMP, reason="sin root.rdb en el dump (exporta PKP_ROMFS)")


@necesita_dump
def test_censo_del_dump_real(capsys):
    assert rdb_names.main(["--rdb", RDB, "censo"]) == 0
    salida = capsys.readouterr().out
    assert "entradas           60722" in salida
    assert "cola 0x401         60717 de 60722 entradas" in salida
    assert "0xbf6b52c7 name           4485" in salida
    # el contrato con el bundle: la cola es la direccion, y apunta donde dice
    assert "coinciden en name_hash+entry_size+tkid+file_size: 54651 (100.00 %)" in salida
    assert "entry_size: {69: 4485}" in salida


@necesita_dump
def test_las_name_apuntan_a_bundles_que_no_estan(capsys):
    """El hallazgo que cierra el encargo en negativo, comprobado en la suite."""
    assert rdb_names.main(["--rdb", RDB, "censo"]) == 0
    salida = capsys.readouterr().out
    assert "entradas `name` cuyo bundle esta en el volcado: 0 de 4485" in salida


@necesita_dump
def test_cruce_objdb_g1s(capsys):
    assert rdb_names.main(["--rdb", RDB, "cruce"]) == 0
    salida = capsys.readouterr().out
    assert "  ... con la referencia resuelta        108909 (36.93 %)" in salida
    assert "tipos de fichero referenciados: [('g1s', 108909)]" in salida
    assert "control de azar: 75807 valores aleatorios, 1 coincidencias" in salida


@necesita_dump
def test_resolver_por_hash_y_por_nombre(capsys):
    assert rdb_names.main(["--rdb", RDB, "resolver", "0x36fd31f9"]) == 0
    salida = capsys.readouterr().out
    assert "hash 0x36fd31f9 = 0x36fd31f9" in salida
    assert "tipo=g1t" in salida

    assert rdb_names.main(["--rdb", RDB, "resolver", "MO_Versatile.kidssingletondb"]) == 0
    salida = capsys.readouterr().out
    assert "kt_hash('MO_Versatile.kidssingletondb') = 0x8b081c30" in salida
    assert "tipo=kidsobjdb" in salida
    assert "0x2943e4da.fdata" in salida

    assert rdb_names.main(["--rdb", RDB, "resolver", "no-existe-xyz-0000"]) == 1
    assert "no esta en el indice" in capsys.readouterr().out


@necesita_dump
def test_identificadores_en_claro_del_objdb(capsys):
    assert rdb_names.main(["--rdb", RDB, "identificadores"]) == 0
    salida = capsys.readouterr().out
    assert "identificadores distintos: 13426" in salida
    assert "nombres del catalogo identicos a un identificador: 2042" in salida

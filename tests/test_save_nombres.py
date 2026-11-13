"""Nombres de objeto desde el save: cadena `id -> #983 -> nameIndex -> #4650`.

Todo lo que se prueba aqui es un **marcador**: `MARCADOR-...`. Ni un nombre del juego
en el codigo ni en el fixture (docs/NORMA-CONTENIDO-Y-PUBLICACION.md §1). El fixture es
sintetico: dos tablas declaradas con `helpers.temp_spec` (8 filas de 68 B y 30 slots) y
un save con los huecos del mismo tamaño que el real (`save_fixture`).

Casos que fija la tarjeta:

- el nombre es el **slot +0** del bloque de seis (`SINGULAR_SLOT`), no el plural `+2`;
- `r = nameIndex + 3`, no `nameIndex` (off-by-three silencioso);
- id sin fila en `#983`, `nameIndex` fuera del pool, bloque vacio o pool truncado ->
  `<sin nombre>`, **sin excepcion**;
- el pool se trocea **una vez** por ejecucion y cada fila se lee una sola vez;
- con `--nombres` la salida es la de siempre *mas* la columna, y sin la bandera no
  cambia ni un byte (C1);
- `save write --dry-run --nombres` dice hueco y objeto antes de tocar nada (C5).

Los dos vectores de `docs/SPEC-NAMES.md` §12.1 (digests de sha256) se comprueban contra
el dump cuando esta configurado: es la unica forma de contrastar esta lectura con un
lector independiente sin copiar texto del juego.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import save_fixture as fx  # noqa: E402
from pokopia import nombres as N  # noqa: E402
from pokopia import paths, tables  # noqa: E402
from pokopia.cli import main as cli_main  # noqa: E402

from tests import helpers  # noqa: E402

ITEM_TABLE = 983
NAME_TABLE_ES = 4650
NAME_TABLE_EN = 4646
ROWS = 8
TEXT_COUNT = 10          # ids de texto 4..13 -> 10 bloques de 6 = 60 slots necesarios
SLOTS = 30               # solo 5 bloques completos: el resto queda truncado

#: Un slot 0 del bloque de `r=4`; `r=5` esta vacio en los seis; `r=6` tiene el +1 lleno
#: (la trampa del slot equivocado); `r=7` es un bloque de un solo slot como el japones.
MARCADORES = [
    b"MARCADOR-SINGULAR", b"", b"MARCADOR-PLURAL", b"MARCADOR-OTRO-GRUPO", b"", b"",
    b"", b"", b"", b"", b"", b"",
    b"", b"MARCADOR-SLOT-UNO", b"MARCADOR-PLURAL-SOLO", b"", b"", b"",
    b"MARCADOR-SIETE", b"", b"", b"", b"", b"",
    b"MARCADOR-OCHO", b"", b"", b"", b"", b"",
]

#: `id de inventario -> nameIndex` escrito en el +34 de la fila de `#983`.
FILAS = {
    1: 1,        # r = 4  -> MARCADOR-SINGULAR
    2: 2,        # r = 5  -> bloque vacio en las nueve lenguas
    3: 3,        # r = 6  -> el +0 vacio y el +1 lleno: no es el nombre
    4: 5000,     # r = 5003 -> fuera del pool
    5: 0,        # r = 3  -> los ids 0..3 no tienen bloque
    6: 9,        # r = 12 -> k = 48, mas alla de los 30 slots (pool truncado)
    7: 4,        # r = 7  -> MARCADOR-SIETE (con r = nameIndex leeria el bloque de 4)
}

SIN_NOMBRE = N.SIN_NOMBRE


# ---------------------------------------------------------------------------
# Fixture sintetico
# ---------------------------------------------------------------------------

def _items_payload(rows: dict[int, int] | None = None, count: int = ROWS) -> bytes:
    """Payload de `#983`: 8 filas de 68 B con el `u16` del +34."""
    filas = {}
    for row, name_index in (rows or FILAS).items():
        fila = bytearray(68)
        struct.pack_into("<H", fila, N.NAME_INDEX_OFFSET, name_index)
        filas[row] = bytes(fila)
    return helpers.records_payload(filas, count=count, stride=68, version=3)


def _text_payload(slots: list[bytes] | None = None) -> bytes:
    return helpers.text_payload(list(slots if slots is not None else MARCADORES),
                                count=TEXT_COUNT)


@pytest.fixture()
def indice():
    """`NameIndex` sobre las dos tablas sinteticas (sin contenedor ni dump)."""
    with helpers.records_spec(index=ITEM_TABLE, count=ROWS, stride=68, version=3), \
            helpers.text_spec(index=NAME_TABLE_ES, count=TEXT_COUNT):
        yield N.NameIndex(_items_payload(), _text_payload())


@pytest.fixture()
def entorno(tmp_path):
    """Contenedor sintetico (983 + 4650) y save sintetico, ambos en `tmp_path`."""
    with helpers.records_spec(index=ITEM_TABLE, count=ROWS, stride=68, version=3), \
            helpers.text_spec(index=NAME_TABLE_ES, count=TEXT_COUNT):
        raiz = str(tmp_path / "romfs")
        helpers.make_container(raiz, {ITEM_TABLE: _items_payload(),
                                      NAME_TABLE_ES: _text_payload()})
        items = {0: (1, 5), 1: (2, 3), 2: (3, 1), 3: (4, 1),
                 4: (5, 1), 5: (6, 1), 6: (7, 1), 7: (99, 1)}
        fx.make_save(str(tmp_path / "save"), payload=fx.make_payload(items=items))
        yield {"romfs": raiz, "save": str(tmp_path / "save")}


# ---------------------------------------------------------------------------
# Resolucion
# ---------------------------------------------------------------------------

def test_resuelve_el_singular(indice):
    assert indice.text_id(1) == 4
    assert indice.resolver(1) == "MARCADOR-SINGULAR"
    assert indice.nombre(1) == "MARCADOR-SINGULAR"


def test_regla_mas_tres_no_off_by_three(indice):
    """Fila 7 guarda 4: el nombre esta en el bloque de `r=7`, no en el de `r=4`."""
    assert indice.text_id(7) == 7
    assert indice.nombre(7) == "MARCADOR-SIETE"


def test_bloque_vacio_es_sin_nombre(indice):
    assert indice.text_id(2) == 5
    assert indice.nombre(2) == SIN_NOMBRE
    assert indice.resolver(2) is None


def test_no_se_lee_el_plural_ni_el_slot_uno(indice):
    """El nombre es el +0: con el +0 vacio no se cae al +1 ni al +2."""
    assert indice.nombre(3) == SIN_NOMBRE


def test_name_index_fuera_del_pool(indice):
    assert indice.text_id(4) is None
    assert indice.nombre(4) == SIN_NOMBRE


def test_id_sin_fila(indice):
    assert indice.nombre(99) == SIN_NOMBRE          # id >= filas de #983
    assert indice.nombre(-1) == SIN_NOMBRE
    assert indice.nombre(0) == SIN_NOMBRE           # nameIndex 0 -> r = 3


def test_pool_truncado_sin_excepcion(indice):
    """`k` cae mas alla del ultimo slot: `<sin nombre>`, no IndexError."""
    assert indice.nombre(6) == SIN_NOMBRE


def test_un_id_raro_no_rompe_una_lista(indice):
    """Recorrer los 130 huecos con ids fuera de rango no lanza nada."""
    salida = [indice.nombre(item) for item in [0, 1, 2, 3, 4, 5, 6, 7, 8, 4600, 4601,
                                               8191]]
    assert salida.count(SIN_NOMBRE) == 10
    assert "MARCADOR-SINGULAR" in salida


def test_pool_una_sola_vez_y_cada_fila_una_vez(indice, monkeypatch):
    """Una lectura del contenedor y una fila por id: nada de 6 lecturas por hueco."""
    parseos = {"n": 0}
    lecturas = {"n": 0}
    parse_pool = tables.parse_pool
    read_row = tables.read_row

    def contar_parse(spec, blob):
        parseos["n"] += 1
        return parse_pool(spec, blob)

    def contar_row(spec, blob, row):
        lecturas["n"] += 1
        return read_row(spec, blob, row)

    monkeypatch.setattr(tables, "parse_pool", contar_parse)
    monkeypatch.setattr(tables, "read_row", contar_row)
    with helpers.records_spec(index=ITEM_TABLE, count=ROWS, stride=68, version=3), \
            helpers.text_spec(index=NAME_TABLE_ES, count=TEXT_COUNT):
        indice = N.NameIndex(_items_payload(), _text_payload())
    assert parseos["n"] == 1
    for item in FILAS:
        indice.nombre(item)
        indice.nombre(item)          # repetido: no vuelve a leer
    assert lecturas["n"] == len(FILAS)


def test_idioma_elige_la_tabla_de_nombres():
    """`--idioma en` lee `#4646`; la cadena es la misma, cambia la tabla."""
    with helpers.records_spec(index=ITEM_TABLE, count=ROWS, stride=68, version=3), \
            helpers.text_spec(index=NAME_TABLE_EN, count=TEXT_COUNT):
        ingles = [b"MARCADOR-EN-SINGULAR", b"", b"MARCADOR-EN-PLURAL", b"", b"", b"",
                  b"", b"", b"", b"", b"", b"",
                  b"", b"", b"MARCADOR-EN-PLURAL-SOLO", b"", b"", b"",
                  b"MARCADOR-EN-SIETE", b"", b"", b"", b"", b"",
                  b"MARCADOR-EN-OCHO", b"", b"", b"", b"", b""]
        payload = helpers.text_payload(ingles, count=TEXT_COUNT)
        indice = N.NameIndex(_items_payload(), payload, text_table=NAME_TABLE_EN)
    assert indice.text_spec.index == NAME_TABLE_EN
    assert indice.nombre(1) == "MARCADOR-EN-SINGULAR"
    assert indice.nombre(3) == SIN_NOMBRE      # el +2 lleno no es el nombre
    assert indice.nombre(7) == "MARCADOR-EN-SIETE"


def test_idioma_desconocido_falla(tmp_path):
    with pytest.raises(tables.TableError):
        N.NameIndex.desde_contenedor(str(tmp_path), language="tlh")


def test_contenedor_inexistente_es_un_error_de_uso(tmp_path, capsys):
    """Sin contenedor no hay nombres: exit 2 y el mensaje dice como apuntarlo."""
    fx.make_save(str(tmp_path / "save"))
    codigo = cli_main(["save", "read", "--save", str(tmp_path / "save"),
                       "--container", str(tmp_path / "sin-romfs"), "--nombres"])
    assert codigo == 2
    error = capsys.readouterr().err
    assert "--container" in error and "PKP_ROMFS" in error


# ---------------------------------------------------------------------------
# CLI: la columna
# ---------------------------------------------------------------------------

def test_cli_sin_bandera_no_cambia_ni_un_byte(entorno, capsys):
    """C1: el formato de siempre, sin columna y sin `<sin nombre>`."""
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"]]) == 0
    salida = capsys.readouterr().out
    filas = [l for l in salida.splitlines() if l.startswith("  hueco")]
    assert len(filas) == 8
    assert all(re.fullmatch(r"  hueco +\d+  id +\d+  cant +\d+", l) for l in filas)
    assert SIN_NOMBRE not in salida
    assert "MARCADOR" not in salida


def test_cli_con_nombres_añade_la_columna(entorno, capsys):
    """C2: una fila por hueco, el nombre detras y `<sin nombre>` donde no hay."""
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--nombres"]) == 0
    salida = capsys.readouterr().out
    filas = [l for l in salida.splitlines() if l.startswith("  hueco")]
    assert len(filas) == 8
    assert filas[0].endswith("  MARCADOR-SINGULAR")
    assert filas[6].endswith("  MARCADOR-SIETE")
    assert filas[7].endswith("  " + SIN_NOMBRE)      # id 99, sin fila en #983
    assert sum(1 for l in filas if l.endswith(SIN_NOMBRE)) == 6


def test_cli_con_nombres_es_la_de_siempre_mas_la_columna(entorno, capsys):
    """C1 sin bandera + C2 con bandera: cada fila es la vieja mas `  nombre`."""
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--all"]) == 0
    sin = [l for l in capsys.readouterr().out.splitlines() if l.startswith("  hueco")]
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--all", "--nombres"]) == 0
    con = [l for l in capsys.readouterr().out.splitlines() if l.startswith("  hueco")]
    assert len(sin) == len(con) == 130
    for vieja, nueva in zip(sin, con):
        assert nueva.startswith(vieja + "  "), (vieja, nueva)


def test_cli_json_con_nombres(entorno, capsys):
    import json
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--nombres", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["items"][0]["nombre"] == "MARCADOR-SINGULAR"
    assert doc["items"][7]["nombre"] == SIN_NOMBRE
    assert cli_main(["save", "read", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert "nombre" not in doc["items"][0]


def test_idioma_sin_nombres_es_error_de_uso(entorno, capsys):
    codigo = cli_main(["save", "read", "--save", entorno["save"],
                       "--container", entorno["romfs"], "--idioma", "en"])
    assert codigo == 2
    assert "--nombres" in capsys.readouterr().err


def test_un_nombre_no_imprimible_no_tumba_la_lista(tmp_path, monkeypatch):
    """Consola cp1252 (Windows) con un nombre UTF-8: sale escapado, no UnicodeEncodeError.

    Es el caso real de `--idioma jp|kr|zh-*` con la salida redirigida a un fichero en un
    Windows que no usa UTF-8 para los flujos. Antes de `backslashreplace` la lista se
    cortaba a la sexta fila con una traza.
    """
    import io

    marcador = "MARCADOR-\u3042".encode("utf-8")
    slots = [marcador] + [b""] * (SLOTS - 1)
    with helpers.records_spec(index=ITEM_TABLE, count=ROWS, stride=68, version=3), \
            helpers.text_spec(index=NAME_TABLE_ES, count=TEXT_COUNT):
        raiz = str(tmp_path / "romfs")
        helpers.make_container(raiz, {ITEM_TABLE: _items_payload({1: 1}),
                                      NAME_TABLE_ES: _text_payload(slots)})
        fx.make_save(str(tmp_path / "save"),
                     payload=fx.make_payload(items={0: (1, 2)}))
        buffer = io.BytesIO()
        flujo = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", newline="")
        monkeypatch.setattr(sys, "stdout", flujo)
        assert cli_main(["save", "read", "--save", str(tmp_path / "save"),
                         "--container", raiz, "--nombres"]) == 0
        flujo.flush()
        escrito = buffer.getvalue().decode("cp1252")
    assert "\\u3042" in escrito
    assert sum(1 for l in escrito.splitlines() if l.startswith("  hueco")) == 1


# ---------------------------------------------------------------------------
# CLI: escribir con el nombre delante (C5)
# ---------------------------------------------------------------------------

def test_write_dry_run_dice_hueco_y_objeto(entorno, capsys):
    assert cli_main(["save", "write", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--slot", "0",
                     "--count", "9", "--dry-run", "--nombres"]) == 0
    salida = capsys.readouterr().out
    assert "cambio    : hueco 0   id 1 -> 1   cant 5 -> 9" in salida
    assert "objeto    : MARCADOR-SINGULAR" in salida
    assert "[dry-run]" in salida


def test_write_dry_run_ensena_el_cambio_de_objeto(entorno, capsys):
    assert cli_main(["save", "write", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--slot", "1",
                     "--id", "7", "--dry-run", "--nombres"]) == 0
    salida = capsys.readouterr().out
    assert "cambio    : hueco 1   id 2 -> 7" in salida
    assert "objeto    : %s -> MARCADOR-SIETE" % SIN_NOMBRE in salida


def test_write_sin_bandera_no_imprime_el_cambio(entorno, capsys):
    assert cli_main(["save", "write", "--save", entorno["save"],
                     "--container", entorno["romfs"], "--slot", "0",
                     "--count", "9", "--dry-run"]) == 0
    salida = capsys.readouterr().out
    assert "cambio" not in salida and "objeto" not in salida
    assert "MARCADOR" not in salida


# ---------------------------------------------------------------------------
# Contra el dump: los vectores publicados de la spec (sin texto del juego)
# ---------------------------------------------------------------------------

HAY_DUMP = os.path.isfile(os.path.join(paths.configured_romfs(), paths.IDX_NAME))
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego")

#: docs/SPEC-NAMES.md §12.1: sha256 del **slot +0** de `r=4` y de `r=3000` en `es`/`en`.
VECTORES = {
    ("es", 4001): ("9ca4c5493c7f23cea6663ddeb154f27ae2388d04596d556a6d917780cf543765", 4),
    ("en", 4001): ("132d0ebd4c51640ef3ad2a84b384e7af90125bf7d834c53b4d31a89a1dfa5570", 4),
    ("es", 2157): ("cfbd5b41541564558c5986a82dcbcaa6dd7ced9bed72c08bb1e1c234777be532", 3000),
}


@necesita_dump
@pytest.mark.parametrize("clave", sorted(VECTORES))
def test_vectores_de_la_spec(clave):
    """El nombre resuelto coincide byte a byte con el vector independiente de la spec."""
    idioma, item_id = clave
    esperado, r = VECTORES[clave]
    indice = N.NameIndex.desde_contenedor(None, language=idioma)
    assert indice.text_id(item_id) == r
    nombre = indice.nombre(item_id)
    assert nombre != SIN_NOMBRE
    assert hashlib.sha256(nombre.encode("utf-8")).hexdigest() == esperado


@necesita_dump
def test_recorrer_las_4600_filas_no_falla():
    """Un indice por ejecucion: 4.600 filas resueltas en memoria, sin excepciones."""
    indice = N.NameIndex.desde_contenedor(None, language="es")
    assert indice.text_spec.index == NAME_TABLE_ES
    assert len(indice.slots) > 17_000
    resueltos = [indice.nombre(item) for item in range(indice.items_spec.count + 1)]
    assert len(resueltos) == indice.items_spec.count + 1
    assert resueltos.count(SIN_NOMBRE) > 0
    assert any(nombre != SIN_NOMBRE for nombre in resueltos)
    assert indice.nombre(indice.items_spec.count) == SIN_NOMBRE   # id sin fila

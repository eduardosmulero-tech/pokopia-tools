"""Contenedor derivado: `count` por encima del declarado y la bandera `--modificado`.

La regla del kit es que un `count` distinto del declarado **falle** (un dump de otra
version no se lee), y sigue siendo el defecto. La tarjeta t_8032f11a abre una
excepcion explicita y acotada para contenedores derivados —los que anaden filas al
dump— con la bandera `--modificado`. Aqui se fija que:

- sin bandera, la deriva del `count` sigue lanzando `TableError` con su mensaje;
- con `--modificado`, `check_header` devuelve el `count` real y `con_conteo` deriva
  la geometria (records_end y pool_start) segun SPEC-NAMES §11.2;
- el `version` no admite deriva **en ninguno** de los dos modos;
- `NameIndex(modificado=True)` resuelve la fila anadida: 8 -> nameIndex 7 ->
  r 10 -> slot 36 -> texto;
- la CLI sin bandera sale con 1, y con la bandera lee la fila nueva, su bloque de
  texto (`--texto`) y `save read --nombres` sobre el contenedor derivado.

Todo el texto de este fichero es marcador (`NUEVO-MARCADOR-4601`), no contenido del
juego (docs/NORMA-CONTENIDO-Y-PUBLICACION.md §1).
"""
from __future__ import annotations

import json
import os
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
from pokopia import tables  # noqa: E402
from pokopia.cli import main as cli_main  # noqa: E402

from tests import helpers  # noqa: E402

ITEM_TABLE = 983
TEXT_TABLE = 4650
FILAS = 8            # count declarado de #983 en el fixture
FILA_NUEVA = 8       # la fila que solo existe en el contenedor derivado (count 9)
NAME_INDEX_NUEVO = 7  # r = 7 + 3 = 10
TEXT_COUNT = 10       # count declarado de #4650 (ids 4..13)
TEXT_COUNT_NUEVO = 11
SLOT_NUEVO = 6 * (10 - tables.TEXT_FIRST_ID)   # bloque de r=10 -> slot 36
MARCADOR = "NUEVO-MARCADOR-4601"
EXISTENTE = "MARCADOR-CUATRO"                  # id de texto 4 (bloque de siempre)


# ---------------------------------------------------------------------------
# Fixtures sinteticos (un contenedor sin anadir filas y otro derivado)
# ---------------------------------------------------------------------------

def _spec_items():
    """`#983` declarado como el registro real: 8 filas, version 3, nameIndex en +34."""
    return helpers.temp_spec(
        index=ITEM_TABLE, kind="records", header=64, stride=68, count=FILAS,
        version=3, confidence="verified", source="tests",
        fields=(tables.FieldSpec(N.NAME_INDEX_OFFSET, "u16", "nameIndex",
                                 confidence="verified"),))


def _filas(con_nueva: bool) -> dict[int, bytes]:
    filas = {0: _fila_name_index(1)}          # nameIndex 1 -> r=4
    if con_nueva:
        filas[FILA_NUEVA] = _fila_name_index(NAME_INDEX_NUEVO)
    return filas


def _fila_name_index(name_index: int) -> bytes:
    fila = bytearray(68)
    struct.pack_into("<H", fila, N.NAME_INDEX_OFFSET, name_index)
    return bytes(fila)


def _items(con_nueva: bool, version: int = 3) -> bytes:
    count = FILAS + 1 if con_nueva else FILAS
    return helpers.records_payload(_filas(con_nueva), count=count,
                                   stride=68, version=version)


def _texto(con_nueva: bool, version: int = 2) -> bytes:
    count = TEXT_COUNT_NUEVO if con_nueva else TEXT_COUNT
    slots = [b""] * (6 * (count - tables.TEXT_FIRST_ID))
    slots[0] = EXISTENTE.encode("utf-8")
    if con_nueva:
        slots[SLOT_NUEVO] = MARCADOR.encode("utf-8")
    return helpers.text_payload(slots, count=count, version=version)


@pytest.fixture()
def specs():
    """Las dos tablas declaradas con la geometria del dump (8 filas / 10 ids)."""
    with _spec_items(), \
            helpers.text_spec(index=TEXT_TABLE, count=TEXT_COUNT):
        yield


@pytest.fixture()
def romfs_derivado(tmp_path):
    """Contenedor sintetico con la fila y el id de texto anadidos."""
    with _spec_items(), \
            helpers.text_spec(index=TEXT_TABLE, count=TEXT_COUNT):
        raiz = str(tmp_path / "romfs")
        helpers.make_container(raiz, {ITEM_TABLE: _items(True),
                                      TEXT_TABLE: _texto(True)})
        yield raiz


# ---------------------------------------------------------------------------
# La geometria estricta sigue siendo el defecto
# ---------------------------------------------------------------------------

def test_sin_bandera_la_deriva_del_count_falla(specs):
    with pytest.raises(tables.TableError, match="count del header 9 != 8 declarado"):
        N.NameIndex(_items(True), _texto(True))


def test_cli_sin_bandera_no_lee_la_fila_nueva(romfs_derivado, capsys):
    assert cli_main(["--container", romfs_derivado, "row", "983", str(FILA_NUEVA)]) == 1
    error = capsys.readouterr().err
    assert "count del header 9 != 8 declarado" in error


def test_version_no_admite_deriva_aunque_sea_modificado(specs):
    """El `version` es el marcador de formato: con deriva, ni con bandera."""
    with pytest.raises(tables.TableError, match="version del header"):
        N.NameIndex(_items(True, version=9), _texto(True), modificado=True)


# ---------------------------------------------------------------------------
# La geometria derivada
# ---------------------------------------------------------------------------

def test_con_conteo_deriva_pool_por_spec(specs):
    """SPEC-NAMES §11.2 en terminos del count, no como constantes."""
    text = tables.get(TEXT_TABLE)
    items = tables.get(ITEM_TABLE)
    assert text is not None and items is not None
    derivado = tables.con_conteo(text, TEXT_COUNT_NUEVO)
    assert derivado.count == TEXT_COUNT_NUEVO
    assert derivado.pool_start == 64 + 32 * TEXT_COUNT_NUEVO
    assert tables.con_conteo(items, FILAS + 1).count == FILAS + 1
    assert tables.con_conteo(items, FILAS + 1).pool_start is None


def test_con_conteo_sin_cambio_devuelve_el_mismo_spec(specs):
    """El dump canonico no gana geometria nueva: mismo objeto, sin copias."""
    text = tables.get(TEXT_TABLE)
    assert text is not None
    assert tables.con_conteo(text, text.count) is text


def test_con_conteo_en_la_tabla_real_de_nombres():
    """#4650 del registro: 96.102 con count 3001 y 96.134 con count 3002."""
    spec = tables.get(4650)
    assert spec is not None and spec.pool_start == 96102
    derivado = tables.con_conteo(spec, 3002)
    assert derivado.count == 3002 and derivado.pool_start == 96134


def test_nameindex_modificado_resuelve_la_fila_anadida(specs):
    indice = N.NameIndex(_items(True), _texto(True), modificado=True)
    assert indice.items_spec.count == FILAS + 1
    assert indice.text_spec.count == TEXT_COUNT_NUEVO
    assert indice.text_spec.pool_start == 64 + 32 * TEXT_COUNT_NUEVO
    assert indice.text_id(FILA_NUEVA) == 10
    assert indice.resolver(FILA_NUEVA) == MARCADOR
    # la fila de siempre sigue resolviendo con la geometria derivada
    assert indice.resolver(0) == EXISTENTE
    assert indice.resolver(FILAS + 100) is None    # id sin fila -> None


# ---------------------------------------------------------------------------
# La CLI con la bandera
# ---------------------------------------------------------------------------

def test_cli_con_bandera_lee_la_fila_nueva(romfs_derivado, capsys):
    assert cli_main(["--container", romfs_derivado, "--modificado",
                     "row", "983", str(FILA_NUEVA)]) == 0
    salida = capsys.readouterr().out
    assert "aviso: count del header 9 != 8 declarado" in salida
    assert "fila 8 de 9" in salida
    assert "nameIndex" in salida and str(NAME_INDEX_NUEVO) in salida


def test_cli_texto_muestra_el_bloque_en_claro(romfs_derivado, capsys):
    assert cli_main(["--container", romfs_derivado, "--modificado",
                     "row", "4650", "10", "--texto"]) == 0
    salida = capsys.readouterr().out
    assert "pool en %d" % (64 + 32 * TEXT_COUNT_NUEVO) in salida
    assert "texto: %s" % MARCADOR in salida
    # sin --texto no se imprime en claro ni un byte de texto
    assert cli_main(["--container", romfs_derivado, "--modificado",
                     "row", "4650", "10"]) == 0
    assert MARCADOR not in capsys.readouterr().out


def test_cli_save_read_nombres_sobre_el_derivado(tmp_path, capsys):
    """El hueco 0 del save apunta a la fila anadida y sale con su nombre."""
    with _spec_items(), \
            helpers.text_spec(index=TEXT_TABLE, count=TEXT_COUNT):
        raiz = str(tmp_path / "romfs")
        helpers.make_container(raiz, {ITEM_TABLE: _items(True),
                                      TEXT_TABLE: _texto(True)})
        guarda = str(tmp_path / "save")
        fx.make_save(guarda, payload=fx.make_payload(items={0: (FILA_NUEVA, 1)}))
        assert cli_main(["--container", raiz, "--modificado", "save", "read",
                         "--save", guarda, "--nombres", "--json"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["items"][0]["nombre"] == MARCADOR

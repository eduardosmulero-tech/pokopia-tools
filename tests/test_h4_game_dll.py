"""H4 en el `game.dll` nativo: correspondencia `main+offset -> PE` y parche de 12 B.

Lo que estos tests fijan, que es lo que puede romperse en silencio:

* el spec declara dos sitios de 6 B que se anulan a `nop` (el equivalente x86-64 del
  `nop` de AArch64 son 6 B por salto, no 4: 2 x 6 = 12, no 8);
* el spec y el codigo no se separan: los desplazamientos de invitado son los dos `b.lt`
  del lector de fotogramas y las dos RVAs caen en la misma funcion traducida;
* la diferencia entre origen y copia es **exactamente** la declarada (funcion de rangos);
* con el DLL nativo (`PKP_GAME_DLL`) la tabla del runtime da la funcion que dice el spec,
  y la comprobacion estructural del PE pasa entera (esta ultima exige capstone).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARCHEO = os.path.join(RAIZ, "tools", "parcheo")
if PARCHEO not in sys.path:
    sys.path.insert(0, PARCHEO)

import h4_game_dll  # noqa: E402
import pe_leer  # noqa: E402

ruta_spec = os.path.join(PARCHEO, "parches", "h4-panel-game-dll.json")
DLL = os.environ.get("PKP_GAME_DLL")
sin_dll = pytest.mark.skipif(not DLL or not os.path.exists(DLL or ""),
                             reason="sin game.dll nativo (exporta PKP_GAME_DLL)")


def _spec() -> dict:
    with open(ruta_spec, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------- el spec, sintetico
def test_dos_sitios_uno_por_umbral():
    mods = _spec()["modificaciones"]
    assert [m["umbral"] for m in mods] == [1, 2]
    assert [m["guest"] for m in mods] == ["0x17a2988", "0x17a2a58"]


def test_cada_sitio_anula_seis_bytes_a_nop():
    for m in _spec()["modificaciones"]:
        assert len(bytes.fromhex(m["esperado"])) == 6
        assert bytes.fromhex(m["nuevo"]) == b"\x90" * 6
        assert m["esperado"].startswith("0f85"), "el sitio tiene que ser un jne rel32"


def test_las_dos_rvas_caen_en_la_misma_funcion():
    mods = _spec()["modificaciones"]
    base = min(int(m["rva"], 0) for m in mods)
    for m in mods:
        assert int(m["rva"], 0) >= base
        assert int(m["rva"], 0) - base < 0x1000


def test_el_spec_pasa_el_lector_de_parches():
    import parche

    spec = parche.leer_spec(ruta_spec)
    assert len(spec["modificaciones"]) == 2


# --------------------------------------------------------------- diferencia byte a byte
def test_bytes_distintos_devuelve_los_rangos_de_verdad(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    original = bytearray(range(256)) * 40
    nuevo = bytearray(original)
    nuevo[100:106] = b"\x90" * 6
    nuevo[1000:1002] = b"\x00\x01"
    a.write_bytes(bytes(original))
    b.write_bytes(bytes(nuevo))
    assert h4_game_dll._bytes_distintos(str(a), str(b), bloque=97) == [(100, 106), (1000, 1002)]


def test_bytes_distintos_de_ficheros_iguales_es_vacio(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"\x00" * 1000)
    assert h4_game_dll._bytes_distintos(str(a), str(a)) == []


def test_bytes_distintos_aborta_si_cambia_el_tamano(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"\x00" * 10)
    b.write_bytes(b"\x00" * 11)
    with pytest.raises(h4_game_dll.Fallo):
        h4_game_dll._bytes_distintos(str(a), str(b))


def test_las_formulas_de_v_del_lifted_son_el_desbordamiento():
    """`b.lt` es N != V; si la V del lifted no fuera la real, el parche cambiaria el test."""
    assert h4_game_dll.comprobar_flags() == 0


# ------------------------------------------------------------------- con el DLL nativo
@sin_dll
def test_la_tabla_del_runtime_da_la_funcion_del_spec():
    pe = pe_leer.abrir(DLL, con_entropia=False)
    from mapear import Mapa

    mapa = Mapa(pe)
    mapa.leer_tabla()
    funcion = mapa.funcion_de_guest(0x17A2988)
    assert funcion is not None
    assert mapa.funcion_de_guest(0x17A2A58) is funcion
    assert funcion.rva == 0xBB6F3B0
    assert pe.rva_a_offset(0xBB716DA) == 0xBB70ADA
    assert pe.rva_a_offset(0xBB71F71) == 0xBB71371


@sin_dll
def test_los_bytes_esperados_estan_en_el_dll_intacto():
    pe = pe_leer.abrir(DLL, con_entropia=False)
    for m in _spec()["modificaciones"]:
        off = pe.rva_a_offset(int(m["rva"], 0))
        assert pe.leer(off, 6).hex() == m["esperado"]


@sin_dll
def test_comprobar_la_estructura_del_sitio():
    pytest.importorskip("capstone", reason="la comprobacion estructural usa capstone")
    assert h4_game_dll.comprobar(DLL) == 0

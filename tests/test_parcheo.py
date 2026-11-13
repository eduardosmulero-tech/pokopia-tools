"""Parcheo del `game.dll` nativo: lector PE, tabla de funciones y parche reversible.

Lo sintetico va aqui y corre siempre; lo que exige el binario real se salta con motivo
si no esta (misma convencion que el resto de la suite: `PKP_GAME_DLL`).

Lo que estos tests fijan, que es lo que puede romperse en silencio:

* un parche que cambia de longitud o que no declara los bytes esperados **aborta**;
* `aplicar` se niega a trabajar si origen y copia son el mismo fichero;
* la ida y vuelta sobre una copia devuelve el `sha256` del origen (C3 de la tarjeta);
* la tabla de funciones del DLL cuadra con la exportacion `nxw_game_function_count`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARCHEO = os.path.join(RAIZ, "tools", "parcheo")
if PARCHEO not in sys.path:
    sys.path.insert(0, PARCHEO)

import parche  # noqa: E402
import mapear  # noqa: E402
import pe_leer  # noqa: E402

DLL = os.environ.get("PKP_GAME_DLL")
sin_dll = pytest.mark.skipif(not DLL or not os.path.exists(DLL or ""),
                            reason="sin game.dll nativo (exporta PKP_GAME_DLL)")


def _spec(tmp_path, modificaciones, **extra):
    ruta = tmp_path / "spec.json"
    cuerpo = {"nombre": "t", "modificaciones": modificaciones}
    cuerpo.update(extra)
    ruta.write_text(json.dumps(cuerpo), encoding="utf-8")
    return str(ruta)


# --------------------------------------------------------------- validacion del spec
def test_un_parche_que_cambia_de_longitud_aborta(tmp_path):
    ruta = _spec(tmp_path, [{"va": "0x10", "esperado": "41", "nuevo": "c3c3"}])
    with pytest.raises(SystemExit):
        parche.leer_spec(ruta)


def test_un_parche_a_medias_aborta(tmp_path):
    ruta = _spec(tmp_path, [{"va": "0x10", "esperado": "41", "nuevo": "c3", "motivo": ""},
                            {"va": "0x20", "esperado": "41"}])
    with pytest.raises(SystemExit):
        parche.leer_spec(ruta)


def test_un_parche_vacio_aborta(tmp_path):
    ruta = _spec(tmp_path, [])
    with pytest.raises(SystemExit):
        parche.leer_spec(ruta)


def test_un_parche_no_puede_traer_rva_y_va_a_la_vez(tmp_path):
    ruta = _spec(tmp_path, [{"rva": "0x10", "va": "0x180000010",
                             "esperado": "41", "nuevo": "c3"}])
    with pytest.raises(SystemExit):
        parche.leer_spec(ruta)


@sin_dll
def test_rva_y_va_absoluta_llegan_al_mismo_offset():
    """En una imagen cargada VA = image_base + RVA; el lector admite las dos formas."""
    pe = pe_leer.abrir(DLL, con_entropia=False)
    rva = mapear.Mapa(pe)._export_rva("nxw_game_abi")
    assert rva is not None
    assert pe.rva_a_offset(rva) == pe.va_a_offset(pe.image_base + rva) == pe.va_a_offset(rva)
    assert pe.va_de_rva(rva) == pe.image_base + rva


def test_no_se_parchea_el_original(tmp_path):
    falso = tmp_path / "game.dll"
    falso.write_bytes(b"MZ")
    spec = _spec(tmp_path, [{"va": "0x10", "esperado": "41", "nuevo": "c3"}])
    with pytest.raises(SystemExit):
        parche.aplicar(str(falso), str(falso), spec, seco=False, forzar=False)


def test_revertir_sin_registro_aborta(tmp_path):
    origen = tmp_path / "o.bin"
    copia = tmp_path / "c.bin"
    origen.write_bytes(b"abc")
    copia.write_bytes(b"abc")
    with pytest.raises(SystemExit):
        parche.revertir(str(origen), str(copia), seco=False)


def test_la_cli_exige_spec_para_aplicar(tmp_path):
    falso = tmp_path / "game.dll"
    falso.write_bytes(b"MZ")
    assert parche.main(["aplicar", "--origen", str(falso), "--copia",
                        str(tmp_path / "copia.dll")]) == 2


# --------------------------------------------------------------- contra el DLL real
@sin_dll
def test_el_lector_ve_las_tres_secciones_y_su_imagen():
    pe = pe_leer.abrir(DLL, con_entropia=False)
    nombres = [s.nombre for s in pe.secciones]
    assert nombres == [".text", ".rdata", ".pdata"]
    assert pe.machine == 0x8664
    assert pe.image_base % 0x10000 == 0
    assert pe.entry_point_rva == 0  # es un contenedor que carga nxrt.exe, no tiene entrada


@sin_dll
def test_la_tabla_de_funciones_cuadra_con_la_exportacion():
    pe = pe_leer.abrir(DLL, con_entropia=False)
    mapa = mapear.Mapa(pe)
    rva_tabla = mapa._export_rva("nxw_game_functions")
    rva_cuenta = mapa._export_rva("nxw_game_function_count")
    assert rva_tabla is not None and rva_cuenta is not None
    datos = pe.leer(pe.rva_a_offset(rva_tabla), 16 * 8)
    cuenta = int.from_bytes(pe.leer(pe.rva_a_offset(rva_cuenta), 4), "little")
    assert cuenta > 100_000
    # los registros van ordenados por direccion de invitado: es lo que permite bisecar
    primeros = [int.from_bytes(datos[i * 16:i * 16 + 8], "little") for i in range(8)]
    assert primeros == sorted(primeros)
    assert len(set(primeros)) == len(primeros)


@sin_dll
def test_una_va_fuera_del_fichero_no_resuelve():
    pe = pe_leer.abrir(DLL, con_entropia=False)
    assert pe.va_a_offset(0xF000_0000_0000) is None


@sin_dll
def test_ida_y_vuelta_sobre_una_copia(tmp_path):
    """C3: aplicar y revertir deja la copia con el sha256 del origen."""
    origen = DLL
    copia = str(tmp_path / "game.copia.dll")
    shutil.copyfile(origen, copia)
    hash_origen = parche.sha256(origen)
    assert parche.sha256(copia) == hash_origen

    pe = pe_leer.abrir(origen, con_entropia=False)
    rva = mapear.Mapa(pe)._export_rva("nxw_game_build_id")
    assert rva is not None
    actual = pe.leer(pe.rva_a_offset(rva), 4)
    otro = bytes(b ^ 0xFF for b in actual)
    spec = _spec(tmp_path, [{"rva": hex(rva), "esperado": actual.hex(),
                             "nuevo": otro.hex(), "motivo": "ida y vuelta"}])

    assert parche.aplicar(origen, copia, spec, seco=False, forzar=False) == 0
    assert parche.sha256(copia) != hash_origen
    assert pe_leer.abrir(copia, con_entropia=False).leer(pe.rva_a_offset(rva), 4) == otro
    assert parche.revertir(origen, copia, seco=False) == 0
    assert parche.sha256(copia) == hash_origen
    assert parche.sha256(origen) == hash_origen

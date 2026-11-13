# -*- coding: utf-8 -*-
"""`kidstask` (`_TGK0000`): lector, validacion y CLI (informe t_df5ad471).

Blobs sinteticos construidos byte a byte con el mismo layout medido en el
build 655360, para que la suite corra sin el juego. Los casos que importan
son los que separan un lector de un adivinador:

* el payload se agota exacto (resto = 0) con la unidad por `tipo`
  (1 = Byte, 5 = UInt32); un `tipo` desconocido falla, no se inventa;
* el recuento de la cabecera tiene que salir al recorrer el fichero;
* la cadena `INGK0000` se alinea a 4: un registro de tamano impar (497 en
  el real) deja un hueco de 3 B y el siguiente sigue parseando;
* un enlace fuera de rango y una cola que no cubre el fichero fallan.

Y tres pruebas contra el dump real (se saltan con motivo si no esta) mas una
contra `kidstypeinfodb.yml` (se salta si no esta clonado en build/refs).
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from pokopia import kidstask as kt
from pokopia import paths
from pokopia.cli import main
from tests.test_objdb import entrada_idrk, escribir_fdata

KIDSTASK = kt.KIDSTASK_KTID


# ---------------------------------------------------------------------------
# Construccion del blob sintetico
# ---------------------------------------------------------------------------

def nodo(ident: int, h1: int = 0, enlaces=(), props=()) -> bytes:
    """Un registro `INGK0000` con el payload medido.

    `props` = lista de `(tipo, len, hash_prop, valores)`; los valores se
    escriben con la unidad que le corresponde al tipo.
    """
    pl = struct.pack("<II", len(props), len(enlaces))
    if enlaces:
        pl += struct.pack("<%dI" % len(enlaces), *enlaces)
    carga = b""
    for tipo, ln, hash_prop, valores in props:
        pl += struct.pack("<III", tipo, ln, hash_prop)
        # tipos fuera de UNIDAD: el constructor es andamio, no el lector; el
        # que tiene que rechazarlos es `parse` (lo comprueba su propio test).
        if kt.UNIDAD.get(tipo, 4) == 4:
            carga += struct.pack("<%dI" % len(valores), *valores)
        else:
            carga += bytes(valores)
    pl += carga
    return b"INGK0000" + struct.pack("<IIII", 24 + len(pl), ident, h1, 0) + pl


def fichero(nodos, *, recuento: int | None = None,
            firma: bytes = kt.FILE_MAGIC) -> bytes:
    """`_TGK0000` con cabecera de 32 B y la cadena alineada a 4."""
    cuerpo = b""
    pos = 32
    for reg in nodos:
        if pos % 4:
            cuerpo += b"\x00" * (4 - pos % 4)
            pos += 4 - pos % 4
        cuerpo += reg
        pos += len(reg)
    total = 32 + len(cuerpo)
    cab = firma + struct.pack("<IIIIII", 32, 24,
                              len(nodos) if recuento is None else recuento,
                              0x22704EBB, 0, total)
    return cab + cuerpo


def ejemplo() -> bytes:
    """Dos nodos: el primero con una prop Byte y otra de array UInt32."""
    return fichero([
        nodo(0x11111111, h1=0x12345678, enlaces=[1],
             props=[(1, 1, 0x05D92ACC, (1,)),
                    (5, 3, 0x02EB563C, (0xAA, 0xBB, 0xCC))]),
        nodo(0x22222222, h1=0x00000000),
    ])


# ---------------------------------------------------------------------------
# El lector
# ---------------------------------------------------------------------------

def test_parse_cabecera_nodos_y_enlaces():
    k = kt.parse(ejemplo(), origen="<sintetico>")
    assert k.cabecera["firma"] == "_TGK0000"
    assert k.cabecera["cabecera_tamano"] == 32
    assert k.cabecera["cabecera_de_registro"] == 24
    assert k.cabecera["recuento"] == 2
    assert k.cabecera["campo_0x1c"] == k.bytes_totales
    assert k.cubre_el_fichero
    assert [n.id for n in k.nodos] == [0x11111111, 0x22222222]
    assert k.nodos[0].enlaces == (1,)
    assert k.aristas() == [(0, 1)]


def test_payload_se_agota_con_unidad_por_tipo():
    """tipo 1 son bytes y tipo 5 son u32: los tres valores caben exactos."""
    k = kt.parse(ejemplo())
    byte_prop, array_prop = k.nodos[0].propiedades
    assert byte_prop.tipo == 1 and byte_prop.valores == (1,)
    assert byte_prop.bytes_totales == 1
    assert array_prop.tipo == 5 and array_prop.valores == (0xAA, 0xBB, 0xCC)
    assert array_prop.bytes_totales == 12


def test_registro_impar_se_alinea_y_el_siguiente_sigue():
    """El registro 1 del real mide 497: el hueco son 3 B y no rompe nada."""
    k = kt.parse(ejemplo())
    assert k.nodos[0].tamano % 4  # impar a proposito (45 + 4*2)
    assert len(k.nodos) == 2 and k.nodos[1].indice == 1


def test_firma_mala_falla():
    with pytest.raises(kt.KidstaskFormatError, match="firma"):
        kt.parse(fichero([nodo(1)], firma=b"_XXK0000"))


def test_recuento_que_no_casa_falla():
    with pytest.raises(kt.KidstaskFormatError, match="recuento de cabecera 5"):
        kt.parse(fichero([nodo(1), nodo(2)], recuento=5))


def test_cola_que_no_cubre_falla():
    with pytest.raises(kt.KidstaskFormatError, match="no cubre el fichero"):
        kt.parse(fichero([nodo(1)]) + b"\x00" * 8)


def test_tipo_desconocido_falla_no_inventa():
    mal = fichero([nodo(1, props=[(9, 1, 0x1234, (1,))])])
    with pytest.raises(kt.KidstaskFormatError, match="tipo=9 desconocido"):
        kt.parse(mal)


def test_enlace_fuera_de_rango_falla():
    mal = fichero([nodo(1, enlaces=[7]), nodo(2)])
    with pytest.raises(kt.KidstaskFormatError, match="enlace 7 fuera del rango"):
        kt.parse(mal)


def test_payload_con_bytes_de_mas_falla():
    reg = nodo(1)
    reg_mal = (reg[:8] + struct.pack("<I", len(reg) + 4) + reg[12:]
               + b"\x00" * 4)
    with pytest.raises(kt.KidstaskFormatError, match="no se agota"):
        kt.parse(fichero([reg_mal]))


# ---------------------------------------------------------------------------
# El YAML de nombres del Paso 0 (se salta si no esta clonado)
# ---------------------------------------------------------------------------

def test_yaml_de_tipos_resuelve_frame_sync_y_flag():
    if not os.path.isfile(kt.YML_DEFECTO):
        pytest.skip("sin kidstypeinfodb.yml (clona fdata_dump en build/refs)")
    tipos, props = kt.cargar_nombres(kt.YML_DEFECTO)
    assert len(tipos) > 1000
    assert tipos.get(0xAB5B4109) == "TypeInfo::TaskNode::Util::FrameSync"
    assert props.get(0x05D92ACC) == "Flag"


# ---------------------------------------------------------------------------
# La CLI
# ---------------------------------------------------------------------------

def test_cli_sobre_un_fichero_sintetico(tmp_path, capsys):
    ruta = tmp_path / "ejemplo.kidstask"
    ruta.write_bytes(ejemplo())

    assert main(["kidstask", str(ruta)]) == 0
    texto = capsys.readouterr().out
    assert "nodos: 2  aristas: 1  tipos resueltos: 0/2" in texto
    assert "0x11111111" in texto and "enlaces=[1]" in texto

    assert main(["kidstask", str(ruta), "--props"]) == 0
    texto = capsys.readouterr().out
    assert "tipo=1 len=1 0x05d92acc" in texto

    assert main(["kidstask", str(ruta), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["cubre_el_fichero"] is True
    assert doc["aristas"] == ["00->01"]
    assert doc["nodos"][0]["propiedades"][0]["valores"] == [1]
    assert doc["nodos"][0]["tipo_nombre"] is None


def test_cli_fichero_inexistente_es_error(tmp_path, capsys):
    assert main(["kidstask", str(tmp_path / "no.kidstask")]) == 1
    assert "no existe el fichero" in capsys.readouterr().err


def test_cli_tipos_inexistente_es_error(tmp_path, capsys):
    ruta = tmp_path / "ejemplo.kidstask"
    ruta.write_bytes(ejemplo())
    assert main(["kidstask", str(ruta), "--tipos", str(tmp_path / "no.yml")]) == 1
    assert "no existe el YAML de tipos" in capsys.readouterr().err


def test_cli_sobre_un_romfs_sintetico(tmp_path, capsys):
    """Sin `archivo` busca la unica entrada `kidstask` del contenedor."""
    raiz = tmp_path / "romfs"
    (raiz / "motor_asset_re").mkdir(parents=True)
    escribir_fdata(str(raiz / "motor_asset_re" / "a.fdata"),
                   [entrada_idrk(ejemplo(), KIDSTASK, 0xBD13A52E)])
    assert main(["kidstask", "--container", str(raiz)]) == 0
    texto = capsys.readouterr().out
    assert "nodos: 2" in texto and "a.fdata" in texto


# ---------------------------------------------------------------------------
# El dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
HAY_DUMP = os.path.isdir(ROMFS) and any(
    nombre.endswith(".fdata")
    for _, _, ficheros in os.walk(ROMFS) for nombre in ficheros)
necesita_dump = pytest.mark.skipif(
    not HAY_DUMP, reason="sin dump del juego (exporta PKP_ROMFS)")


@necesita_dump
def test_real_los_33_nodos_con_sus_enlaces():
    datos, origen = kt.leer_de_romfs(ROMFS)
    k = kt.parse(datos, origen=origen)
    assert k.cabecera["recuento"] == 33 == len(k.nodos)
    assert k.cubre_el_fichero
    assert k.bytes_totales == 3868
    assert k.cabecera["campo_0x1c"] == 3868
    # el registro 1 es el impar medido (497) y es FrameSync
    assert k.nodos[1].tamano == 497
    assert k.nodos[1].tipo_hash == 0xAB5B4109
    # el grafo: 58 aristas, todo enlaza dentro de rango y 32 vuelve a 0
    assert len(k.aristas()) == 58
    assert all(0 <= j < 33 for _, j in k.aristas())
    assert k.nodos[32].enlaces == (0,)
    assert k.nodos[11].enlaces == tuple(range(12, 18))


@necesita_dump
def test_real_nombres_resueltos_con_el_yaml():
    if not os.path.isfile(kt.YML_DEFECTO):
        pytest.skip("sin kidstypeinfodb.yml (clona fdata_dump en build/refs)")
    tipos, props = kt.cargar_nombres(kt.YML_DEFECTO)
    datos, _ = kt.leer_de_romfs(ROMFS)
    k = kt.parse(datos)
    resueltos = [n for n in k.nodos
                 if k.nombre_de_tipo(n.tipo_hash, tipos, props)]
    assert len(resueltos) == 26
    assert not k.nombre_de_tipo(k.nodos[0].tipo_hash, tipos, props)

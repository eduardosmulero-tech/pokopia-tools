"""Pruebas de `tools/hashes_en_binario.py` que no necesitan el dump.

Lo que se prueba aquí es la maquinaria que puede dar un **negativo falso** si está rota:

* el decodificador LZ4 (si descomprime mal, se busca en bytes que no son el ejecutable);
* la construcción del conjunto de u32 por rejilla (si se deja una rejilla fuera, se pierden
  apariciones);
* la localización de offsets y el análisis de bloque;
* la regla del veredicto, con los umbrales fijos.

El módulo es un script de `tools/`, así que se carga por ruta.
"""

from __future__ import annotations

import importlib.util
import os
import struct

import pytest

RUTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "hashes_en_binario.py")

if not os.path.isfile(RUTA):
    pytest.skip(
        "tools/ no viaja en la release: el buscador de hashes vive en tools/",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def hb():
    spec = importlib.util.spec_from_file_location("hashes_en_binario", RUTA)
    assert spec is not None and spec.loader is not None, "no se pudo cargar %s" % RUTA
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# --- LZ4 formato bloque ------------------------------------------------------

def test_lz4_solo_literales(hb):
    """Bloque de una secuencia con literales y nada más: token alto = longitud."""
    datos = b"hola mundo"
    bloque = bytes([len(datos) << 4]) + datos
    assert hb.lz4_block_decompress(bloque, len(datos)) == datos


def test_lz4_con_match_solapado(hb):
    """`abababab`: 4 literales + match de offset 2 que se solapa consigo mismo + 1 literal.

    El formato bloque exige que la última secuencia sean solo literales, así que el match
    va en medio. Se construye a mano para no depender de un compresor.
    """
    bloque = bytes([0x40]) + b"abab" + struct.pack("<H", 2) + bytes([0x10]) + b"X"
    assert hb.lz4_block_decompress(bloque, 9) == b"ababababX"


def test_lz4_tamano_que_no_cuadra_falla(hb):
    """Si el tamaño descomprimido no es el declarado, se levanta en vez de devolver basura."""
    with pytest.raises(hb.BinarioError):
        hb.lz4_block_decompress(bytes([0x30]) + b"abc", 99)


# --- conjunto de u32 por rejilla --------------------------------------------

def test_u32_set_ve_las_cuatro_rejillas(hb):
    """Un valor que empieza en el offset 1 tiene que salir en la rejilla 1 y no en la 0."""
    valor = 0xDEADBEEF
    datos = b"\x00" + struct.pack("<I", valor) + b"\x00\x00\x00"
    assert valor in hb.u32_set(datos, 1)
    assert valor not in hb.u32_set(datos, 0)


def test_u32_set_no_inventa(hb):
    datos = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    assert hb.u32_set(datos, 0) == {0x04030201, 0x08070605}


# --- offsets y bloques -------------------------------------------------------

def test_find_all_cuenta_y_localiza(hb):
    datos = b"...." + struct.pack("<I", 0x11223344) + b".." + struct.pack("<I", 0x11223344)
    offsets, total = hb.find_all(datos, struct.pack("<I", 0x11223344))
    assert offsets == [4, 10]
    assert total == 2


def test_analizar_bloque_detecta_contiguo_y_alineacion(hb):
    contiguo = hb.analizar_bloque([0x100, 0x104, 0x108])
    assert contiguo["pasos_de_4"] == 2
    assert contiguo["alineadas"] == 3

    disperso = hb.analizar_bloque([0x101, 0x2000002, 0x3000003])
    assert disperso["pasos_de_4"] == 0
    assert disperso["alineadas"] == 0
    assert disperso["mod4"] == {0: 0, 1: 1, 2: 1, 3: 1}


# --- veredicto ---------------------------------------------------------------

def test_veredicto_compilada_si_estan_casi_todos(hb):
    ver = hb.veredicto(87, 88, 0.002)
    assert ver["veredicto"] == "COMPILADA"


def test_veredicto_calculada_si_es_compatible_con_azar(hb):
    ver = hb.veredicto(0, 88, 0.002)
    assert ver["veredicto"] == "CALCULADA EN EJECUCIÓN"
    assert ver["p_valor"] == 1.0


def test_veredicto_indeterminado_en_tierra_de_nadie(hb):
    """Cinco aciertos con tasa base baja no es ni tabla ni azar: se dice, no se elige."""
    ver = hb.veredicto(5, 88, 0.002)
    assert ver["veredicto"] == "INDETERMINADO"


def test_binomial_tail_coincide_con_el_caso_trivial(hb):
    assert hb.binomial_tail(0, 10, 0.5) == 1.0
    assert hb.binomial_tail(10, 10, 0.5) == pytest.approx(0.5 ** 10)


def test_binomial_tail_aguanta_n_grande_sin_desbordar(hb):
    """Con n = 2.043 y k pequeño la cuenta directa desborda el float; esta no."""
    cola = hb.binomial_tail(4, 2043, 0.0011)
    assert 0.0 < cola < 1.0
    # y con p muy pequeño y k=0 sigue siendo 1
    assert hb.binomial_tail(0, 2043, 0.0001) == 1.0

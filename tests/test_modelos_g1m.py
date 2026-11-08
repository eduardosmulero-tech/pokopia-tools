# -*- coding: utf-8 -*-
"""Lectura de G1M/G1T: estructura, malla y localizacion de diferencias.

Los ficheros de prueba se construyen **aqui**, byte a byte, con modelos
sinteticos de 4 vertices y 6 indices. No se usa ni un byte del juego: lo que se
prueba es el lector (`pokopia/g1m.py`) y, cuando el arbol de trabajo lo trae, el
comparador (`tools/modelos/pkp_modelo.py`), no el dump. `tools/` no viaja en la
release, asi que las pruebas del comparador y de las herramientas se **saltan**
ahi en vez de fallar.

Cubre lo que la tarjeta exige poder afirmar:

* un `G1M` se reconoce aunque vaya detras de su envoltorio de 12 B y **no** se
  reconoce buscando las cadenas canonicas (`G1M\\0`), que es el falso negativo
  que costo un barrido entero;
* la malla se cuenta igual por los dos caminos: la tira de indices se convierte
  en triangulos y los degenerados (los que unen trozos de tira) se cuentan aparte;
* una diferencia de unos pocos bytes se localiza **por campo y por region**, no
  con un «difieren N bytes».
"""

from __future__ import annotations

import os
import re
import struct
import sys

import pytest

from pokopia import g1m

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELOS = os.path.join(RAIZ, "tools", "modelos")

#: El comparador vive en `tools/` (no viaja en la release): se importa si esta.
pkp_modelo = None
if os.path.isdir(MODELOS):
    if MODELOS not in sys.path:
        sys.path.insert(0, MODELOS)
    try:
        import pkp_modelo  # noqa: E402,F811
    except ImportError:      # sin el arbol de herramientas no hay comparador
        pkp_modelo = None


# ---------------------------------------------------------------------------
# Constructores sinteticos
# ---------------------------------------------------------------------------

def _seccion(magic: int, datos: bytes) -> bytes:
    return struct.pack("<III", magic, 12 + len(datos), 1) + datos


def _g1mg(indices: tuple[int, ...], vertices: int = 4, primitiva: int = 4) -> bytes:
    """Chunk GM1G minimo: vertex buffer, index buffer y un submesh.

    Version `7300`, la del fichero real: por encima de `0400` cada entrada de
    buffer lleva un u32 extra detras de su cabecera, y el lector lo tiene que
    aplicar aqui igual que alli (por eso los sinteticos la llevan).
    """
    stride = 12
    vb = struct.pack("<IIII", 0, stride, vertices, 0) + b"\x00" * (stride * vertices)
    sec_vb = _seccion(g1m.SEC_VERTEX_BUFFERS, vb)
    ib = (struct.pack("<III", len(indices), 16, 0)
          + struct.pack("<%dH" % len(indices), *indices))
    sec_ib = _seccion(g1m.SEC_INDEX_BUFFER, ib)
    sub = struct.pack("<14I", 0, 0, 0, 0, 0, 0, 0, 0, 0, primitiva,
                      0, vertices, 0, len(indices))
    sec_sub = _seccion(g1m.SEC_SUBMESH, sub)
    secciones = sec_vb + sec_ib + sec_sub
    cabecera = (b"GM1G" + struct.pack("<II", 0x30303733, 48 + len(secciones))
                + b"NX\x00\x00" + struct.pack("<I", 0) + struct.pack("<6f", *([0.0] * 6))
                + struct.pack("<I", 3))
    return cabecera + secciones


def _g1m(indices: tuple[int, ...], vertices: int = 4, primitiva: int = 4) -> bytes:
    """G1M sintetico con los cuatro chunks que lleva el del contenedor.

    El chunk GM1G **no** lleva cabecera propia: la de 48 B del propio GM1G es la
    del chunk (magic, version y tamano coinciden), que es como va en el fichero
    real: los otros tres chunks sí son cabecera de 12 B sin cuerpo.
    """
    gm1g = _g1mg(indices, vertices, primitiva)
    chunks = (b"FM1G" + b"0300" + struct.pack("<I", 12)
              + b"SM1G" + b"2300" + struct.pack("<I", 12)
              + b"MM1G" + b"0200" + struct.pack("<I", 12)
              + gm1g)
    return b"_M1G" + b"7300" + struct.pack("<IIII", 24 + len(chunks), 24, 0, 4) + chunks


def _envoltorio(cuerpo: bytes) -> bytes:
    """El envoltorio de 12 B que lleva el modelo dentro del contenedor."""
    return struct.pack("<III", 1, 12, len(cuerpo)) + cuerpo


def _g1t(n: int = 2) -> bytes:
    """G1T sintetico: cabecera de 28 B, flags, tabla de offsets relativos y registros."""
    tabla = 28 + 4 * n
    registros = []
    offs = []
    pos = 4 * n  # la tabla ocupa 4*n y los datos empiezan justo detras
    for i in range(n):
        offs.append(pos)
        reg = struct.pack("<BBBBII", 0x40, 0x60, (10 & 0xF) | ((9 & 0xF) << 4), 0,
                          0x12240000, 12) + b"\xAA" * 8
        registros.append(reg)
        pos += len(reg)
    total = tabla + 4 * n + sum(len(r) for r in registros)
    cab = (b"GT1G" + b"0600" + struct.pack("<IIIII", total, tabla, n, 24, 0))
    return cab + struct.pack("<%dI" % n, *([0] * n)) + struct.pack("<%dI" % n, *offs) + b"".join(registros)


# ---------------------------------------------------------------------------
# G1M: estructura
# ---------------------------------------------------------------------------

def test_g1m_cabecera_y_chunks():
    fichero = _g1m((0, 1, 2, 2, 3, 0))
    g = g1m.parse_g1m(fichero)
    assert g["version"] == "7300"
    assert g["tamano"] == len(fichero)
    assert [c["magic"] for c in g["chunks"]] == ["FM1G", "SM1G", "MM1G", "GM1G"]
    assert g["problemas"] == []
    # el tamano de cada chunk incluye su cabecera: el siguiente empieza en pos+tamano
    assert g["chunks"][-1]["offset"] + g["chunks"][-1]["tamano"] == g["tamano"]


def test_g1m_con_longitud_declarada_incorrecta_se_reporta():
    fichero = bytearray(_g1m((0, 1, 2)))
    struct.pack_into("<I", fichero, 8, len(fichero) + 4)
    g = g1m.parse_g1m(bytes(fichero))
    assert g["problemas"], "un tamano que no cuadra tiene que salir como problema"


def test_geometria_de_la_tira_cuenta_degenerados_aparte():
    # tira de 6 indices = 4 ventanas; las dos que unen trozos de tira son
    # degeneradas (repiten vertice) y no cuentan como triangulo real
    fichero = _g1m((0, 1, 2, 2, 3, 0))
    geo = g1m.geometria(g1m.parse_g1m(fichero))
    malla = geo["mallas"][0]
    assert malla["topologia"] == "trianglestrip"
    assert malla["vertices"] == 4
    assert malla["indices"] == 6
    assert malla["triangulos"] == 4
    assert malla["triangulos_degenerados"] == 2
    assert malla["triangulos_reales"] == 2
    assert malla["secuencia_triangulos"] == [(0, 1, 2), (0, 2, 3)]
    assert malla["max_indice"] == 3
    assert geo["vertices"] == 4 and geo["indices"] == 6 and geo["triangulos"] == 2


def test_geometria_de_lista_de_triangulos():
    fichero = _g1m((0, 1, 2, 1, 2, 3), primitiva=3)
    geo = g1m.geometria(g1m.parse_g1m(fichero))
    assert geo["mallas"][0]["topologia"] == "trianglelist"
    assert geo["mallas"][0]["triangulos"] == 2
    assert geo["mallas"][0]["triangulos_degenerados"] == 0


def test_problemas_detecta_un_indice_fuera_del_buffer():
    fichero = _g1m((0, 1, 2, 3, 4, 0), vertices=4)   # el 4 no existe
    fallos = g1m.problemas(fichero)
    assert any("referencia el vertice 4" in f for f in fallos), fallos


def _g1m_dos_buffers(indices: tuple[int, ...], vertices: int = 4,
                      primitiva: int = 3, vb_index: int = 1) -> bytes:
    """GM1G con dos buffers de vertices: uno por vertice y otro constante.

    Es el caso de 4 de los 26 modelos reales extraidos de `.fdata`: el submesh
    apunta con su `vb_index` a un conjunto de atributos que incluye un buffer de
    `count = 1` (un bloque constante que se repite en cada vertice), asi que el
    `count` del buffer **no** es el numero de vertices de la malla.
    """
    stride = 12
    vb0 = struct.pack("<IIII", 0, stride, vertices, 0) + b"\x00" * (stride * vertices)
    vb1 = struct.pack("<IIII", 0, 8, 1, 0) + b"\x00" * 8
    datos_vb = vb0 + vb1
    sec_vb = struct.pack("<III", g1m.SEC_VERTEX_BUFFERS, 12 + len(datos_vb), 2) + datos_vb
    ib = (struct.pack("<III", len(indices), 16, 0)
          + struct.pack("<%dH" % len(indices), *indices))
    sec_ib = _seccion(g1m.SEC_INDEX_BUFFER, ib)
    sub = struct.pack("<14I", 0, vb_index, 0, 0, 0, 0, 0, 0, 0, primitiva,
                      0, vertices, 0, len(indices))
    sec_sub = _seccion(g1m.SEC_SUBMESH, sub)
    secciones = sec_vb + sec_ib + sec_sub
    cabecera = (b"GM1G" + struct.pack("<II", 0x30303733, 48 + len(secciones))
                + b"NX\x00\x00" + struct.pack("<I", 0) + struct.pack("<6f", *([0.0] * 6))
                + struct.pack("<I", 3))
    gm1g = cabecera + secciones
    chunks = (b"FM1G" + b"0300" + struct.pack("<I", 12)
              + b"SM1G" + b"2300" + struct.pack("<I", 12)
              + b"MM1G" + b"0200" + struct.pack("<I", 12)
              + gm1g)
    return b"_M1G" + b"7300" + struct.pack("<IIII", 24 + len(chunks), 24, 0, 4) + chunks


def test_problemas_no_confunde_el_buffer_constante_con_los_vertices():
    # el submesh apunta al buffer de count 1 y declara 4 vertices: no es un fallo
    fichero = _g1m_dos_buffers((0, 1, 2, 2, 3, 0), vertices=4)
    assert g1m.problemas(fichero) == []
    malla = g1m.geometria(g1m.parse_g1m(fichero))["mallas"][0]
    assert malla["vb_count"] == 1, "el buffer referenciado es el constante"
    assert malla["vertices"] == 4 and malla["max_indice"] == 3


def test_problemas_sigue_detectando_un_indice_fuera_con_dos_buffers():
    fichero = _g1m_dos_buffers((0, 1, 2, 3, 4, 0), vertices=4)   # el 4 no existe
    fallos = g1m.problemas(fichero)
    assert any("referencia el vertice 4" in f for f in fallos), fallos


# ---------------------------------------------------------------------------
# Magics: el falso negativo clasico
# ---------------------------------------------------------------------------

def test_clasificar_encuentra_el_g1m_detras_del_envoltorio():
    cuerpo = _g1m((0, 1, 2))
    blob = _envoltorio(cuerpo)
    clase = g1m.clasificar(blob)
    assert clase["tipo"] == "g1m"
    assert clase["offset"] == 12
    assert blob[:4] != g1m.MAGIC_G1M, "el magic no esta en el byte 0: es el caso real"
    assert blob[clase["offset"]:clase["offset"] + 4] == g1m.MAGIC_G1M


def test_las_cadenas_canonicas_no_encuentran_el_magic():
    blob = _envoltorio(_g1m((0, 1, 2)))
    for cadena in (b"G1M\0", b"G1M_"):
        assert cadena not in blob, "si apareciera, el barrido por cadenas valdria"


def test_clasificar_textura_y_vacio():
    assert g1m.clasificar(_g1t())["tipo"] == "g1t"
    assert g1m.clasificar(b"")["tipo"] == "vacio"
    assert g1m.clasificar(b"\x01\x02\x03\x04")["tipo"] == "otro"


# ---------------------------------------------------------------------------
# G1T
# ---------------------------------------------------------------------------

def test_g1t_cabecera_y_offsets_relativos_a_la_tabla():
    fichero = _g1t(2)
    t = g1m.parse_g1t(fichero)
    assert t["version"] == "0600"
    assert t["tamano"] == len(fichero)
    assert t["n_texturas"] == 2
    assert t["offset_tabla"] == 36
    assert t["flags"] == [0, 0]
    assert [x["offset"] for x in t["texturas"]] == [44, 64]
    assert t["texturas"][0]["formato"] == 0x60
    assert t["texturas"][0]["ancho"] == 1024 and t["texturas"][0]["alto"] == 512
    assert t["texturas"][0]["mips"] == 4


# ---------------------------------------------------------------------------
# Comparador: localizar la diferencia
# ---------------------------------------------------------------------------

def test_comparar_estructura_localiza_el_cambio_en_la_tira():
    if pkp_modelo is None:
        pytest.skip("tools/modelos no esta (no viaja en la release)")
    a = _g1m((0, 1, 2, 2, 3, 0))
    b = _g1m((0, 1, 2, 3, 0))          # una tira mas corta, mismos triangulos reales
    est = pkp_modelo.comparar_estructura(a, b)
    campos = {c["campo"]: (c["a"], c["b"]) for c in est["campos_distintos"]}
    assert campos["G1M.tamano"][0] - campos["G1M.tamano"][1] == 2
    assert campos["INDEX_BUFFER[0].count"] == (6, 5)
    assert campos["SUBMESH[0].index_count"] == (6, 5)
    regiones = {r["region"]: r for r in est["regiones_distintas"]}
    assert "GM1G.seccion INDEX_BUFFER" in regiones
    # el vertex buffer no cambia y no aparece entre las regiones distintas
    assert "GM1G.seccion VERTEX_BUFFERS" not in regiones


def test_comparar_estructura_sin_cambios_no_reporta_nada():
    if pkp_modelo is None:
        pytest.skip("tools/modelos no esta (no viaja en la release)")
    a = _g1m((0, 1, 2))
    est = pkp_modelo.comparar_estructura(a, a)
    assert est["campos_distintos"] == []
    assert est["regiones_distintas"] == []
    assert est["secciones_movidas"] == []


def test_comparar_dos_ficheros_iguales_da_malla_identica(tmp_path):
    if pkp_modelo is None:
        pytest.skip("tools/modelos no esta (no viaja en la release)")
    datos = _g1m((0, 1, 2, 2))
    pa = tmp_path / "a.g1m"
    pb = tmp_path / "b.g1m"
    pa.write_bytes(datos)
    pb.write_bytes(datos)
    res = pkp_modelo.comparar(str(pa), str(pb))
    assert res["identicos"] is True
    assert res["ok_malla"] and res["ok_estructural"]
    assert res["vertices_a"] == res["vertices_b"] == 4


def test_diferencias_localiza_un_tramo():
    assert g1m.diferencias(b"abcd", b"abcd") == []
    tramos = g1m.diferencias(b"abcd", b"abXd")
    assert tramos == [{"inicio": 2, "fin": 3, "bytes": 1}]
    tramos = g1m.diferencias(b"abcd", b"ab")
    assert tramos[-1]["longitud"] == "a=4 b=2"


# ---------------------------------------------------------------------------
# Higiene del repo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", sorted(
    f for f in (os.listdir(MODELOS) if os.path.isdir(MODELOS) else []) if f.endswith(".py")))
def test_las_herramientas_de_modelos_no_llevan_rutas_de_esta_maquina(nombre):
    if not os.path.isdir(MODELOS):
        pytest.skip("tools/modelos no esta (no viaja en la release)")
    ruta = os.path.join(MODELOS, nombre)
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    hallazgos = re.findall(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"']*", texto)
    assert not hallazgos, "%s lleva rutas absolutas: %s" % (nombre, hallazgos[:3])

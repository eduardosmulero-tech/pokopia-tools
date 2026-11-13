"""Cruce objdb <-> catalogo: las piezas que se pueden fijar sin el dump.

`tools/cruce_objdb_catalogo.py` es un script de medicion y su resultado depende del build,
pero sus dos lectores (el del catalogo y el del `kidsobjdb`) y el verificador de orden del
array de hashes son codigo que **tiene que fallar** cuando los bytes no cuadran. Eso es lo
que se fija aqui: se construyen blobs sinteticos con el formato medido y se comprueba que
acepta los buenos y rechaza los malos. El resto (los recuentos del dump real) se verifica
ejecutando el script, y su salida vive en `informes/t_745d06e3/`.

Sin dump: todo lo de este fichero se construye byte a byte.
"""

from __future__ import annotations

import os
import struct
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import cruce_objdb_catalogo as cruce  # noqa: E402


def _dok(registros: list[bytes]) -> bytes:
    """Contenedor `_DOK0000` con los registros dados, alineados a 4 B."""
    cuerpo = bytearray()
    cuerpo += struct.pack("<8s5I", b"_DOK0000", 28, 24, len(registros), 0, 0)
    for registro in registros:
        pos = len(cuerpo)
        if pos % 4:
            cuerpo += b"\x00" * (4 - pos % 4)
        cuerpo += registro
    return bytes(cuerpo)


def _registro(pares: list[tuple[int, int, tuple[int, ...]]], *, ident: int = 1,
              tipo: int = 0x1234, cola: bytes = b"") -> bytes:
    """Registro `IDOK0000`: cabeceras de par, luego TODOS los valores, luego la cola."""
    cabeceras = b"".join(struct.pack("<III", kind, len(valores), clave)
                         for kind, clave, valores in pares)
    valores = b"".join(struct.pack("<%dI" % len(v), *v) if v else b""
                       for _k, _c, v in pares)
    cuerpo = cabeceras + valores + cola
    return (struct.pack("<8sIIII", b"IDOK0000", 24 + len(cuerpo), ident, tipo, len(pares))
            + cuerpo)


def test_kt_hash_contra_vector_del_motor():
    """El vector viene del motor (nombre de fichero real), no de este calculo."""
    assert cruce.kt_hash("CharacterEditor.shader.kidssingletondb") == 0x718CCB8B


def test_verifica_orden_acepta_el_array_con_su_hueco():
    hashes = [0x11111111, 0x22222222, 0x33333333]
    relleno = b"\xaa" * 16
    array = struct.pack("<II", hashes[0], hashes[1]) + b"\x00" * 8 + \
        struct.pack("<I", hashes[2])
    registro = relleno + array + b"\xbb" * 8
    offset, hechos, huecos = cruce._verifica_orden(registro, hashes)
    assert (offset, hechos) == (len(relleno), 3)
    assert huecos == (8,)


def test_verifica_orden_rechaza_un_array_desordenado():
    hashes = [0x11111111, 0x22222222, 0x33333333]
    array = struct.pack("<III", hashes[0], hashes[2], hashes[1])
    assert cruce._verifica_orden(array, hashes) == (-1, 0, ())


def test_itera_registros_lee_el_blob_bueno():
    blob = _dok([_registro([(5, 0xAAAA, (1, 2)), (5, 0xBBBB, ())], ident=7, tipo=0x99)])
    vistos = list(cruce.itera_registros(blob))
    assert len(vistos) == 1
    ident, tipo, lista = vistos[0]
    assert (ident, tipo) == (7, 0x99)
    assert [p.clave for p in lista] == [0xAAAA, 0xBBBB]
    assert lista[0].valores == (1, 2)
    assert lista[1].valores == ()


def test_itera_registros_rechaza_la_cola_que_no_cuadra():
    """4 B de mas al final de un registro: error, no un valor suelto."""
    registro = bytearray(_registro([(5, 0xAAAA, (1,))], ident=1, tipo=1, cola=b"\x00" * 4))
    blob = _dok([bytes(registro)])
    with pytest.raises(cruce.CruceError, match="sin cuadrar"):
        list(cruce.itera_registros(blob))


def test_itera_registros_rechaza_el_recuento_declarado():
    blob = bytearray(_dok([_registro([(5, 0xAAAA, (1,))], ident=1, tipo=1)]))
    struct.pack_into("<I", blob, 16, 2)  # declara 2 registros y hay 1
    with pytest.raises(cruce.CruceError, match="declara"):
        list(cruce.itera_registros(bytes(blob)))


def test_lee_root_rdb_no_se_traga_un_indice_que_no_cuadra(tmp_path):
    """60.722 entradas declaradas y una cabecera que no es `IDRK0000`: error, no silencio."""
    cabecera = struct.pack("<8sIII", b"_DRK0000", 32, 24, 3)
    entrada = struct.pack("<8sIII", b"IDRK0000", 32, 0, 0)
    ruta = tmp_path / "root.rdb"
    ruta.write_bytes(cabecera + entrada + b"\x00" * 32)
    with pytest.raises(cruce.CruceError):
        cruce.lee_root_rdb(str(ruta))

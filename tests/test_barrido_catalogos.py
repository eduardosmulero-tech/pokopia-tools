"""Barrido de catalogo: hash KT, deteccion de tramos y prueba de hashes.

Todo sintetico: aqui no se lee el dump ni se copia contenido del juego. Lo que
fijan las pruebas es el criterio de la tarjeta (cadenas NUL-separadas, 20
seguidas, 90 % de hashes presentes) y las dos trampas que costaron medidas:

* un tramo de 19 cadenas **no** es tabla, y uno de 20 si (el limite se prueba en
  los dos lados);
* la prueba de hashes es la que distingue una tabla de una lista de nombres:
  sin los hashes en el blob, el mismo tramo no pasa.

Y las dos implementaciones de la busqueda de hashes (`find` y `scan`) tienen que
dar el mismo conjunto: la suite lo comprueba aqui, y el barrido real se lanzo con
las dos para contrastar.
"""

from __future__ import annotations

import os
import struct
import sys
import types

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERRAMIENTA = os.path.join(RAIZ, "tools", "barrido_catalogos.py")
if not os.path.isfile(HERRAMIENTA):
    pytest.skip(
        "tools/ no viaja en la release: el barrido de catalogo vive en tools/",
        allow_module_level=True,
    )
if os.path.join(RAIZ, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(RAIZ, "tools"))

import barrido_catalogos as bc  # noqa: E402


# ---------------------------------------------------------------------------
# Utilidades de construccion
# ---------------------------------------------------------------------------

def nombres(n: int, prefijo: str = "BP") -> list[str]:
    """Nombres sinteticos con el formato del catalogo, no del juego."""
    return ["%s%05d_A00_PIEZA%02d_00_00" % (prefijo, i, i) for i in range(n)]


def blob_con(lista: list[str], *, con_hashes: bool = True,
             basura: bytes = b"\x00\x01\x02\x03" * 4) -> bytes:
    """Un blob con las cadenas NUL-separadas y, opcionalmente, sus hashes."""
    cuerpo = b"\x00".join(c.encode("ascii") for c in lista) + b"\x00"
    if con_hashes:
        cola = b"".join(struct.pack("<I", bc.kt_hash(c)) for c in lista)
    else:
        cola = b"\xaa\xbb\xcc\xdd" * len(lista)
    return b"_DOK0000" + basura + cuerpo + b"\x00" + basura + cola + b"\x00" * 8


def entrada(offset: int = 0x1000, name_hash: int = 0xDEADBEEF):
    return types.SimpleNamespace(offset=offset, name_hash=name_hash)


# ---------------------------------------------------------------------------
# El hash del motor
# ---------------------------------------------------------------------------

def test_kt_hash_reproduce_los_valores_medidos():
    """Tres valores verificados contra el dump y contra el ejecutable."""
    assert bc.kt_hash("CharacterEditor.shader.kidssingletondb") == 0x718CCB8B
    assert bc.kt_hash("system.rdb.name") == 0x0A603D98
    assert bc.kt_hash("MO_Versatile.kidssingletondb") == 0x8B081C30


def test_kt_hash_de_cadena_vacia_es_error():
    with pytest.raises(ValueError):
        bc.kt_hash("")


# ---------------------------------------------------------------------------
# Deteccion de tramos
# ---------------------------------------------------------------------------

def test_encuentra_el_tramo_y_su_offset():
    lista = nombres(25)
    blob = blob_con(lista)
    tramos = list(bc.iter_tramos(blob, 6, 48, 20))
    assert len(tramos) == 1
    assert tramos[0].cadenas == tuple(lista)
    assert blob[tramos[0].offset:tramos[0].offset + 5] == lista[0][:5].encode()


def test_diecinueve_cadenas_no_son_tabla_y_veinte_si():
    assert list(bc.iter_tramos(blob_con(nombres(19)), 6, 48, 20)) == []
    assert len(list(bc.iter_tramos(blob_con(nombres(20)), 6, 48, 20))) == 1


def test_un_byte_no_imprimible_parte_el_tramo():
    """Dos bloques de 15 con un separador sucio: ni uno llega a 20."""
    lista = nombres(30)
    cuerpo = (b"\x00".join(c.encode() for c in lista[:15]) + b"\x00"
              + b"\x00\x07\x00"
              + b"\x00".join(c.encode() for c in lista[15:]) + b"\x00")
    blob = b"_DOK0000" + b"\x00\x01" * 4 + cuerpo + b"\x00" * 16
    assert list(bc.iter_tramos(blob, 6, 48, 20)) == []


def test_las_cadenas_cortas_no_entran():
    """Cadenas de 5 caracteres quedan fuera del criterio de longitud."""
    cortas = ["A%04d" % i for i in range(30)]
    assert list(bc.iter_tramos(blob_con(cortas), 6, 48, 20)) == []


# ---------------------------------------------------------------------------
# La prueba de hashes
# ---------------------------------------------------------------------------

def test_los_dos_backends_dan_el_mismo_conjunto():
    lista = nombres(24)
    blob = blob_con(lista)
    pedidos = {bc.kt_hash(c) for c in lista}
    pedidos.add(0x12345678)  # no esta en el blob
    por_find, usado_find = bc.hashes_presentes(blob, set(pedidos), "find")
    por_scan, usado_scan = bc.hashes_presentes(blob, set(pedidos), "scan")
    assert usado_find == "find" and usado_scan == "scan"
    assert por_find == por_scan == {bc.kt_hash(c) for c in lista}


def test_auto_elige_backend_y_responde_igual():
    blob = blob_con(nombres(20))
    pedidos = {bc.kt_hash(c) for c in nombres(20)}
    encontrados, backend = bc.hashes_presentes(blob, pedidos, "auto")
    assert backend in ("find", "scan")
    assert encontrados == pedidos


def test_sin_los_hashes_la_tabla_no_pasa():
    lista = nombres(24)
    con, sin = blob_con(lista), blob_con(lista, con_hashes=False)
    tablas_con = list(bc._tablas_del_blob("x.fdata", entrada(), con, 6, 48, 20,
                                          0.90, "auto", bc.Counter()))
    tablas_sin = list(bc._tablas_del_blob("x.fdata", entrada(), sin, 6, 48, 20,
                                          0.90, "auto", bc.Counter()))
    assert len(tablas_con) == len(tablas_sin) == 1
    assert tablas_con[0].pasa(0.90) and tablas_con[0].verificadas == 24
    assert not tablas_sin[0].pasa(0.90) and tablas_sin[0].verificadas == 0


def test_el_umbral_es_el_de_la_tarjeta():
    """18 de 20 es justo el 90 % y pasa; 17 de 20 (85 %) no pasa."""
    lista = nombres(20)
    cuerpo = b"\x00".join(c.encode() for c in lista) + b"\x00"
    hashes = [struct.pack("<I", bc.kt_hash(c)) for c in lista]
    for presentes, esperado in ((18, True), (17, False)):
        cola = b"".join(hashes[:presentes]) + b"\xee\xee\xee\xee" * 20
        # Los bytes no imprimibles entre el tramo y los hashes impiden que un
        # hash que empiece por ASCII se enganche al tramo como una cadena mas.
        blob = (b"_DOK0000" + b"\x00\x01" * 4 + cuerpo + b"\x00"
                + b"\x00\x01" * 4 + cola + b"\x00" * 8)
        tabla = next(bc._tablas_del_blob("x.fdata", entrada(), blob, 6, 48, 20,
                                         0.90, "auto", bc.Counter()))
        assert tabla.verificadas == presentes
        assert tabla.pasa(0.90) is esperado


# ---------------------------------------------------------------------------
# Prefijos y formato de catalogo
# ---------------------------------------------------------------------------

def test_analiza_prefijos_separa_categorias_y_formato():
    lista = nombres(3, "BP") + nombres(2, "PM") + ["PC_HAIR_0000"]
    datos = bc.analiza_prefijos(tuple(lista))
    assert datos["prefijos2"]["BP"] == 3
    assert datos["prefijos2"]["PM"] == 2
    assert datos["prefijos2"]["PC"] == 1
    assert datos["catalogo_formato"] == 5  # PC_HAIR_0000 no tiene el formato
    assert datos["catalogo_subcadena"] == 5


def test_formato_de_catalogo_cuenta_campo_y_subcadena_por_separado():
    """La tabla buena tiene un nombre pegado a dos bytes: cuentan distinto."""
    limpio = nombres(2)
    pegado = ["kH" + limpio[0]]
    datos = bc.analiza_prefijos(tuple(limpio + pegado))
    assert datos["catalogo_formato"] == 2
    assert datos["catalogo_subcadena"] == 3


# ---------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------

def _resultado(tablas):
    return types.SimpleNamespace(tablas=tablas)


def test_control_positivo_exige_las_2043_cadenas_de_catalogo():
    def tabla(subcadena, offset=bc.CONTROL_POSITIVO_ENTRADA):
        return types.SimpleNamespace(
            fichero=os.path.join("motor_asset_re", "KIDS_PLATFORM_OUNCE",
                                 bc.CONTROL_POSITIVO_FICHERO),
            entrada_offset=offset, tabla_offset=0x69D9, cadenas=("x",) * 2064,
            verificadas=2063, pct=100.0 * 2063 / 2064,
            catalogo_formato=subcadena - 1, catalogo_subcadena=subcadena)

    assert bc.control_positivo(_resultado([tabla(2043)]))["ok"] is True
    fallo = bc.control_positivo(_resultado([tabla(2042)]))
    assert fallo["ok"] is False and "2043" in fallo["motivo"]
    assert bc.control_positivo(_resultado([]))["ok"] is False
    # Una tabla de catalogo en OTRA entrada no vale como control positivo.
    assert bc.control_positivo(_resultado([tabla(2043, offset=0x410)]))["ok"] is False


def test_cli_falla_con_romfs_inexistente(tmp_path):
    codigo = bc.main(["--romfs", str(tmp_path / "no-existe"),
                      "--out", str(tmp_path / "salida.json")])
    assert codigo == 2
    assert not (tmp_path / "salida.json").exists()


def test_cli_rechaza_umbral_fuera_de_rango(tmp_path):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    assert bc.main(["--romfs", str(romfs), "--out", str(tmp_path / "x.json"),
                    "--umbral", "1.5"]) == 2

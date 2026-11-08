"""Catalogo de entidades: lectura, verificacion y CLI. Sin dump salvo donde se dice.

Todo lo sintetico se construye aqui byte a byte con el mismo formato que el
`.fdata` medido (`PDRK0000` / `_DOK0000` / `IDOK0000`), de modo que la suite
corre sin el dump y sin material de terceros. Los tres casos que fijan el
contrato son:

* el hash: vectores tomados del **array del propio motor**, no de mi calculo;
* el recuento: un catalogo mutilado tiene que **fallar**, no avisar;
* la CLI: `list` imprime una linea por entidad y el reparto va a stderr.

Al final, un punado de pruebas contra el dump real que se saltan con motivo si
no esta (`PKP_ROMFS`).
"""

from __future__ import annotations

import json
import os
import struct
import zlib

import pytest

from pokopia import catalog, fdata, paths
from pokopia.cli import main

#: Vectores medidos en el array de hashes del propio motor (`+0x26B` del registro),
#: es decir: los calcula el juego, no este modulo. Las cadenas que aparecen aquí son
#: las que cita la tarjeta `t_8d07080d` en sus criterios, salvo
#: `AP00000_GURUGURUMEGANE_00_00`, que se queda porque es el único vector externo
#: (sacado de ese array y no de este código) y hace falta para que la prueba no sea
#: circular: sin un nombre real no hay vector. Ver
#: `docs/NORMA-CONTENIDO-Y-PUBLICACION.md` §1 y `docs/CATALOGO-Y-SAVE.md` (nota de norma).
VECTORES = {
    "BP00006_A01_TSUTA00_00": 0x6E680230,
    "PM00006_RIZADON_00_00": 0x80606821,
    "BI00060_NENDO00_00": 0x7209A9D9,
    "BI00063_RENGA00_00": 0xEC3B01C3,
    "BP02249_A00_CONCRETE_MIXER00_00": 0x9DA31EC6,
    "BP02588_A06_APPLE_MIXER00_00": 0x738E00CD,
    "BP02625_A07_MIXER00_00": 0xF1A56083,
    "AP00000_GURUGURUMEGANE_00_00": 0xE8E66689,
}


# ---------------------------------------------------------------------------
# Construccion de un `.fdata` con el catalogo dentro
# ---------------------------------------------------------------------------

def nombres_sinteticos(cuantos: int = catalog.EXPECTED_NAMES,
                       prefijos: dict[str, int] | None = None) -> list[str]:
    """Nombres con el formato del catalogo, unicos y con el reparto pedido."""
    if prefijos is None:
        prefijos = {"BP": cuantos}
    salida: list[str] = []
    for prefijo, n in prefijos.items():
        for i in range(n):
            salida.append("%s%05d_A00_TEST_%02d_00" % (prefijo, i, i % 10))
    if len(set(salida)) != len(salida):
        raise AssertionError("los nombres sinteticos no son unicos")
    return salida


def registro_dok(nombres: list[str], *, con_hashes: bool = True) -> bytes:
    """Un contenedor `_DOK0000` con un solo registro `IDOK` y la tabla dentro."""
    cola = b"".join(nombre.encode("ascii") + b"\x00" for nombre in nombres)
    if con_hashes:
        cola += b"".join(struct.pack("<I", catalog.kt_hash(n)) for n in nombres)
    cuerpo = b"\x00\x00\x00\x00" + cola
    tam = 0x18 + len(cuerpo)
    registro = b"IDOK0000" + struct.pack("<4I", tam, 0, 0xDAC911D7, 0) + cuerpo
    cabecera = b"_DOK0000" + struct.pack("<5I", 0x1C, 0x18, 1, 0, 0)
    return cabecera + registro


def escribir_catalogo(romfs: str, nombres: list[str], *, con_hashes: bool = True) -> str:
    """Romfs minimo con el `.fdata` del catalogo, alineado como el de verdad."""
    destino = os.path.join(romfs, catalog.CATALOG_FDATA)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    payload = registro_dok(nombres, con_hashes=con_hashes)
    comprimido = zlib.compress(payload)
    if len(comprimido) < len(payload):
        datos = struct.pack("<HQ", len(comprimido), 0) + comprimido
    else:  # un payload diminuto puede crecer al comprimir: se guarda crudo
        datos = payload
    entry_size = fdata.ENTRY_HEADER_SIZE + len(datos)
    entrada = (fdata.IDRK_MAGIC
               + struct.pack("<3Q", entry_size, len(datos), len(payload))
               + struct.pack("<4I", 0, 0x2943E4DA, 0x20A6A0BB, 0)
               + datos)
    buf = bytearray(fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0))
    buf += entrada
    if len(buf) % fdata.ENTRY_ALIGN:
        buf += b"\x00" * (fdata.ENTRY_ALIGN - len(buf) % fdata.ENTRY_ALIGN)
    with open(destino, "wb") as fh:
        fh.write(bytes(buf))
    return destino


@pytest.fixture(autouse=True)
def _cache_limpia():
    catalog.clear_cache()
    yield
    catalog.clear_cache()


# ---------------------------------------------------------------------------
# El hash
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre,esperado", sorted(VECTORES.items()))
def test_hash_vectores_del_motor(nombre, esperado):
    """Los vectores salen del array de hashes del registro, no de mi calculo."""
    assert catalog.kt_hash(nombre) == esperado
    assert catalog.hash_for(nombre) == esperado


def test_hash_no_acepta_vacio():
    with pytest.raises(catalog.CatalogError):
        catalog.kt_hash("")


def test_hash_distingue_mayusculas_y_sufijos():
    base = catalog.kt_hash("BP00006_A01_TSUTA00_00")
    assert catalog.kt_hash("BP00006_A01_TSUTA00_01") != base
    assert catalog.kt_hash("bp00006_a01_tsuta00_00") != base


# ---------------------------------------------------------------------------
# Lectura del contenedor
# ---------------------------------------------------------------------------

def test_tabla_de_nombres_de_un_registro():
    nombres = ["BP00006_A01_TSUTA00_00", "PM00006_RIZADON_00_00"]
    registro = registro_dok(nombres)
    offset, leidos = catalog.name_table(registro)
    assert leidos == nombres
    assert registro[offset:offset + len(nombres[0])] == nombres[0].encode()


def test_tabla_ignora_nombres_fuera_de_formato():
    """Un nombre con otro formato no entra en la tabla (no casa con el patron)."""
    registro = registro_dok(["PC_PALABRA_0000", "BP00001_A00_TEST00_00", "TEST_CUBE"])
    _offset, leidos = catalog.name_table(registro)
    assert leidos == ["BP00001_A00_TEST00_00"]


def test_dok_rechaza_registro_con_firma_rara():
    roto = bytearray(registro_dok(["BP00001_A00_TEST00_00"]))
    roto[0x1C:0x24] = b"XXXX0000"
    with pytest.raises(catalog.CatalogError, match="IDOK0000"):
        catalog.parse_dok(bytes(roto))


# ---------------------------------------------------------------------------
# El contrato de verificacion (C4: un catalogo mutilado FALLA)
# ---------------------------------------------------------------------------

def test_catalogo_completo_se_lee_y_se_invierte(tmp_path):
    nombres = nombres_sinteticos(prefijos={"BP": 972, "PM": 900, "BI": 87,
                                           "PC": 73, "AP": 11})
    assert len(nombres) == catalog.EXPECTED_NAMES
    escribir_catalogo(str(tmp_path), nombres)

    tabla = catalog.load_catalog(str(tmp_path))
    assert isinstance(tabla, dict)
    assert len(tabla) == catalog.EXPECTED_NAMES
    assert tabla[nombres[0]] == catalog.kt_hash(nombres[0])

    cat = catalog.load(str(tmp_path))
    assert cat.by_prefix == {"BP": 972, "PM": 900, "BI": 87, "PC": 73, "AP": 11}
    assert cat.name_for(cat.hashes[nombres[-1]]) == nombres[-1]
    assert cat.hash_for(nombres[-1]) == cat.hashes[nombres[-1]]


def test_catalogo_mutilado_falla_por_recuento(tmp_path):
    """C4: con 2.042 nombres el modulo no avisa, revienta."""
    nombres = nombres_sinteticos()[:-1]
    assert len(nombres) == catalog.EXPECTED_NAMES - 1
    escribir_catalogo(str(tmp_path), nombres)
    with pytest.raises(catalog.CatalogError) as excinfo:
        catalog.load_catalog(str(tmp_path))
    mensaje = str(excinfo.value)
    assert "2042" in mensaje and "2043" in mensaje


def test_catalogo_sin_los_hashes_falla(tmp_path):
    """El recuento cuadra pero la lista no es la del motor: tambien revienta."""
    escribir_catalogo(str(tmp_path), nombres_sinteticos(), con_hashes=False)
    with pytest.raises(catalog.CatalogError, match="hashes calculados no aparecen"):
        catalog.load_catalog(str(tmp_path))


def test_catalogo_con_repetidos_falla(tmp_path):
    nombres = nombres_sinteticos()
    nombres[-1] = nombres[0]
    escribir_catalogo(str(tmp_path), nombres)
    with pytest.raises(catalog.CatalogError, match="repetidos"):
        catalog.load_catalog(str(tmp_path))


def test_sin_el_fdata_del_catalogo_el_error_lo_dice(tmp_path):
    with pytest.raises(catalog.CatalogError, match="no encuentro el .fdata"):
        catalog.load_catalog(str(tmp_path))


def test_consultas_fuera_del_catalogo_fallan(tmp_path):
    escribir_catalogo(str(tmp_path), nombres_sinteticos())
    cat = catalog.load(str(tmp_path))
    with pytest.raises(catalog.CatalogError, match="fuera del catalogo"):
        cat.hash_for("BP99999_A00_NO_EXISTE_00")
    with pytest.raises(catalog.CatalogError, match="fuera del catalogo"):
        cat.name_for(0xDEADBEEF)


# ---------------------------------------------------------------------------
# La CLI
# ---------------------------------------------------------------------------

def test_list_imprime_una_linea_por_entidad(tmp_path, capsys):
    escribir_catalogo(str(tmp_path), nombres_sinteticos(prefijos={"BP": 2000,
                                                                  "PM": 43}))
    assert main(["catalog", "list", "--container", str(tmp_path)]) == 0
    salida = capsys.readouterr()
    lineas = salida.out.splitlines()
    assert len(lineas) == catalog.EXPECTED_NAMES
    assert lineas[0].startswith("0x")
    assert "2043 entidades" in salida.err and "BP 2000" in salida.err


def test_list_con_prefijo(tmp_path, capsys):
    nombres = nombres_sinteticos(prefijos={"BI": 87, "BP": 1956})
    escribir_catalogo(str(tmp_path), nombres)
    assert main(["catalog", "list", "--prefix", "BI", "--container", str(tmp_path)]) == 0
    salida = capsys.readouterr()
    lineas = salida.out.splitlines()
    assert len(lineas) == 87
    assert all(nombre.split("  ")[1].startswith("BI") for nombre in lineas)


def test_list_json(tmp_path, capsys):
    escribir_catalogo(str(tmp_path), nombres_sinteticos())
    assert main(["catalog", "list", "--container", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["names"] == catalog.EXPECTED_NAMES
    assert doc["count"] == catalog.EXPECTED_NAMES
    assert doc["entries"][0]["hash"].startswith("0x")


def test_find_sin_distinguir_mayusculas(tmp_path, capsys):
    nombres = nombres_sinteticos(prefijos={"BP": catalog.EXPECTED_NAMES})
    nombres[0] = "BP02249_A00_CONCRETE_MIXER00_00"
    nombres[1] = "BP02588_A06_APPLE_MIXER00_00"
    nombres[2] = "BP02625_A07_MIXER00_00"
    escribir_catalogo(str(tmp_path), nombres)
    assert main(["catalog", "find", "Mixer", "--container", str(tmp_path)]) == 0
    salida = capsys.readouterr()
    assert len(salida.out.splitlines()) == 3
    assert "3 de 2043" in salida.err


def test_find_sin_resultados_devuelve_1(tmp_path, capsys):
    escribir_catalogo(str(tmp_path), nombres_sinteticos())
    assert main(["catalog", "find", "no-existe-esto", "--container", str(tmp_path)]) == 1
    assert capsys.readouterr().out == ""


def test_la_cli_del_catalogo_mutilado_sale_con_1(tmp_path, capsys):
    escribir_catalogo(str(tmp_path), nombres_sinteticos()[:100])
    assert main(["catalog", "list", "--container", str(tmp_path)]) == 1
    assert "2043" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# El dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
HAY_DUMP = os.path.isfile(os.path.join(ROMFS, catalog.CATALOG_FDATA))
necesita_dump = pytest.mark.skipif(
    not HAY_DUMP, reason="sin dump del juego (exporta PKP_ROMFS)")


@necesita_dump
def test_el_array_de_hashes_va_en_el_orden_de_la_lista():
    """2062 de 2062: el hash calculado coincide con el que guarda el motor, y en orden.

    Es la prueba externa (el array lo escribio el juego) y la unica que valida el
    algoritmo para **todos** los nombres, no solo para los vectores de arriba.
    """
    cat = catalog.load(ROMFS)
    with open(cat.source, "rb") as fh:
        entry = next(e for e in fdata.iter_entries(cat.source) if e.offset == cat.entry_offset)
        datos = fdata.read_entry(fh, entry)
    _cabecera, registros = catalog.parse_dok(datos)
    registro = registros[cat.record]
    rec = datos[registro.offset:registro.offset + registro.size]

    import re
    patron_extra = re.compile(rb"[A-Z]{2}_[A-Z0-9_]+")
    tokens = [t.decode("ascii") for t in rec[cat.table_offset:].split(b"\x00")
              if catalog.NAME_RE.fullmatch(t) or patron_extra.fullmatch(t)]
    inicio = min(rec.find(struct.pack("<I", cat.hashes[n])) for n in cat.names[:16])
    for i, token in enumerate(tokens):
        assert rec[inicio + 4 * i:inicio + 4 * i + 4] == struct.pack("<I", catalog.kt_hash(token)), \
            "desajuste en el token %d del registro" % i
    assert len(tokens) == 2062


@necesita_dump
def test_catalogo_del_dump_real():
    cat = catalog.load(ROMFS)
    assert len(cat.names) == catalog.EXPECTED_NAMES
    assert cat.by_prefix == catalog.EXPECTED_BY_PREFIX
    assert cat.record == 29
    assert cat.table_offset == 0x42EB
    assert cat.hash_for("BP02249_A00_CONCRETE_MIXER00_00") == 0x9DA31EC6
    assert cat.name_for(0x9DA31EC6) == "BP02249_A00_CONCRETE_MIXER00_00"


@necesita_dump
def test_cli_del_dump_real(capsys):
    assert main(["catalog", "list", "--container", ROMFS]) == 0
    lineas = capsys.readouterr().out.splitlines()
    assert len(lineas) == catalog.EXPECTED_NAMES
    assert main(["catalog", "list", "--prefix", "BI", "--container", ROMFS]) == 0
    texto = capsys.readouterr().out
    assert "BI00060_NENDO00_00" in texto and "BI00063_RENGA00_00" in texto
    assert main(["catalog", "find", "mixer", "--container", ROMFS]) == 0
    salida = capsys.readouterr().out
    for nombre in ("BP02249_A00_CONCRETE_MIXER00_00", "BP02588_A06_APPLE_MIXER00_00",
                   "BP02625_A07_MIXER00_00"):
        assert nombre in salida
    assert len(salida.splitlines()) == 3

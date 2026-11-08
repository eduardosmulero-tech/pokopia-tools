"""`.fdata` (PDRK/IDRK): listar, contar y extraer. Todo con ficheros sinteticos.

Ningun fixture del juego: cada `.fdata` de estas pruebas se construye aqui byte a
byte con el mismo formato que el dump, para que la suite corra sin el dump y sin
material de terceros. Los tres casos que importan son los que costaron horas en
la medicion:

* el modo normal de trozos (`<H` + 8 B de relleno) y el modo FETH (`<I`);
* los tres tamanos de la cabecera son `u64` — una entrada de mas de 4 GiB lo fija;
* `extract` nombra `<name_hash>.<tipo>` y nunca escribe dentro del romfs.

Y un par de pruebas contra el dump real, que se saltan con motivo si no esta.
"""

from __future__ import annotations

import json
import os
import struct
import zlib

import pytest

from pokopia import fdata, paths
from pokopia.cli import main

KSCL = 0x5599AA51
G1T = 0xAFBEC60C
KIDSOBJDB = 0x20A6A0BB
DESCONOCIDO = 0xDEADBEEF


# ---------------------------------------------------------------------------
# Construccion del .fdata sintetico
# ---------------------------------------------------------------------------

def trocear(payload: bytes, *, feth: bool = False, tam: int = 0x4000) -> bytes:
    """Payload troceado como lo guarda el juego: [tamano][zlib] por trozo."""
    salida = bytearray()
    for inicio in range(0, len(payload), tam):
        comprimido = zlib.compress(payload[inicio:inicio + tam])
        if feth:
            salida += struct.pack("<I", len(comprimido))
        else:
            salida += struct.pack("<HQ", len(comprimido), 0)
        salida += comprimido
    return bytes(salida)


def entrada(payload: bytes, *, ktid: int = KSCL, name_hash: int = 0x11223344,
            flags: int = 0, entry_type: int = 0, metadata: bytes = b"",
            crudo: bool = False, tam: int = 0x4000) -> bytes:
    """Una entrada IDRK completa: cabecera de 48 B + metadata + datos."""
    if crudo:
        datos = payload
    else:
        datos = trocear(payload, feth=bool(flags & fdata.FETH_FLAG), tam=tam)
    entry_size = fdata.ENTRY_HEADER_SIZE + len(metadata) + len(datos)
    return (
        fdata.IDRK_MAGIC
        + struct.pack("<3Q", entry_size, len(datos), len(payload))
        + struct.pack("<4I", entry_type, name_hash, ktid, flags)
        + metadata
        + datos)


def escribir_fdata(ruta, entradas, *, cabecera: bytes | None = None) -> str:
    """Contenedor PDRK con las entradas dadas, cada una alineada a 16 B."""
    if cabecera is None:
        cabecera = fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0)
    buf = bytearray(cabecera)
    for blob in entradas:
        buf += blob
        if len(buf) % fdata.ENTRY_ALIGN:
            buf += b"\x00" * (fdata.ENTRY_ALIGN - len(buf) % fdata.ENTRY_ALIGN)
    with open(ruta, "wb") as fh:
        fh.write(bytes(buf))
    return str(ruta)


# ---------------------------------------------------------------------------
# Constructor: cabeceras, offsets y tipos
# ---------------------------------------------------------------------------

def test_lista_offset_tipo_y_tamanos(tmp_path, capsys):
    payload = b"LCSK2600" + bytes(range(256)) * 40
    ruta = escribir_fdata(tmp_path / "0xdead.beef.fdata", [
        entrada(payload, ktid=KSCL, name_hash=0x0000BEEF),
        entrada(b"textura", ktid=G1T, name_hash=0x0000CAFE, crudo=True),
        entrada(payload[:1000], ktid=KIDSOBJDB, name_hash=0x0000D00D,
                flags=fdata.FETH_FLAG),
    ])

    assert main(["fdata", "list", ruta, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    entradas = doc["files"][0]["entries"]
    assert [e["type"] for e in entradas] == ["kscl", "g1t", "kidsobjdb"]
    assert [e["type_ktid"] for e in entradas] == ["0x5599aa51", "0xafbec60c", "0x20a6a0bb"]
    assert entradas[0]["offset"] == 0x10
    assert entradas[0]["uncompressed_size"] == len(payload)
    assert entradas[1]["compressed_size"] == entradas[1]["uncompressed_size"] == len("textura")
    for anterior, siguiente in zip(entradas, entradas[1:]):
        assert anterior["offset"] % fdata.ENTRY_ALIGN == 0
        assert siguiente["offset"] == fdata.align_up(anterior["offset"] + anterior["entry_size"])

    assert main(["fdata", "list", ruta]) == 0
    texto = capsys.readouterr().out
    assert "0x00000010" in texto and "kscl" in texto and "kidsobjdb" in texto


def test_metadata_queda_entre_cabecera_y_datos(tmp_path):
    """`entry_size - compressed_size - 0x30` es metadata, no datos."""
    ruta = escribir_fdata(tmp_path / "meta.fdata", [
        entrada(b"x" * 100, metadata=b"\xaa" * 8, name_hash=1),
    ])
    (e,) = list(fdata.iter_entries(ruta))
    assert e.metadata_size == 8
    assert e.data_offset == e.offset + 0x30 + 8
    assert fdata.read_entry_from(ruta, e) == b"x" * 100


# ---------------------------------------------------------------------------
# Descompresion: crudo, trozos normales, trozos FETH
# ---------------------------------------------------------------------------

def test_extrae_crudo_comprimido_y_feth(tmp_path):
    grande = bytes((i * 7) % 251 for i in range(3 * 0x4000 + 123))   # 3 trozos
    ruta = escribir_fdata(tmp_path / "mixto.fdata", [
        entrada(b"crudo de verdad", ktid=KSCL, name_hash=0x00000001, crudo=True),
        entrada(grande, ktid=G1T, name_hash=0x00000002),
        entrada(grande, ktid=KIDSOBJDB, name_hash=0x00000003, flags=fdata.FETH_FLAG),
    ])

    escritos = fdata.extract(ruta, G1T, str(tmp_path / "out"))
    assert len(escritos) == 1
    _entrada, destino = escritos[0]
    assert os.path.basename(destino) == "0x00000002.g1t"
    assert os.path.join(str(tmp_path / "out"), "0x00000002.g1t") == destino
    with open(destino, "rb") as fh:
        assert fh.read() == grande

    # el mismo payload en modo FETH: mismo resultado, 6 B menos por trozo
    assert fdata.read_entry_from(ruta, list(fdata.iter_entries(ruta))[0]) == b"crudo de verdad"
    crudo_u16 = fdata.read_entry_from(ruta, list(fdata.iter_entries(ruta))[1])
    crudo_feth = fdata.read_entry_from(ruta, list(fdata.iter_entries(ruta))[2])
    assert crudo_u16 == crudo_feth == grande

    entradas = list(fdata.iter_entries(ruta))
    trozos = len(range(0, len(grande), 0x4000))
    assert entradas[2].chunk_header_size == 4
    assert entradas[1].chunk_header_size == 10
    assert entradas[1].compressed_size - entradas[2].compressed_size == 6 * trozos


def test_los_tres_tamanos_son_u64(tmp_path):
    """La trampa que costo una hora: si se leen como u32, todo deja de cuadrar.

    No se puede tener un fichero de 4 GiB en la suite, asi que la entrada se
    declara por campos: solo la cabecera de 48 B esta en disco y el lector tiene
    que devolver los valores exactos y negarse a leer datos que no estan.
    """
    entry_size = 0x100000030        # 4 GiB + 48, con la parte alta encendida
    comprimido = 0x0000000080000000
    sin_comprimir = 0x100000000     # 4 GiB

    cabecera = fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0)
    blob = (fdata.IDRK_MAGIC
            + struct.pack("<3Q", entry_size, comprimido, sin_comprimir)
            + struct.pack("<4I", 0, 0xABCDEF01, G1T, 0))
    ruta = tmp_path / "enorme.fdata"
    ruta.write_bytes(cabecera + blob)

    (e,) = list(fdata.iter_entries(str(ruta)))
    assert e.entry_size == entry_size
    assert e.compressed_size == comprimido
    assert e.uncompressed_size == sin_comprimir
    assert e.end_offset == fdata.align_up(0x10 + entry_size)

    # lectura como u32 (el error): "entry_size 48" parece razonable y no lo es
    como_u32 = struct.unpack_from("<8s6I", blob)
    assert como_u32[1] == 0x30, "el error u32 ve entry_size 48 y se lo cree"
    assert como_u32[1] != e.entry_size

    # y el lector no intenta leer 4 GiB que no existen: error claro, no cuelgue
    with pytest.raises(fdata.FdataTruncatedError):
        fdata.read_entry_from(str(ruta), e)


# ---------------------------------------------------------------------------
# stat: recuento por tipo
# ---------------------------------------------------------------------------

def test_stat_agrega_por_tipo_y_baja_a_las_subcarpetas(tmp_path, capsys):
    raiz = tmp_path / "romfs"
    (raiz / "motor_asset_re" / "MountPoint_1").mkdir(parents=True)
    contenido = b"datos" * 100
    escribir_fdata(raiz / "motor_asset_re" / "a.fdata", [
        entrada(contenido, ktid=KSCL, name_hash=1),
        entrada(contenido, ktid=KSCL, name_hash=2),
        entrada(contenido, ktid=G1T, name_hash=3, crudo=True),
    ])
    escribir_fdata(raiz / "motor_asset_re" / "MountPoint_1" / "b.fdata", [
        entrada(contenido, ktid=KIDSOBJDB, name_hash=4),
        entrada(b"raro", ktid=DESCONOCIDO, name_hash=5),
    ])
    (raiz / "notas.txt").write_text("no es un fdata")

    assert main(["fdata", "stat", str(raiz), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["files"] == 2
    assert doc["entries"] == 5
    tipos = {t["type"]: t for t in doc["types"]}
    assert tipos["kscl"]["entries"] == 2
    assert tipos["g1t"]["compressed"] == 0          # va crudo
    assert tipos["kidsobjdb"]["compressed"] == 1
    assert any(t["type_ktid"] == "0xdeadbeef" for t in doc["types"])

    assert main(["fdata", "stat", str(raiz)]) == 0
    texto = capsys.readouterr().out
    assert "entradas  : 5" in texto and "0xdeadbeef" in texto


def test_stat_sin_fdata_es_un_error_con_mensaje(tmp_path, capsys):
    assert main(["fdata", "stat", str(tmp_path)]) == 1
    assert "no hay ningun .fdata" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# extract: nombres, guardas de escritura y errores
# ---------------------------------------------------------------------------

def test_extract_nombra_hash_y_tipo_y_filtra(tmp_path):
    ruta = escribir_fdata(tmp_path / "tres.fdata", [
        entrada(b"uno", ktid=KIDSOBJDB, name_hash=0x0000BEEF),
        entrada(b"dos", ktid=G1T, name_hash=0x0000CAFE),
        entrada(b"tres", ktid=KIDSOBJDB, name_hash=0x0000D00D),
    ])
    salida = tmp_path / "out"
    assert main(["fdata", "extract", ruta, "--type", "kidsobjdb", "--out", str(salida)]) == 0
    assert sorted(os.listdir(str(salida))) == ["0x0000beef.kidsobjdb", "0x0000d00d.kidsobjdb"]
    with open(str(salida / "0x0000beef.kidsobjdb"), "rb") as fh:
        assert fh.read() == b"uno"


def test_extract_no_pisa_una_entrada_con_el_mismo_hash(tmp_path, capsys):
    """Dos entradas del mismo tipo con el mismo hash pisan el mismo nombre."""
    ruta = escribir_fdata(tmp_path / "repes.fdata", [
        entrada(b"uno", ktid=KSCL, name_hash=0x0000BEEF),
        entrada(b"dos", ktid=KSCL, name_hash=0x0000BEEF),
    ])
    assert main(["fdata", "extract", ruta, "--type", "kscl",
                 "--out", str(tmp_path / "out")]) == 1
    assert "se pisaria" in capsys.readouterr().err


def test_extract_en_el_romfs_esta_prohibido(tmp_path, monkeypatch, capsys):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    ruta = escribir_fdata(tmp_path / "x.fdata", [entrada(b"uno", name_hash=1)])
    monkeypatch.setenv("PKP_ROMFS", str(romfs))

    assert main(["fdata", "extract", ruta, "--type", "kscl",
                 "--out", str(romfs / "salida")]) == 2
    assert "destino protegido" in capsys.readouterr().err
    assert not (romfs / "salida").exists()


def test_tipo_desconocido_y_firma_mala(tmp_path, capsys):
    ruta = escribir_fdata(tmp_path / "x.fdata", [entrada(b"uno", name_hash=1)])
    assert main(["fdata", "extract", ruta, "--type", "noexiste", "--out", str(tmp_path)]) == 1
    assert "tipo desconocido" in capsys.readouterr().err

    assert fdata.parse_type("0x20a6a0bb") == KIDSOBJDB
    assert fdata.parse_type("KIDSOBJDB") == KIDSOBJDB
    assert fdata.type_name(DESCONOCIDO) == "0xdeadbeef"

    malo = tmp_path / "malo.fdata"
    malo.write_bytes(b"NOPE0000" + b"\x00" * 32)
    assert main(["fdata", "list", str(malo)]) == 1
    assert "PDRK0000" in capsys.readouterr().err


def test_entrada_cortada_no_se_lee_a_medias(tmp_path):
    """Si el payload comprimido no esta entero, error; nunca datos a medias."""
    datos = entrada(os.urandom(500), name_hash=1)
    assert len(datos) > 96
    ruta = tmp_path / "cortado.fdata"
    ruta.write_bytes(
        fdata.PDRK_MAGIC + struct.pack("<2I", 0x10, 0) + datos[:80])
    (e,) = list(fdata.iter_entries(str(ruta)))
    with pytest.raises(fdata.FdataTruncatedError):
        fdata.read_entry_from(str(ruta), e)


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
def test_stat_del_romfs_real(tmp_path, capsys):
    assert main(["fdata", "stat", ROMFS, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["entries"] == 79710
    tipos = {t["type"]: t["entries"] for t in doc["types"]}
    assert tipos["g1s"] == 26137
    assert tipos["g1a"] == 17457
    assert tipos["g1t"] == 14412
    assert tipos["kidsobjdb"] == 4144
    assert tipos["kscl"] == 361
    assert doc["files"] == 24


@necesita_dump
def test_extract_de_un_kidsobjdb_del_romfs_real(tmp_path):
    """El criterio de parada: lo extraido empieza por `_DOK0000`."""
    from pokopia import fdata as mod

    ruta = ""
    for candidato in mod.find_fdata(ROMFS):
        if any(e.type_ktid == KIDSOBJDB for e in mod.iter_entries(candidato)):
            if os.path.getsize(candidato) < 2 * 1024 * 1024:
                ruta = candidato
                break
    if not ruta:
        pytest.skip("ningun .fdata pequeno con kidsobjdb en este dump")

    escritos = mod.extract(ruta, KIDSOBJDB, str(tmp_path / "out"))
    assert escritos, "el .fdata elegido no tiene kidsobjdb"
    for _entrada, destino in escritos:
        with open(destino, "rb") as fh:
            assert fh.read(8) == b"_DOK0000"

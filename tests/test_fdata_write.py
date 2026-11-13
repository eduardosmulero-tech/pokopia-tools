"""Escritura minima de `.fdata`: `write_entry`, `repack` e `inject`.

Todo con ficheros sinteticos; ningun byte del juego. Los casos que importan:

* la entrada cruda (los dos tamanos iguales) y la comprimida-preservada;
* los metadatos opacos de 40 B tienen que sobrevivir a la escritura;
* la alineacion a 16 B cuando el bloque nuevo no es multiplo de 16;
* el fichero del juego **acaba en el `entry_size` de su ultima entrada** (no
  lleva el relleno final): el repack tiene que reproducirlo byte a byte;
* `--route slot` no escribe: o dice que no cabe, o dice que no esta resuelto.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib

import pytest

from pokopia import fdata
from pokopia.cli import main
from tests.test_fdata import entrada, trocear

G1T = 0xAFBEC60C
KSCL = 0x5599AA51
HASH = 0xCA806E59


def contenedor(ruta, entradas, *, relleno_final: bool = True) -> str:
    """Como `escribir_fdata`, pero sin el relleno de la ultima si se pide."""
    buf = bytearray(fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0))
    for i, blob in enumerate(entradas):
        buf += blob
        ultima = i == len(entradas) - 1
        if ultima and not relleno_final:
            continue
        if len(buf) % fdata.ENTRY_ALIGN:
            buf += b"\x00" * (fdata.ENTRY_ALIGN - len(buf) % fdata.ENTRY_ALIGN)
    with open(ruta, "wb") as fh:
        fh.write(bytes(buf))
    return str(ruta)


def leer_todo(ruta: str) -> list[tuple[int, bytes]]:
    with open(ruta, "rb") as fh:
        return [(e.name_hash, fdata.read_entry(fh, e)) for e in fdata.iter_entries(ruta)]


# ---------------------------------------------------------------------------
# write_entry
# ---------------------------------------------------------------------------

def test_write_entry_cruda_declara_los_dos_tamanos_iguales():
    payload = bytes(range(256)) * 4
    blob = fdata.write_entry(payload, name_hash=HASH, type_ktid=G1T,
                             entry_type=8, flags=0x400000)
    magic, entry_size, cmp_, unc, tipo, nh, ktid, flags = fdata.ENTRY_HEADER.unpack_from(blob)
    assert magic == fdata.IDRK_MAGIC
    assert entry_size == len(blob) == 0x30 + len(payload)
    assert cmp_ == unc == len(payload)
    assert (tipo, nh, ktid, flags) == (8, HASH, G1T, 0x400000)


def test_write_entry_con_40_bytes_de_metadatos(tmp_path):
    """Los metadatos opacos van entre la cabecera y los datos: 40 B, tal cual."""
    payload = b"GT1G" + bytes(range(200))
    metadata = bytes(range(0xA0, 0xA0 + 40))
    ruta = contenedor(tmp_path / "meta.fdata", [
        fdata.write_entry(payload, metadata=metadata, name_hash=HASH, type_ktid=G1T),
    ])
    (e,) = list(fdata.iter_entries(ruta))
    assert e.metadata_size == 40
    assert e.entry_size == 0x30 + 40 + len(payload)
    assert e.data_offset == e.offset + 0x30 + 40
    assert fdata.entry_metadata(ruta, e) == metadata
    assert fdata.read_entry_from(ruta, e) == payload


def test_write_entry_comprimida_preservada_no_retrocea(tmp_path):
    """`stored=` guarda los trozos ya comprimidos y declara los crudos."""
    payload = bytes((i * 13) % 251 for i in range(3 * 0x4000 + 7))
    trozos = trocear(payload)
    blob = fdata.write_entry(payload, stored=trozos, name_hash=HASH, type_ktid=KSCL)
    ruta = contenedor(tmp_path / "comprimida.fdata", [blob])
    (e,) = list(fdata.iter_entries(ruta))
    assert e.is_compressed
    assert e.compressed_size == len(trozos)
    assert e.uncompressed_size == len(payload)
    assert fdata.read_entry_from(ruta, e) == payload


def test_write_entry_comprimida_del_mismo_tamano_es_un_error():
    """Si comprimido == crudo el lector lo tomaria por crudo: se rechaza."""
    with pytest.raises(fdata.FdataWriteError):
        fdata.write_entry(b"x" * 100, stored=b"y" * 100)


def test_write_entry_vacia_y_campos_fuera_de_u32():
    with pytest.raises(fdata.FdataWriteError):
        fdata.write_entry(b"")
    with pytest.raises(fdata.FdataWriteError):
        fdata.write_entry(b"x", flags=0x1_0000_0000)


# ---------------------------------------------------------------------------
# repack
# ---------------------------------------------------------------------------

def _tres_entradas() -> list[bytes]:
    return [
        fdata.write_entry(b"crudo de verdad", metadata=b"\xaa" * 8,
                          name_hash=0x00000001, type_ktid=KSCL),
        fdata.write_entry(b"GT1G" + b"\x11" * 500, metadata=b"\xbb" * 40,
                          name_hash=HASH, type_ktid=G1T, entry_type=8,
                          flags=0x400000),
        fdata.write_entry(bytes((i * 7) % 251 for i in range(0x4000 + 33)),
                          name_hash=0x00000003, type_ktid=KSCL, stored=None),
    ]


@pytest.mark.parametrize("relleno_final", [True, False])
def test_repack_neutro_es_identico_byte_a_byte(tmp_path, relleno_final):
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas(),
                        relleno_final=relleno_final)
    antes = open(origen, "rb").read()
    destino = tmp_path / "copia.fdata"
    resultado = fdata.repack(origen, str(destino))
    despues = open(destino, "rb").read()
    assert despues == antes
    assert resultado.size == len(antes)
    assert resultado.entries == 3
    assert resultado.replaced == ()
    assert resultado.sha256 == hashlib.sha256(antes).hexdigest()


def test_repack_alinea_cuando_el_bloque_no_es_multiplo_de_16(tmp_path):
    """Un payload de 30 B deja la entrada en 0x30+30 = 78 B: hay que rellenar."""
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas(),
                        relleno_final=False)
    nuevo = fdata.write_entry(b"N" * 30, name_hash=HASH, type_ktid=G1T)
    assert len(nuevo) % 16
    destino = tmp_path / "copia.fdata"
    resultado = fdata.repack(origen, str(destino), {HASH: nuevo})

    entradas = list(fdata.iter_entries(str(destino)))
    assert [e.name_hash for e in entradas] == [0x00000001, HASH, 0x00000003]
    for e in entradas:
        assert e.offset % fdata.ENTRY_ALIGN == 0
    # la siguiente empieza donde acaba el relleno de la tocada
    assert entradas[2].offset == fdata.align_up(entradas[1].offset + entradas[1].entry_size)
    # relleno a cero entre las dos
    with open(destino, "rb") as fh:
        fh.seek(entradas[1].offset + entradas[1].entry_size)
        relleno = fh.read(entradas[2].offset - entradas[1].offset - entradas[1].entry_size)
    assert relleno == b"\x00" * len(relleno) and relleno

    # el tamano declarado del fichero cuadra con las entradas + alineaciones
    total = os.path.getsize(str(destino))
    assert total == entradas[-1].offset + entradas[-1].entry_size
    assert fdata.read_entry_from(str(destino), entradas[1]) == b"N" * 30
    assert resultado.replaced == (HASH,)


def test_repack_no_toca_las_entradas_no_reemplazadas(tmp_path):
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas(),
                        relleno_final=False)
    antes = leer_todo(origen)
    destino = tmp_path / "copia.fdata"
    fdata.repack(origen, str(destino),
                 {HASH: fdata.write_entry(b"GT1G" + b"\x22" * 10, name_hash=HASH,
                                          type_ktid=G1T)})
    despues = leer_todo(str(destino))
    assert [a[0] for a in antes] == [d[0] for d in despues]
    assert antes[0] == despues[0]
    assert antes[2] == despues[2]
    assert despues[1] == (HASH, b"GT1G" + b"\x22" * 10)


def test_repack_se_niega_a_escribir_sobre_el_origen(tmp_path):
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas())
    with pytest.raises(fdata.FdataWriteError):
        fdata.repack(origen, origen)
    assert os.path.getsize(origen) > 0


def test_repack_no_escribe_en_el_romfs(tmp_path, monkeypatch):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas())
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    with pytest.raises(PermissionError):
        fdata.repack(origen, str(romfs / "0xdead.fdata"))
    assert not (romfs / "0xdead.fdata").exists()


def test_repack_rechaza_un_bloque_que_no_es_entrada(tmp_path):
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas())
    with pytest.raises(fdata.FdataWriteError):
        fdata.repack(origen, str(tmp_path / "copia.fdata"), {HASH: b"no soy IDRK"})


def test_repack_rechaza_un_hash_que_no_esta(tmp_path):
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas())
    with pytest.raises(fdata.FdataWriteError):
        fdata.repack(origen, str(tmp_path / "copia.fdata"),
                     {0x12345678: fdata.write_entry(b"x", name_hash=0x12345678)})


# ---------------------------------------------------------------------------
# inject por la CLI
# ---------------------------------------------------------------------------

def _fdata_con_destino(tmp_path) -> str:
    return contenedor(tmp_path / "0x57e5b452.fdata", _tres_entradas(),
                      relleno_final=False)


def test_cli_inject_raw_mete_el_fichero_y_conserva_lo_demas(tmp_path, capsys):
    origen = _fdata_con_destino(tmp_path)
    nuevo = tmp_path / "nuevo.g1t"
    nuevo.write_bytes(b"GT1G" + bytes(range(200)) * 3)
    salida = tmp_path / "copia.fdata"

    assert main(["fdata", "inject", origen, "--name-hash", "0xca806e59",
                 "--file", str(nuevo), "--out", str(salida)]) == 0
    texto = capsys.readouterr().out
    assert "0xca806e59" in texto and "despues" in texto and "crudos" in texto

    antes = leer_todo(origen)
    despues = leer_todo(str(salida))
    assert despues[1] == (HASH, nuevo.read_bytes())
    assert despues[0] == antes[0] and despues[2] == antes[2]

    (e,) = [x for x in fdata.iter_entries(str(salida)) if x.name_hash == HASH]
    assert not e.is_compressed
    assert e.metadata_size == 40                      # los del original
    assert e.entry_type == 8 and e.type_ktid == G1T   # los del original
    assert e.flags == 0x400000                        # los del original


def test_cli_inject_json_y_flags_forzados(tmp_path, capsys):
    origen = _fdata_con_destino(tmp_path)
    nuevo = tmp_path / "nuevo.g1t"
    nuevo.write_bytes(b"GT1G" + b"\x00" * 64)
    salida = tmp_path / "copia.fdata"
    assert main(["fdata", "inject", origen, "--name-hash", "0xCA806E59",
                 "--file", str(nuevo), "--out", str(salida), "--flags", "0",
                 "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["name_hash"] == "0xca806e59"
    assert doc["after"]["flags"] == 0
    assert doc["after"]["compressed_size"] == doc["after"]["uncompressed_size"] == len(nuevo.read_bytes())
    assert doc["sha256"] == hashlib.sha256(open(str(salida), "rb").read()).hexdigest()


def test_cli_inject_slot_que_no_cabe(tmp_path, capsys):
    origen = _fdata_con_destino(tmp_path)
    # la entrada de destino no esta comprimida (0x30+40+10 B): cualquier payload
    # grande no cabe en su hueco
    grande = tmp_path / "grande.g1t"
    grande.write_bytes(os.urandom(4000))
    assert main(["fdata", "inject", origen, "--name-hash", "0xca806e59",
                 "--file", str(grande), "--out", str(tmp_path / "c.fdata"),
                 "--route", "slot"]) == 1
    assert "no cabe en la ranura" in capsys.readouterr().err


def test_cli_inject_slot_que_cabe_pero_no_esta_resuelto(tmp_path, capsys):
    origen = contenedor(tmp_path / "comprimido.fdata", [
        entrada(b"GT1G" + b"\x11" * 500, ktid=G1T, name_hash=HASH,
                metadata=b"\xbb" * 40, flags=0x400000),
    ], relleno_final=False)
    hueco = list(fdata.iter_entries(origen))[0].compressed_size
    nuevo = tmp_path / "pequeno.g1t"
    nuevo.write_bytes(b"\x00" * 40)
    assert fdata.chunked_size(nuevo.read_bytes()) <= hueco, "el caso de prueba tiene que caber"
    assert main(["fdata", "inject", origen, "--name-hash", "0xca806e59",
                 "--file", str(nuevo), "--out", str(tmp_path / "c.fdata"),
                 "--route", "slot"]) == 1
    error = capsys.readouterr().err
    assert "slot no implementada" in error and "no cabe" not in error


def test_cli_inject_hash_inexistente_y_fichero_que_falta(tmp_path, capsys):
    origen = _fdata_con_destino(tmp_path)
    nuevo = tmp_path / "nuevo.g1t"
    nuevo.write_bytes(b"GT1G")
    assert main(["fdata", "inject", origen, "--name-hash", "0x11223344",
                 "--file", str(nuevo), "--out", str(tmp_path / "c.fdata")]) == 1
    assert "0x11223344 no esta en" in capsys.readouterr().err

    assert main(["fdata", "inject", origen, "--name-hash", "0xca806e59",
                 "--file", str(tmp_path / "noexiste.g1t"),
                 "--out", str(tmp_path / "c.fdata")]) == 1
    assert "no existe el fichero" in capsys.readouterr().err


def test_cli_inject_no_pisa_el_origen(tmp_path, capsys):
    origen = _fdata_con_destino(tmp_path)
    nuevo = tmp_path / "nuevo.g1t"
    nuevo.write_bytes(b"GT1G" + b"\x01" * 16)
    antes = open(origen, "rb").read()
    assert main(["fdata", "inject", origen, "--name-hash", "0xca806e59",
                 "--file", str(nuevo), "--out", origen]) == 1
    assert "mismo fichero" in capsys.readouterr().err
    assert open(origen, "rb").read() == antes


# ---------------------------------------------------------------------------
# El hueco del payload (presupuesto, no escritura)
# ---------------------------------------------------------------------------

def test_chunked_size_no_escribe_los_8_bytes_del_trozo():
    payload = b"\x00" * (3 * fdata.CHUNK_SIZE)
    esperado = sum(10 + len(zlib.compress(payload[i:i + fdata.CHUNK_SIZE], 6))
                   for i in range(0, len(payload), fdata.CHUNK_SIZE))
    assert fdata.chunked_size(payload) == esperado


# ---------------------------------------------------------------------------
# Lector independiente: comprueba al escritor sin importarlo
# ---------------------------------------------------------------------------

def test_lector_independiente_lee_lo_que_escribe_repack(tmp_path):
    """`tests/independent_fdata_reader.py` no importa `pokopia.fdata`."""
    import subprocess
    import sys

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lector = os.path.join(raiz, "tests", "independent_fdata_reader.py")
    origen = contenedor(tmp_path / "origen.fdata", _tres_entradas(), relleno_final=False)
    copia = tmp_path / "copia.fdata"
    nuevo = fdata.write_entry(b"GT1G" + b"\x33" * 77, name_hash=HASH,
                              type_ktid=G1T, flags=0x400000)
    fdata.repack(origen, str(copia), {HASH: nuevo})

    detalle = tmp_path / "detalle.json"
    salida = subprocess.run([sys.executable, lector, str(copia), "--json", str(detalle)],
                            capture_output=True, text=True)
    assert salida.returncode == 0, salida.stderr
    doc = json.load(open(str(detalle), encoding="utf-8"))
    assert doc["entradas"] == 3
    assert doc["tamano"] == os.path.getsize(str(copia))
    assert doc["campo3"] == 0

    contra = subprocess.run([sys.executable, lector, str(copia), "--contra", origen],
                            capture_output=True, text=True)
    assert contra.returncode == 1              # hay una entrada distinta, la esperada
    assert '"payloads_distintos": 1' in contra.stdout
    assert '"entradas_movidas_de_offset": 1' in contra.stdout

    fila = [x for x in doc["detalle"] if x["name_hash"] == "0xca806e59"][0]
    assert fila["sha256"] == hashlib.sha256(b"GT1G" + b"\x33" * 77).hexdigest()
    assert fila["entry_size"] == len(nuevo)
    assert fila["flags"] == 0x400000

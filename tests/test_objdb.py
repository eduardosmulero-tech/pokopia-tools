"""`kidsobjdb` (`_DOK0000`/`IDOK0000`): registros, trios, reparto y CLI.

Todo con blobs sinteticos construidos byte a byte con el mismo layout que el
dump, para que la suite corra sin el juego. Los cuatro casos que importan son los
que separan un lector de un adivinador:

* la aritmetica de la cola (`24 + 12*pares + 4*suma(valores) == size`), que es lo
  que cierra el formato;
* un byte cambiado en la firma de un registro **falla**, no devuelve basura (C4);
* la suma de tamanos nunca pasa del blob y los registros no se solapan (C5);
* el recuento declarado en la cabecera tiene que salir al recorrer el fichero.

Y tres pruebas contra el dump real (se saltan con motivo si no esta).
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from pokopia import fdata, objdb, paths
from pokopia.cli import main

KIDSOBJDB = objdb.KIDSOBJDB_KTID
OTRO_TIPO = 0xDEADBEEF


# ---------------------------------------------------------------------------
# Construccion del blob sintetico
# ---------------------------------------------------------------------------

def registro(ident: int, type_hash: int, pares, *,
             firma: bytes = objdb.RECORD_MAGIC, cola_extra: bytes = b"") -> bytes:
    """Un registro completo.

    `pares` es una lista de `(kind, hash, valores)`. El layout es el medido: los
    tríos van todos seguidos en la cabecera y **despues** la carga de cada uno,
    en el mismo orden. `cola_extra` mete bytes que no cuadran a proposito.
    """
    trios = b"".join(struct.pack("<III", kind, len(valores), clave)
                     for kind, clave, valores in pares)
    carga = b"".join(struct.pack("<I", v)
                     for _, _, valores in pares for v in valores)
    cuerpo = trios + carga + cola_extra
    size = objdb.RECORD_HEADER_SIZE + len(cuerpo)
    return firma + struct.pack("<IIII", size, ident, type_hash, len(pares)) + cuerpo


def blob(registros, *, firma: bytes = objdb.FILE_MAGIC, declarados: int | None = None,
         cabecera: int = 28, cabecera_registro: int = objdb.RECORD_HEADER_SIZE,
         cola: bytes | None = None) -> bytes:
    """Fichero `_DOK0000`: cabecera, registros y nada mas."""
    if cola is None:
        cola = b"\x00" * (cabecera - objdb.MIN_HEADER_SIZE)
    n = len(registros) if declarados is None else declarados
    return (firma + struct.pack("<III", cabecera, cabecera_registro, n) + cola
            + b"".join(registros))


def entrada_idrk(payload: bytes, ktid: int, name_hash: int) -> bytes:
    """Entrada IDRK cruda (compressed_size == uncompressed_size)."""
    entry_size = fdata.ENTRY_HEADER_SIZE + len(payload)
    return (fdata.IDRK_MAGIC
            + struct.pack("<3Q", entry_size, len(payload), len(payload))
            + struct.pack("<4I", 0, name_hash, ktid, 0)
            + payload)


def escribir_fdata(ruta, entradas) -> str:
    """Contenedor PDRK con las entradas dadas, cada una alineada a 16 B."""
    buf = bytearray(fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0))
    for ent in entradas:
        buf += ent
        if len(buf) % fdata.ENTRY_ALIGN:
            buf += b"\x00" * (fdata.ENTRY_ALIGN - len(buf) % fdata.ENTRY_ALIGN)
    with open(ruta, "wb") as fh:
        fh.write(bytes(buf))
    return str(ruta)


def dos_registros() -> bytes:
    return blob([
        registro(0x000084CE, 0x18EB1E56, [
            (5, 0x193025DF, (0x1CA8BB39,)),
            (5, 0xDB59AAFC, ()),
        ]),
        registro(0x7FFFFFFF, OTRO_TIPO, [
            (5, 0x193025DF, (1, 2, 3)),
            (4, 0x7D63EE7A, (0,)),
            (8, 0xB17E2494, (0xDEADBEEF, 0xFEEDFACE)),
        ]),
    ])


# ---------------------------------------------------------------------------
# Recorrido: offset, size, id, type_hash y trios
# ---------------------------------------------------------------------------

def test_iter_records_da_offset_size_id_tipo_y_trios():
    datos = dos_registros()
    primero, segundo = list(objdb.iter_records(datos))

    assert primero.offset == 28
    assert primero.size == objdb.RECORD_HEADER_SIZE + 2 * objdb.PAIR_SIZE + 4
    assert primero.id == 0x000084CE
    assert primero.type_hash == 0x18EB1E56
    assert [p.hash for p in primero.pairs] == [0x193025DF, 0xDB59AAFC]
    assert [p.kind for p in primero.pairs] == [5, 5]
    assert primero.pairs[0].values == (0x1CA8BB39,)
    assert primero.pairs[1].values == ()
    assert primero.pairs[1].n_values == 0

    # sin solapes y en orden: cada registro empieza donde acaba el anterior
    assert segundo.offset == primero.end
    assert segundo.end == len(datos)
    assert [p.values for p in segundo.pairs] == [(1, 2, 3), (0,), (0xDEADBEEF, 0xFEEDFACE)]
    assert [p.kind for p in segundo.pairs] == [5, 4, 8]


def test_load_de_bytes_reparte_por_tamano_y_por_tipo():
    db = objdb.load(dos_registros())
    assert db.count == 2
    assert db.declared_count == 2
    assert db.pair_count == 5
    assert db.header_size == 28 and db.record_header_size == 24
    assert [t.as_dict() for t in db.by_type] == [
        {"type_hash": "0x18eb1e56", "records": 1},
        {"type_hash": "0xdeadbeef", "records": 1},
    ]
    assert sum(s.records for s in db.by_size) == 2
    assert db.find(0x7FFFFFFF).type_hash == OTRO_TIPO
    assert db.find(1234) is None
    assert [r.id for r in db.records_of(OTRO_TIPO)] == [0x7FFFFFFF]

    doc = db.as_dict()
    assert doc["records"] == 2 and doc["type_hashes"] == 2
    assert doc["sizes"] and doc["types"]


def test_load_desde_fdata_elige_el_kidsobjdb_mayor(tmp_path):
    """Una ruta `.fdata` (o la carpeta) se abre por la base mayor de dentro."""
    pequeno = blob([registro(1, OTRO_TIPO, [(5, 0x11223344, (7,))])])
    grande = dos_registros()
    ruta = escribir_fdata(tmp_path / "0x0000abcd.fdata", [
        entrada_idrk(b"otra cosa", 0x5599AA51, 0x00000001),
        entrada_idrk(pequeno, KIDSOBJDB, 0x00000002),
        entrada_idrk(grande, KIDSOBJDB, 0x00000003),
    ])

    from_fdata = objdb.load(ruta)
    assert from_fdata.count == 2, "tiene que leer el kidsobjdb de 0x00000003"
    assert from_fdata.source_entry is not None
    assert from_fdata.source_entry.name_hash == 0x00000003
    assert from_fdata.origin is not None
    assert os.path.basename(from_fdata.origin) == "0x0000abcd.fdata"

    from_dir = objdb.load(str(tmp_path))
    assert from_dir.count == 2
    assert [s.size for s in objdb.find_sources(str(tmp_path))] == [len(grande), len(pequeno)]
    assert objdb.largest(str(tmp_path)).entry.name_hash == 0x00000003

    # y un fichero que ya es la base, sin pasar por el .fdata
    suelto = tmp_path / "extraido.bin"
    suelto.write_bytes(grande)
    assert objdb.load(str(suelto)).count == 2


# ---------------------------------------------------------------------------
# C4 y C5: fallar en vez de adivinar, y no solaparse
# ---------------------------------------------------------------------------

def test_c4_un_byte_mutado_en_la_firma_falla(tmp_path):
    """Un byte cambiado en `IDOK0000` tiene que romper, no devolver basura."""
    datos = bytearray(dos_registros())
    assert datos[28:36] == objdb.RECORD_MAGIC
    datos[30] ^= 0x01                      # 'O' -> 'N' en la firma del primer registro

    with pytest.raises(objdb.ObjDbFormatError) as excinfo:
        list(objdb.iter_records(bytes(datos)))
    assert "IDOK0000" in str(excinfo.value)
    assert "0x1c" in str(excinfo.value), "el error tiene que decir donde"

    with pytest.raises(objdb.ObjDbFormatError):
        objdb.load(bytes(datos))

    ruta = tmp_path / "mutado.bin"
    ruta.write_bytes(bytes(datos))
    with pytest.raises(objdb.ObjDbFormatError):
        objdb.load(str(ruta))


def test_c4_un_byte_mutado_en_la_firma_del_fichero_falla():
    datos = bytearray(dos_registros())
    datos[0] = ord("X")
    with pytest.raises(objdb.ObjDbFormatError) as excinfo:
        objdb.load(bytes(datos))
    assert "_DOK0000" in str(excinfo.value)


def test_c5_los_tamanos_suman_el_blob_sin_solapes():
    datos = dos_registros()
    registros = list(objdb.iter_records(datos))

    suma = sum(r.size for r in registros)
    assert suma == len(datos) - 28
    assert suma <= len(datos), "la suma de tamanos no puede pasarse del blob"
    anterior = 28
    for r in registros:
        assert r.offset >= anterior, "dos registros no pueden solaparse"
        assert r.offset == anterior
        anterior = r.end
    assert anterior == len(datos), "el ultimo registro tiene que acabar en el final del blob"


def test_size_que_se_sale_del_blob_no_se_lee_a_medias():
    datos = bytearray(dos_registros())
    struct.pack_into("<I", datos, 28 + 8, 4096)     # size enorme en el primer registro
    with pytest.raises(objdb.ObjDbTruncatedError):
        list(objdb.iter_records(bytes(datos)))


def test_recuento_declarado_distinto_falla():
    datos = blob([registro(1, OTRO_TIPO, [(5, 0x11223344, (7,))])], declarados=2)
    with pytest.raises(objdb.ObjDbFormatError) as excinfo:
        objdb.load(datos)
    assert "declara 2" in str(excinfo.value) and "tiene 1" in str(excinfo.value)


def test_cola_que_no_cuadra_falla():
    """Si declara tres valores y hay uno, el registro no cuadra: error, no basura."""
    datos = blob([registro(1, OTRO_TIPO, [(5, 0xAA, (1, 2, 3))], cola_extra=b"\x00" * 4)])
    with pytest.raises(objdb.ObjDbFormatError) as excinfo:
        objdb.load(datos)
    assert "sin cuadrar" in str(excinfo.value)


def test_blob_demasiado_corto_es_error():
    with pytest.raises(objdb.ObjDbTruncatedError):
        objdb.load(objdb.FILE_MAGIC + b"\x00" * 4)
    with pytest.raises(objdb.ObjDbError):
        objdb.load(b"")


# ---------------------------------------------------------------------------
# CLI contra un romfs sintetico
# ---------------------------------------------------------------------------

@pytest.fixture()
def romfs(tmp_path) -> str:
    raiz = tmp_path / "romfs"
    (raiz / "motor_asset_re").mkdir(parents=True)
    escribir_fdata(raiz / "motor_asset_re" / "a.fdata",
                   [entrada_idrk(dos_registros(), KIDSOBJDB, 0x0000BEEF)])
    return str(raiz)


def test_cli_stat_del_romfs_sintetico(romfs, capsys):
    assert main(["objdb", "stat", romfs, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["records"] == 2
    assert doc["declared_count"] == 2
    assert doc["pairs"] == 5
    assert doc["type_hashes"] == 2
    assert sum(s["records"] for s in doc["sizes"]) == 2
    assert {t["type_hash"] for t in doc["types"]} == {"0x18eb1e56", "0xdeadbeef"}
    assert doc["fdata_entry"]["type"] == "kidsobjdb"

    assert main(["objdb", "stat", romfs]) == 0
    texto = capsys.readouterr().out
    assert "registros : 2" in texto
    assert "type_hash : 2 distintos" in texto
    assert "0x18eb1e56" in texto and "0xdeadbeef" in texto


def test_cli_dump_saca_todos_los_registros_de_un_tipo(romfs, capsys):
    assert main(["objdb", "dump", romfs, "--type", "0x18eb1e56", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["total"] == 1 and doc["shown"] == 1
    assert doc["records"][0]["id"] == 0x000084CE
    assert doc["records"][0]["pairs"][0]["values"] == [0x1CA8BB39]

    # con --limit no se corta en silencio: dice cuantos hay y cuantos saca
    assert main(["objdb", "dump", romfs, "--type", "0xdeadbeef", "--limit", "1"]) == 0
    texto = capsys.readouterr().out
    assert "0xdeadbeef: 1 registros, mostrando 1" in texto
    assert "kind 8" in texto and "0xfeedface" in texto

    # y un tipo que no esta es un error, no un cero silencioso
    assert main(["objdb", "dump", romfs, "--type", "0x12345678"]) == 1
    assert "ningun registro con type_hash" in capsys.readouterr().err

    # --type no hex: error de uso
    assert main(["objdb", "dump", romfs, "--type", "noeshex"]) == 2
    assert "type_hash en hex" in capsys.readouterr().err


def test_cli_id_encuentra_y_no_encuentra(romfs, capsys):
    assert main(["objdb", "id", romfs, "2147483647"]) == 0
    texto = capsys.readouterr().out
    assert "type_hash 0xdeadbeef" in texto and "0xfeedface" in texto

    assert main(["objdb", "id", romfs, "2147483647", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["found"] is True and doc["record"]["type_hash"] == "0xdeadbeef"

    assert main(["objdb", "id", romfs, "1234"]) == 1
    assert "ningun registro con id 1234" in capsys.readouterr().err


def test_cli_sin_kidsobjdb_es_un_error(tmp_path, capsys):
    (tmp_path / "x.fdata").write_bytes(
        fdata.PDRK_MAGIC + struct.pack("<2I", 0x10, 0)
        + entrada_idrk(b"nada", 0x5599AA51, 1))
    assert main(["objdb", "stat", str(tmp_path)]) == 1
    assert "no hay ningun kidsobjdb" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# La base mayor del dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
HAY_DUMP = os.path.isdir(ROMFS) and any(
    nombre.endswith(".fdata")
    for _, _, ficheros in os.walk(ROMFS) for nombre in ficheros)
necesita_dump = pytest.mark.skipif(
    not HAY_DUMP, reason="sin dump del juego (exporta PKP_ROMFS)")

#: Lo medido en el build 655360 (informe t_cb6d917e).
TAMANOS = ((100, 121296), (220, 99815), (228, 33909), (212, 9953), (208, 8461),
           (224, 7876), (216, 5279), (196, 3136), (176, 2650))


@pytest.fixture(scope="module")
def base_mayor():
    """La base de 50.152.112 B, cargada una vez para toda la seccion (2,3 s)."""
    if not HAY_DUMP:
        pytest.skip("sin dump del juego (exporta PKP_ROMFS)")
    return objdb.load(ROMFS)


@necesita_dump
def test_stat_de_la_base_mayor_del_dump(base_mayor):
    db = base_mayor
    assert db.count == 294939
    assert db.declared_count == 294939
    assert len(db.by_type) == 190
    assert db.pair_count == 1474636
    assert db.source_entry is not None
    assert db.source_entry.uncompressed_size == 50152112
    assert tuple((s.size, s.records) for s in db.by_size)[:9] == TAMANOS
    assert len(db.by_size) == 23
    # C5 sobre el fichero real: los registros agotan el blob, sin solapes
    suma = sum(r.size for r in db.records())
    assert suma == len(db.blob) - db.header_size


@necesita_dump
def test_dump_e_id_de_la_base_mayor(base_mayor, capsys):
    assert main(["objdb", "dump", ROMFS, "--type", "0xfe476315", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["total"] == 1 and doc["shown"] == 1
    ident = doc["records"][0]["id"]
    assert doc["records"][0]["pairs"][0]["hash"] == "0x193025df"

    assert main(["objdb", "id", ROMFS, str(ident), "--json"]) == 0
    encontrado = json.loads(capsys.readouterr().out)
    assert encontrado["found"] is True
    assert encontrado["record"]["type_hash"] == "0xfe476315"

    # el tipo mayor aparece entero: 258.043 registros, contados por el modulo
    assert sum(1 for _ in base_mayor.records_of(0x18EB1E56)) == 258043

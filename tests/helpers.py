"""Utilidades de prueba: contenedores sinteticos, tablas declaradas y mods."""

from __future__ import annotations

import contextlib
import json
import os
import struct

from pokopia import paths, tables
from pokopia.container import ContainerWriter, get_compressor, read_container, unpack_entry
from pokopia.tables import TableSpec

#: Tablas sinteticas que usan los tests (no existen en el dump o no se usan).
REC_TABLE = 5
TEXT_TABLE = 6
REC_COUNT = 8
REC_STRIDE = 68
TEXT_COUNT = 10
TEXT_SLOTS = 40


def records_payload(rows: dict[int, bytes], count: int = REC_COUNT,
                    stride: int = REC_STRIDE, version: int = 0) -> bytes:
    """Payload con header de 64 B (count, version) y `count` filas de `stride`."""
    buf = bytearray(64 + count * stride)
    struct.pack_into("<II", buf, 0, count, version)
    for row, data in rows.items():
        if len(data) > stride:
            raise ValueError("fila %d: %d B > stride %d" % (row, len(data), stride))
        start = 64 + row * stride
        buf[start:start + len(data)] = data
    return bytes(buf)


def text_payload(slots: list[bytes], count: int = TEXT_COUNT, version: int = 2) -> bytes:
    """Payload de tabla de texto: header 64 B + count*32 B de registros + pool."""
    buf = bytearray(64 + count * 32)
    struct.pack_into("<II", buf, 0, count, version)
    return bytes(buf) + b"".join(slot + b"\x00" for slot in slots)


def make_container(root: str, payloads: dict[int, bytes], entries: int | None = None) -> paths.Container:
    """Contenedor sintetico con un payload por indice (vacio si no se declara)."""
    os.makedirs(root, exist_ok=True)
    n = entries if entries is not None else max(payloads) + 1
    idx = os.path.join(root, paths.IDX_NAME)
    binp = os.path.join(root, paths.BIN_NAME)
    writer = ContainerWriter(binp, get_compressor("auto"))
    for i in range(n):
        blob = payloads.get(i, b"")
        writer.add(blob, flag=(1 if blob else 0))
    writer.close(idx)
    return paths.Container(os.path.abspath(root), idx, binp)


@contextlib.contextmanager
def temp_spec(index: int, **kwargs):
    """Declara una tabla temporalmente en el registro (se restaura al salir)."""
    spec = TableSpec(index=index, **kwargs)
    previous = tables.TABLES.get(index)
    tables.TABLES[index] = spec
    try:
        yield spec
    finally:
        if previous is None:
            tables.TABLES.pop(index, None)
        else:
            tables.TABLES[index] = previous


def records_spec(index: int = REC_TABLE, count: int = REC_COUNT,
                 stride: int = REC_STRIDE, version: int = 0):
    return temp_spec(index, kind="records", header=64, stride=stride, count=count,
                     version=version, confidence="verified", source="tests")


def text_spec(index: int = TEXT_TABLE, count: int = TEXT_COUNT):
    return temp_spec(index, kind="text", header=64, stride=32, count=count,
                     version=2, pool_start=64 + 32 * count,
                     confidence="verified", source="tests")


def base_doc(container: paths.Container, name: str = "mod-de-prueba") -> dict:
    md5 = paths.container_md5(container)
    return {
        "mod_format": 1,
        "name": name,
        "version": "0.1.0",
        "authors": ["tests"],
        "description": "",
        "game": {"title": "pokopia", "version": "2.0.1a", "container_md5": md5},
        "requires": [],
        "edits": [],
        "text": [],
        "files": [],
    }


def write_mod(root: str, doc: dict, name: str = "mod.json") -> str:
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, name)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    return target


def read_payload(container: paths.Container, table: int) -> bytes:
    entries, bin_data = read_container(container.idx, container.bin)
    return unpack_entry(bin_data, entries[table], index=table)


def u32(payload: bytes, offset: int) -> int:
    return struct.unpack_from("<I", payload, offset)[0]

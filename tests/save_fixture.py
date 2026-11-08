"""Save sintetico para los tests: misma geometria que el layout, cero datos del juego.

No es una copia del save real: el payload se rellena a cero y solo se escriben los
registros que el test declara. Se construye en memoria (4,6 MB de ceros) y se guarda como
CMNDAT.BIN valido: cabecera de 0x130, zlib y longitud declarada.
"""
from __future__ import annotations

import os
import struct
import zlib

from pokopia.save import layout as layouts

HEADER = layouts.HEADER_SIZE


def blank_payload(lay: layouts.Layout | None = None) -> bytearray:
    lay = lay or layouts.LAYOUT_2_0_1
    return bytearray(lay.payload_size)


def write_record(payload: bytearray, lay: layouts.Layout, region: str, index: int,
                 data: bytes) -> None:
    reg = lay.region(region)
    start, end = reg.record(index)
    if len(data) > reg.stride:
        raise ValueError("registro de %d B no cabe en el stride %d"
                         % (len(data), reg.stride))
    payload[start:start + len(data)] = data


def item_record(item_id: int, count: int = 1, variant: int = 0) -> bytes:
    word = (variant & ~0x1FFF) | (item_id & 0x1FFF)
    return struct.pack("<I", word) + bytes([count & 0xFF])


def villager_record(marker: int = 1) -> bytes:
    """Registro de aldeano con identificador no nulo en +1..+16."""
    rec = bytearray(374)
    for i in range(1, 17):
        rec[i] = (marker * 7 + i) & 0xFF
    rec[21] = 1
    return bytes(rec)


def make_payload(*, items: dict[int, tuple[int, int]] | None = None,
                 villagers: int = 0, homes: int = 0,
                 catalogue: dict[int, int] | None = None,
                 lay: layouts.Layout | None = None) -> bytes:
    """Payload con los registros indicados. `items` = {hueco: (id, cantidad)}."""
    lay = lay or layouts.LAYOUT_2_0_1
    payload = blank_payload(lay)
    for slot, (item_id, count) in (items or {}).items():
        write_record(payload, lay, "inventory", slot, item_record(item_id, count))
    for k in range(villagers):
        write_record(payload, lay, "villagers", k, villager_record(k + 1))
    home = bytearray(lay.region("homes").stride)
    home[0] = 1
    for k in range(homes):
        write_record(payload, lay, "homes", k, bytes(home))
    for item_id, value in (catalogue or {}).items():
        reg = lay.region("catalogue")
        payload[reg.offset + item_id] = value
    return bytes(payload)


def write_page(directory: str, payload: bytes, *, page: str = "G00",
               version: int = layouts.VERSION_2_0_1, magic: int = layouts.SAVE_MAGIC,
               declared_delta: int = 0, raw_payload: bytes | None = None,
               tail: bytes = b"") -> str:
    """Escribe un CMNDAT.BIN sintetico y devuelve su ruta."""
    os.makedirs(os.path.join(directory, page), exist_ok=True)
    path = os.path.join(directory, page, "CMNDAT.BIN")
    body = zlib.compress(raw_payload if raw_payload is not None else payload, 6)
    head = bytearray(HEADER)
    struct.pack_into("<III", head, 0, magic, version, 0x40001)
    struct.pack_into("<i", head, 0x10, HEADER + len(body) + declared_delta)
    with open(path, "wb") as fh:
        fh.write(bytes(head) + body + tail)
    return path


def make_save(directory: str, *, payload: bytes | None = None, pages: tuple[str, ...] = ("G00",),
              **kwargs) -> str:
    payload = payload if payload is not None else make_payload()
    for page in pages:
        write_page(directory, payload, page=page, **kwargs)
    return os.path.join(directory, "G00", "CMNDAT.BIN")

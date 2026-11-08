"""Inventario del save: los 130 registros de 5 B de la region `inventory`.

Geometria (la pone el layout, aqui solo se interpreta):

    +0  u32  raw    id = raw & 0x1FFF   (13 bits; 0 = hueco vacio)
                    bits 13..31 = variante / colocacion del objeto
    +4  u8   cantidad                    (0..255)

La mascara no es opcional: leer los dos primeros bytes como u16 sin enmascarar convierte
cuatro registros de las paginas medidas en ids de 10.208 y mas, fuera de las 4.600 filas
de `#983` (medido en t_e4f8d673).

Este modulo no escribe ficheros: `with_item()` devuelve el payload nuevo y `writer.py` es
quien lo guarda con copia de seguridad.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .errors import SaveError
from .page import SavePage

#: Bits bajos del campo `raw` que forman el id de objeto.
ITEM_ID_MASK = 0x1FFF

#: Cantidad maxima que cabe en el byte +4.
MAX_COUNT = 255

#: Papel de la region del inventario en el layout. Se pide por papel, no por nombre:
#: una version nueva puede llamar a la region de otra forma sin tocar este modulo.
ROLE = "inventory"


@dataclass(frozen=True)
class ItemRecord:
    """Un hueco del inventario."""

    slot: int
    raw: bytes
    item_id: int
    count: int

    @property
    def occupied(self) -> bool:
        return self.item_id != 0

    @property
    def variant(self) -> int:
        """Bits 13..31 del campo `raw` (variante y colocacion)."""
        return struct.unpack_from("<I", self.raw, 0)[0] & ~ITEM_ID_MASK

    def as_dict(self) -> dict:
        return {"slot": self.slot, "id": self.item_id, "count": self.count,
                "variant": self.variant, "raw": self.raw.hex(),
                "occupied": self.occupied}

    def __str__(self) -> str:
        return ("hueco %3d  id %5d  cant %3d%s"
                % (self.slot, self.item_id, self.count,
                   "" if not self.variant else "  variante %#x" % self.variant))


def _layout(page: SavePage):
    return page.layout


def read_items(page: SavePage) -> list[ItemRecord]:
    """Los 130 registros del inventario de una pagina."""
    reg = _layout(page).region_by_role(ROLE)
    out = []
    for slot in range(reg.count):
        start, end = reg.record(slot)
        raw = page.payload[start:end]
        word = struct.unpack_from("<I", raw, 0)[0]
        count = raw[reg.stride - 1]
        out.append(ItemRecord(slot=slot, raw=raw, item_id=word & ITEM_ID_MASK,
                              count=count))
    return out


def distinct_ids(page: SavePage) -> list[int]:
    return sorted({r.item_id for r in read_items(page) if r.occupied})


def occupied(page: SavePage) -> int:
    return sum(1 for r in read_items(page) if r.occupied)


def with_item(page: SavePage, slot: int, *, item_id: int | None = None,
              count: int | None = None, variant: int | None = None) -> bytes:
    """Payload nuevo con un registro cambiado. No toca el fichero.

    `item_id=None` deja el id actual; lo mismo `count` y `variant`. Pasar `item_id=0`
    vacia el hueco.
    """
    reg = _layout(page).region_by_role(ROLE)
    if not 0 <= slot < reg.count:
        raise SaveError("hueco %d fuera de rango (0..%d)" % (slot, reg.count - 1))
    start, end = reg.record(slot)
    raw = page.payload[start:end]
    word = struct.unpack_from("<I", raw, 0)[0]
    current_id = word & ITEM_ID_MASK
    current_variant = word & ~ITEM_ID_MASK
    new_id = current_id if item_id is None else item_id
    new_count = raw[reg.stride - 1] if count is None else count
    new_variant = current_variant if variant is None else variant

    if not 0 <= new_id <= ITEM_ID_MASK:
        raise SaveError("id %d no cabe en 13 bits (0..%d)" % (new_id, ITEM_ID_MASK))
    if not 0 <= new_count <= MAX_COUNT:
        raise SaveError("cantidad %d fuera de rango (0..%d)" % (new_count, MAX_COUNT))
    if new_variant & ITEM_ID_MASK:
        raise SaveError("la variante %#x se solapa con el id (mascara %#x)"
                        % (new_variant, ITEM_ID_MASK))

    record = struct.pack("<I", new_variant | new_id) + bytes([new_count])
    if len(record) < reg.stride:
        record = record + raw[len(record):]
    payload = bytearray(page.payload)
    payload[start:end] = record
    return bytes(payload)


def set_item(payload: bytes, page: SavePage, slot: int, *,
             item_id: int | None = None, count: int | None = None,
             variant: int | None = None) -> bytes:
    """Igual que `with_item` pero partiendo de un payload ya modificado."""
    tmp = SavePage(path=page.path, page=page.page, raw=page.raw, payload=payload,
                   layout=page.layout, md5=page.md5)
    return with_item(tmp, slot, item_id=item_id, count=count, variant=variant)


def diff_bytes(a: bytes, b: bytes) -> list[int]:
    """Offsets donde dos buffers del mismo tamano difieren."""
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]

"""Tipos de campo que un mod puede escribir, y su codificacion.

Un mod declara `type` y dos valores textuales (`expect`, `value`). Aqui se
traducen a bytes y se comprueba que caben en el tipo.
"""

from __future__ import annotations

import struct

#: tipo -> (tamano en bytes, formato struct). "bytes" no tiene tamano fijo.
SCALARS: dict[str, tuple[int, str]] = {
    "u8": (1, "<B"),
    "i8": (1, "<b"),
    "u16": (2, "<H"),
    "i16": (2, "<h"),
    "u32": (4, "<I"),
    "i32": (4, "<i"),
    "u64": (8, "<Q"),
    "i64": (8, "<q"),
    "f32": (4, "<f"),
    "f64": (8, "<d"),
}

TYPES = tuple(SCALARS) + ("bytes",)


class TypeError_(ValueError):
    """Valor o tipo de campo invalido en un mod."""


def type_size(typ: str) -> int | None:
    """Bytes que ocupa el tipo; None si es de longitud declarada ("bytes")."""
    if typ == "bytes":
        return None
    if typ not in SCALARS:
        raise TypeError_("tipo desconocido %r (validos: %s)" % (typ, ", ".join(TYPES)))
    return SCALARS[typ][0]


def _to_number(text) -> int | float:
    if isinstance(text, bool):
        raise TypeError_("valor booleano no admitido")
    if isinstance(text, (int, float)):
        return text
    if not isinstance(text, str):
        raise TypeError_("valor %r no es numero ni cadena" % (text,))
    raw = text.strip().replace("_", "")
    if not raw:
        raise TypeError_("valor vacio")
    neg = raw.startswith("-")
    body = raw[1:] if neg else raw
    try:
        value = int(body, 16) if body.lower().startswith("0x") else int(body, 10)
    except ValueError:
        try:
            value = float(raw)
        except ValueError:
            raise TypeError_("%r no es un numero" % text) from None
    return -value if neg else value


def parse_hex(text: str) -> bytes:
    """Cadena hex -> bytes. Admite espacios, guiones y prefijos 0x por byte."""
    if not isinstance(text, str):
        raise TypeError_("se esperaba una cadena hex, no %r" % (text,))
    raw = text.strip().replace(" ", "").replace("_", "").replace("-", "")
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    if len(raw) % 2:
        raise TypeError_("hex de longitud impar: %r" % text)
    try:
        return bytes.fromhex(raw)
    except ValueError:
        raise TypeError_("%r no es hex valido" % text) from None


def encode(typ: str, text) -> bytes:
    """Codifica `expect`/`value` segun el tipo declarado."""
    if typ == "bytes":
        return parse_hex(text)
    size, fmt = SCALARS[typ]
    if typ.startswith("f"):
        value = float(_to_number(text))
        try:
            return struct.pack(fmt, value)
        except (OverflowError, struct.error) as exc:
            raise TypeError_("%r no cabe en %s (%s)" % (text, typ, exc)) from None
    value = _to_number(text)
    if isinstance(value, float):
        if value != int(value):
            raise TypeError_("%r no es entero y el tipo es %s" % (text, typ))
        value = int(value)
    lo, hi = (-(1 << (8 * size - 1)), (1 << (8 * size - 1)) - 1) if typ[0] == "i" \
        else (0, (1 << (8 * size)) - 1)
    if not lo <= value <= hi:
        raise TypeError_("%d fuera de rango para %s (%d..%d)" % (value, typ, lo, hi))
    return struct.pack(fmt, value)


def decode(typ: str, data: bytes):
    """Valor legible de un campo ya leido del contenedor."""
    if typ == "bytes":
        return data.hex()
    _, fmt = SCALARS[typ]
    return struct.unpack(fmt, data)[0]


def describe(typ: str, data: bytes) -> str:
    """Texto estable para informes: hex + valor decimal/cadena."""
    if typ == "bytes":
        return "hex %s" % data.hex()
    value = decode(typ, data)
    return "%s (0x%x) hex %s" % (value, value, data.hex())

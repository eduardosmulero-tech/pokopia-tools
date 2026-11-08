"""Animaciones del motor KTGL (`G2A`): lectura, escritura, exportacion y edicion.

El contenedor `.fdata` llama `g1a` al tipo (`type_ktid` `0x6fa91671`), pero los
ficheros son `G2A` version `0400`. Ver `pokopia.anim.g2a` para el formato y
`pokopia.anim.serial` para la exportacion a JSON/CSV.
"""

from . import g2a, serial, source
from .g2a import (
    AnimError,
    AnimFormatError,
    Animation,
    Bone,
    Header,
    KeyBlock,
    Row,
    Spline,
    axis_angle_to_quaternion,
    build,
    parse,
    peek,
    roundtrip,
    set_keyframe_value,
)
from .serial import (CSV_HEADER, csv_rows, from_json, read_json, to_json,
                     write_csv, write_json)
from .source import load, load_bytes

__all__ = [
    "AnimError",
    "AnimFormatError",
    "Animation",
    "Bone",
    "CSV_HEADER",
    "Header",
    "KeyBlock",
    "Row",
    "Spline",
    "axis_angle_to_quaternion",
    "build",
    "csv_rows",
    "from_json",
    "g2a",
    "load",
    "load_bytes",
    "parse",
    "peek",
    "read_json",
    "roundtrip",
    "serial",
    "set_keyframe_value",
    "source",
    "to_json",
    "write_csv",
    "write_json",
]

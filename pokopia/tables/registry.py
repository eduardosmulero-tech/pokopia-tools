"""Geometria declarada de las tablas conocidas del contenedor.

Solo metadatos de formato: cuanto mide el header, cual es el stride de fila,
cuantas filas hay y donde empieza la zona de texto. **Ninguna semantica de
contenido**: los campos se nombran por lo que la spec demuestra (`nameIndex` es
el u16 de +34 de `#983`, con `id = nameIndex + 3`), o no se nombran.

Cada tabla lleva `confidence`:
  verified   medido y contrastado con una spec del repo
  inference  geometria medida, semantica sin demostrar
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class FieldSpec:
    offset: int
    type: str
    name: str
    note: str = ""
    confidence: str = "verified"


@dataclass(frozen=True)
class TableSpec:
    index: int
    kind: str                     # "records" | "text"
    header: int
    stride: int
    count: int
    count_field: int = 0
    version_field: int = 4
    version: int | None = None
    pool_start: int | None = None
    language: str | None = None
    fields: tuple[FieldSpec, ...] = ()
    confidence: str = "verified"
    source: str = ""
    note: str = ""

    # -- geometria -------------------------------------------------------
    def row_offset(self, row: int) -> int:
        """Posicion absoluta del primer byte de la fila dentro del payload."""
        if not 0 <= row < self.count:
            raise IndexError("fila %d fuera de rango (0..%d) de la tabla #%d"
                             % (row, self.count - 1, self.index))
        return self.header + row * self.stride

    @property
    def records_end(self) -> int:
        return self.header + self.count * self.stride


def _records(index: int, stride: int, count: int, *, version=None,
             fields=(), confidence="inference", note="") -> TableSpec:
    return TableSpec(index=index, kind="records", header=64, stride=stride,
                     count=count, version=version, fields=fields,
                     confidence=confidence, source="docs/ARQUITECTURA-KIT.md §3",
                     note=note)


NAMES_LANGS = ("jp", "en", "fr", "it", "de", "es", "zh-TW", "kr", "zh-CN")

TABLES: dict[int, TableSpec] = {}


def _add(spec: TableSpec) -> None:
    TABLES[spec.index] = spec


# --- tablas de registros medidas (sin semantica de campo) -------------------
_add(_records(40, 80, 4096, confidence="inference",
              note="64 + 4096*80 = 327.744 B (medido)"))
_add(_records(41, 16, 4096, version=3, confidence="inference",
              note="64 + 4096*16 = 65.600 B (medido)"))
_add(_records(42, 4, 256, confidence="inference",
              note="64 + 256*4 = 1.088 B; el u32 de +0 dice 255 y no 256 (medido)"))
_add(_records(44, 100, 4096, confidence="inference",
              note="64 + 4096*100 = 409.664 B (medido)"))

# --- tabla de items: unica con un campo demostrado -------------------------
_add(_records(
    983, 68, 4600, version=3,
    fields=(FieldSpec(34, "u16", "nameIndex",
                      note="id de texto = nameIndex + 3 (docs/SPEC-NAMES.md §6.3)",
                      confidence="verified"),),
    confidence="inference",
    note="64 + 4600*68 = 312.864 B; count=4600 en +0 y version=3 en +4 (medido). "
         "El resto de la ficha no esta demostrado: ver SPEC-ITEM-ROW.",
))

# --- tablas de texto -------------------------------------------------------
for i, lang in enumerate(NAMES_LANGS):
    _add(TableSpec(index=4636 + i, kind="text", header=64, stride=32, count=3001,
                   version=2, pool_start=96096, language=lang,
                   confidence="verified", source="docs/SPEC-NAMES.md §3.2",
                   note="descripciones; pool en 96.096 (medido)"))
for i, lang in enumerate(NAMES_LANGS):
    _add(TableSpec(index=4645 + i, kind="text", header=64, stride=32, count=3001,
                   version=2, pool_start=96102, language=lang,
                   confidence="verified", source="docs/SPEC-NAMES.md §3.1",
                   note="nombres; pool en 96.102 (6 ceros de separacion, medido)"))

#: primera/ultima id de texto valida (`r` en 4..count+3, docs/SPEC-NAMES.md §6)
TEXT_FIRST_ID = 4
SLOTS_PER_BLOCK = 6
SINGULAR_SLOT = 0
PLURAL_SLOT = 2


def get(index: int) -> TableSpec | None:
    return TABLES.get(index)


def known() -> list[TableSpec]:
    return [TABLES[k] for k in sorted(TABLES)]


def table_name(index: int) -> str:
    spec = TABLES.get(index)
    if spec is None:
        return "#%d (sin geometria declarada)" % index
    if spec.kind == "text":
        return "#%d textos %s" % (index, spec.language)
    return "#%d registros de %d B" % (index, spec.stride)


# --- lectura de payloads con geometria ------------------------------------

class TableError(ValueError):
    """El payload no cuadra con la geometria declarada."""


def check_header(spec: TableSpec, blob: bytes, *, modificado: bool = False) -> tuple[int, int]:
    """Comprueba count/version del header y devuelve (count, version).

    Por defecto el `count` tiene que ser exactamente el declarado: un dump de
    otra version o un payload corrupto falla aqui, y debe fallar. Con
    `modificado=True` (el flag `--modificado` de la CLI) se admite que un
    contenedor **derivado** del dump traiga mas filas que el declarado
    (docs/AÑADIR-FILAS.md); entonces la estructura se comprueba contra el
    `count` real, no contra el declarado, y el llamante recibe ese count real
    para derivar la geometria con `con_conteo`. El `version` no admite deriva
    en ninguno de los dos modos: es el marcador de formato.
    """
    if len(blob) < spec.header:
        raise TableError("#%d: payload de %d B, header de %d B"
                         % (spec.index, len(blob), spec.header))
    count = struct.unpack_from("<I", blob, spec.count_field)[0]
    version = struct.unpack_from("<I", blob, spec.version_field)[0]
    if count != spec.count and not modificado:
        raise TableError("#%d: count del header %d != %d declarado"
                         % (spec.index, count, spec.count))
    if spec.version is not None and version != spec.version:
        raise TableError("#%d: version del header %d != %d declarado"
                         % (spec.index, version, spec.version))
    records_end = spec.header + count * spec.stride
    if len(blob) < records_end:
        raise TableError("#%d: payload de %d B y el area de registros acaba en %d"
                         % (spec.index, len(blob), records_end))
    return count, version


def con_conteo(spec: TableSpec, count: int) -> TableSpec:
    """Geometria derivada del `count` real de un contenedor derivado.

    La spec formula la geometria en terminos del `count` del header, no como
    constantes: el area de registros es `header + stride*count` y, en las
    tablas de texto, el pool arranca justo despues (SPEC-NAMES §11.2). Aqui se
    aplica ese mismo desplazamiento al `pool_start` declarado, lo que conserva
    su anomalia conocida (`#4638` arranca 1 B despues de lo esperado).
    Sin cambio de `count` devuelve el propio spec: para el dump canonico no hay
    geometria nueva.
    """
    if count == spec.count:
        return spec
    pool = spec.pool_start
    if pool is not None:
        pool = pool + spec.stride * (count - spec.count)
    return replace(spec, count=count, pool_start=pool)


def read_row(spec: TableSpec, blob: bytes, row: int) -> bytes:
    start = spec.row_offset(row)
    return blob[start:start + spec.stride]


def parse_pool(spec: TableSpec, blob: bytes) -> tuple[list[bytes], bool]:
    """Trocea la zona de texto en slots NUL-delimitados.

    Devuelve (slots, terminado). `terminado` dice si el ultimo slot acaba en NUL
    (si no, hay una cola sin terminador que se conserva al reserializar).
    """
    if spec.pool_start is None:
        raise TableError("#%d: no es una tabla de texto" % spec.index)
    if len(blob) < spec.pool_start:
        raise TableError("#%d: payload de %d B y el pool empieza en %d"
                         % (spec.index, len(blob), spec.pool_start))
    pool = blob[spec.pool_start:]
    slots: list[bytes] = []
    pos = 0
    while True:
        end = pool.find(b"\x00", pos)
        if end < 0:
            slots.append(pool[pos:])
            return slots, False
        slots.append(pool[pos:end])
        pos = end + 1
        if pos >= len(pool):
            return slots, True


def build_pool(slots: list[bytes], terminated: bool = True) -> bytes:
    out = b"".join(slot + b"\x00" for slot in slots[:-1])
    out += slots[-1] + (b"\x00" if terminated else b"")
    return out


def slot_ordinal(spec: TableSpec, text_id: int, slot: int = SINGULAR_SLOT) -> int:
    """Ordinal del slot de `(id, slot)` segun docs/SPEC-NAMES.md §6."""
    if not TEXT_FIRST_ID <= text_id <= spec.count + 3:
        raise TableError("id de texto %d fuera de rango (%d..%d) de #%d"
                         % (text_id, TEXT_FIRST_ID, spec.count + 3, spec.index))
    if not 0 <= slot < SLOTS_PER_BLOCK:
        raise TableError("slot %d fuera de 0..%d" % (slot, SLOTS_PER_BLOCK - 1))
    return SLOTS_PER_BLOCK * (text_id - TEXT_FIRST_ID) + slot


def block_slots(spec: TableSpec, slots: list[bytes], text_id: int) -> list[bytes]:
    """Los slots del bloque de 6 de `text_id`, en orden `+0` -> `+5`.

    Devuelve los que existan: el ultimo bloque del pool puede estar truncado (en
    `#4650` hay 18.003 slots para 18.006 huecos, docs/SPEC-NAMES.md §6), y el
    criterio de `expect_sha256` hashea lo que hay, no huecos vacios inventados.
    """
    if not TEXT_FIRST_ID <= text_id <= spec.count + 3:
        raise TableError("id de texto %d fuera de rango (%d..%d) de #%d"
                         % (text_id, TEXT_FIRST_ID, spec.count + 3, spec.index))
    base = SLOTS_PER_BLOCK * (text_id - TEXT_FIRST_ID)
    return slots[base:base + SLOTS_PER_BLOCK]


def block_sha256(spec: TableSpec, slots: list[bytes], text_id: int) -> str:
    """sha256 del bloque de `text_id` — criterio de `expect_sha256`.

    Contrato (docs/MOD-FORMAT.md §3.1): se hashea la **concatenacion de los bytes
    de los slots del bloque, en orden `+0` -> `+5`, tal cual estan en el pool**.
    Sin terminador NUL, sin separador, sin normalizacion Unicode y sin
    recodificar. Hexadecimal en minusculas, 64 caracteres.
    """
    return hashlib.sha256(b"".join(block_slots(spec, slots, text_id))).hexdigest()

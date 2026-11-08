#!/usr/bin/env python3
"""Lector del contenedor `kidsobjdb` (`_DOK0000` / `IDOK0000`). Solo lectura.

Un `.fdata` del romfs guarda varias bases `kidsobjdb` (4.144 entradas de tipo
`0x20A6A0BB` en el build 655360). Cada una es un fichero autocontenido: cabecera
`_DOK0000`, un recuento de registros y los registros, uno tras otro, con firma
`IDOK0000`. La mayor de todas —50.152.112 B, 294.939 registros— es la que lee
este modulo por defecto.

Formato, medido sobre el dump v2.0.1a (build 655360). Todos los campos son
little endian y todo esta alineado a 4 B:

    Cabecera del fichero (28 B; `header_size` puede crecer):
      +0x00  char[8]  "_DOK0000"
      +0x08  u32      header_size          28 en las 4.144 bases del dump
      +0x0C  u32      record_header_size   24 en las 4.144
      +0x10  u32      count                registros que siguen
      +0x14  bytes    cola de la cabecera  header_size - 20 B (8 en las 4.144, sin
                                           interpretar: cambia entre ficheros)

    Registro (`record_header_size` = 24 B de cabecera + cola variable):
      +0x00  char[8]  "IDOK0000"
      +0x08  u32      size       bytes del registro, cabecera incluida, %4 == 0
      +0x0C  u32      id         unico en la base (294.939 distintos de 294.939)
      +0x10  u32      type_hash  tipo del objeto (190 valores distintos)
      +0x14  u32      n_pairs    numero de pares que siguen
      +0x18  par[n_pairs]        12 B cada uno: kind, n_values, hash
      cola:   para cada par, en orden, n_values x u32 (su valor)

La aritmetica de la cola es la comprobacion que cierra el formato: para los
294.939 registros de la base mayor se cumple, byte a byte,

    24 + 12 * n_pairs + 4 * sum(n_values) == size

y la suma de los `size` de todos los registros agota el fichero exactamente
(0 B de resto). Si algo no cuadra, `iter_records` **falla** en vez de devolver
basura: un lector que adivina convierte un error de formato en un dato falso.

Limite conocido y medido: en otras bases `kidsobjdb` del mismo dump aparecen
`kind` distintos de 5 (4, 8, 10, ...) y ahi la carga **no** es de 4 B por valor;
el registro deja de cuadrar y el lector lo dice con su offset. La base mayor que
cubre esta tarjeta usa 4 B por valor en el 100 % de sus 1.474.636 pares.

Solo stdlib. Nada de este modulo escribe: es lectura sobre bytes ya
descomprimidos por `pokopia.fdata`.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Iterator

from . import fdata

#: Firma del fichero.
FILE_MAGIC = b"_DOK0000"

#: Firma de cada registro.
RECORD_MAGIC = b"IDOK0000"

#: Cabecera minima del fichero: firma + 3 u32 (`header_size`, `record_header_size`, `count`).
MIN_HEADER_SIZE = 20

#: Cabecera fija de un registro: firma + `size`, `id`, `type_hash`, `n_pairs`.
RECORD_HEADER_SIZE = 24

#: Bytes de un par (kind, n_values, hash).
PAIR_SIZE = 12

#: Tipo `kidsobjdb` en la tabla de tipos del `.fdata`.
KIDSOBJDB_KTID = 0x20A6A0BB

_HEADER = struct.Struct("<8sIII")
_RECORD = struct.Struct("<8sIIII")
_PAIR = struct.Struct("<III")


class ObjDbError(Exception):
    """La base no se puede leer. `exit_code` lo fija la CLI."""

    exit_code = 1


class ObjDbFormatError(ObjDbError):
    """Los bytes no siguen el formato `_DOK0000`/`IDOK0000`."""


class ObjDbTruncatedError(ObjDbFormatError):
    """El blob acaba antes de donde dicen sus propios campos."""


@dataclass(frozen=True)
class Pair:
    """Un par clave/valor de un registro.

    El encargo lo llamaba trío `(hash, valor, flag)`; en el byte el orden es
    `(kind, n_values, hash)` y el valor no va dentro del trio sino en la cola del
    registro. `kind` es el que aqui ocupa el lugar del flag: en la base mayor vale
    5 en 1.474.626 de 1.474.636 pares (los otros diez: siete con 4 y tres con 8).
    Su significado esta sin confirmar y no se inventa: se expone tal cual.
    """

    kind: int
    hash: int
    values: tuple[int, ...]

    @property
    def n_values(self) -> int:
        return len(self.values)

    def as_dict(self) -> dict:
        doc = {
            "kind": self.kind,
            "hash": "0x%08x" % self.hash,
            "values": list(self.values),
            "hex": ["0x%08x" % v for v in self.values],
        }
        return doc


@dataclass(frozen=True)
class Record:
    """Un registro `IDOK0000`, con su posicion dentro del blob."""

    offset: int
    size: int
    id: int
    type_hash: int
    pairs: tuple[Pair, ...]

    @property
    def end(self) -> int:
        """Offset del registro siguiente (`offset + size`)."""
        return self.offset + self.size

    @property
    def n_pairs(self) -> int:
        return len(self.pairs)

    def as_dict(self) -> dict:
        return {
            "offset": self.offset,
            "size": self.size,
            "id": self.id,
            "type_hash": "0x%08x" % self.type_hash,
            "pairs": [p.as_dict() for p in self.pairs],
        }


@dataclass(frozen=True)
class SizeCount:
    """Una fila del reparto por tamano de registro."""

    size: int
    records: int

    def as_dict(self) -> dict:
        return {"size": self.size, "records": self.records}


@dataclass(frozen=True)
class TypeCount:
    """Una fila del reparto por `type_hash`."""

    type_hash: int
    records: int

    def as_dict(self) -> dict:
        return {"type_hash": "0x%08x" % self.type_hash, "records": self.records}


@dataclass(frozen=True)
class ObjDb:
    """Una base `kidsobjdb` ya validada, con su reparto.

    Guarda el blob y los agregados; los registros se vuelven a recorrer con
    `records()`, que es barato (0,3 s para los 294.939 de la base mayor) y evita
    materializar 1,47 millones de pares en memoria.
    """

    blob: bytes
    header_size: int
    record_header_size: int
    declared_count: int
    count: int
    pair_count: int
    trailer: bytes
    by_size: tuple[SizeCount, ...]
    by_type: tuple[TypeCount, ...]
    origin: str | None = None
    source_entry: fdata.Entry | None = None

    def records(self) -> Iterator[Record]:
        """Recorre los registros otra vez (mismo orden, misma validacion)."""
        return iter_records(self.blob)

    def records_of(self, type_hash: int) -> Iterator[Record]:
        """Registros de un `type_hash`, en orden de fichero."""
        return (r for r in self.records() if r.type_hash == type_hash)

    def find(self, ident: int) -> Record | None:
        """El registro con ese `id`, o `None` si no esta."""
        for record in self.records():
            if record.id == ident:
                return record
        return None

    def as_dict(self) -> dict:
        doc = {
            "origin": self.origin,
            "size": len(self.blob),
            "header_size": self.header_size,
            "record_header_size": self.record_header_size,
            "declared_count": self.declared_count,
            "records": self.count,
            "pairs": self.pair_count,
            "type_hashes": len(self.by_type),
            "sizes": [s.as_dict() for s in self.by_size],
            "types": [t.as_dict() for t in self.by_type],
        }
        if self.source_entry is not None:
            doc["fdata_entry"] = self.source_entry.as_dict()
        return doc


# ---------------------------------------------------------------------------
# Recorrido y validacion
# ---------------------------------------------------------------------------

def iter_records(blob: bytes | bytearray | memoryview) -> Iterator[Record]:
    """Recorre los registros del blob validando cabecera, tamanos y cola.

    Falla (`ObjDbFormatError`) en cuanto un byte no cuadra: firma de registro,
    `size` no multiple de 4, registro que se sale del blob, pares que no caben en
    el registro, cola que no agota el `size`, o recuento final distinto del
    declarado en la cabecera. Nunca devuelve un registro a medias.
    """
    if not isinstance(blob, memoryview):
        blob = memoryview(blob)
    total = len(blob)
    if total < MIN_HEADER_SIZE:
        raise ObjDbTruncatedError(
            "%d B: no llega a la cabecera de %d B" % (total, MIN_HEADER_SIZE))
    magic, header_size, record_header_size, declared = _HEADER.unpack_from(blob, 0)
    if magic != FILE_MAGIC:
        raise ObjDbFormatError(
            "no empieza por %r (empieza por %r)" % (FILE_MAGIC, bytes(magic)))
    if header_size < MIN_HEADER_SIZE or header_size > total:
        raise ObjDbFormatError(
            "cabecera de %d B: fuera de rango (%d B de blob)" % (header_size, total))
    if record_header_size < RECORD_HEADER_SIZE:
        raise ObjDbFormatError(
            "cabecera de registro de %d B, menor que la fija de %d B"
            % (record_header_size, RECORD_HEADER_SIZE))

    pos = header_size
    hechos = 0
    while pos < total:
        if pos + record_header_size > total:
            raise ObjDbTruncatedError(
                "registro %d en 0x%x: cabecera cortada (%d B de blob)"
                % (hechos, pos, total))
        magic, size, ident, type_hash, n_pairs = _RECORD.unpack_from(blob, pos)
        if magic != RECORD_MAGIC:
            raise ObjDbFormatError(
                "registro %d en 0x%x: se esperaba %r y hay %r"
                % (hechos, pos, RECORD_MAGIC, bytes(magic)))
        if size % 4:
            raise ObjDbFormatError(
                "registro %d en 0x%x: size %d no es multiplo de 4"
                % (hechos, pos, size))
        if size < record_header_size:
            raise ObjDbFormatError(
                "registro %d en 0x%x: size %d < cabecera %d"
                % (hechos, pos, size, record_header_size))
        fin = pos + size
        if fin > total:
            raise ObjDbTruncatedError(
                "registro %d en 0x%x: dice %d B y solo quedan %d"
                % (hechos, pos, size, total - pos))
        inicio_pares = pos + record_header_size
        fin_pares = inicio_pares + PAIR_SIZE * n_pairs
        if fin_pares > fin:
            raise ObjDbFormatError(
                "registro %d en 0x%x (id %d): %d pares no caben en %d B"
                % (hechos, pos, ident, n_pairs, size))

        pares = []
        carga = fin_pares
        for i in range(n_pairs):
            kind, n_values, clave = _PAIR.unpack_from(blob, inicio_pares + PAIR_SIZE * i)
            fin_valores = carga + 4 * n_values
            if fin_valores > fin:
                raise ObjDbFormatError(
                    "registro %d en 0x%x (id %d), par %d: %d valores se salen del registro"
                    % (hechos, pos, ident, i, n_values))
            valores = struct.unpack_from("<%dI" % n_values, blob, carga)
            carga = fin_valores
            pares.append(Pair(kind=kind, hash=clave, values=valores))
        if carga != fin:
            raise ObjDbFormatError(
                "registro %d en 0x%x (id %d): quedan %d B sin cuadrar despues de los pares "
                "(%d B de registro, %d pares, 4 B por valor)"
                % (hechos, pos, ident, fin - carga, size, n_pairs))

        yield Record(offset=pos, size=size, id=ident, type_hash=type_hash,
                     pairs=tuple(pares))
        hechos += 1
        pos = fin

    if hechos != declared:
        raise ObjDbFormatError(
            "la cabecera declara %d registros y el fichero tiene %d" % (declared, hechos))


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------

def parse_blob(blob: bytes | bytearray | memoryview,
               *, origin: str | None = None,
               source_entry: fdata.Entry | None = None) -> ObjDb:
    """Valida el blob entero y devuelve la base con su reparto por tamano y tipo."""
    por_tamano: dict[int, int] = {}
    por_tipo: dict[int, int] = {}
    pares = 0
    total = 0
    for record in iter_records(blob):
        por_tamano[record.size] = por_tamano.get(record.size, 0) + 1
        por_tipo[record.type_hash] = por_tipo.get(record.type_hash, 0) + 1
        pares += record.n_pairs
        total += 1

    _, header_size, record_header_size, declared = _HEADER.unpack_from(blob, 0)
    return ObjDb(
        blob=bytes(blob),
        header_size=header_size,
        record_header_size=record_header_size,
        declared_count=declared,
        count=total,
        pair_count=pares,
        trailer=bytes(blob[MIN_HEADER_SIZE:header_size]),
        by_size=tuple(SizeCount(size=s, records=n) for s, n in
                      sorted(por_tamano.items(), key=lambda kv: (-kv[1], kv[0]))),
        by_type=tuple(TypeCount(type_hash=t, records=n) for t, n in
                      sorted(por_tipo.items(), key=lambda kv: (-kv[1], kv[0]))),
        origin=origin,
        source_entry=source_entry,
    )


# ---------------------------------------------------------------------------
# Localizacion dentro de los .fdata y carga
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """Un `kidsobjdb` localizado dentro de un `.fdata`, sin descomprimir."""

    fdata: str
    entry: fdata.Entry

    @property
    def size(self) -> int:
        return self.entry.uncompressed_size

    def as_dict(self) -> dict:
        return {"fdata": self.fdata, "entry": self.entry.as_dict(),
                "size": self.size}


def find_sources(root: str) -> list[Source]:
    """Todos los `kidsobjdb` de los `.fdata` bajo `root`, del mayor al menor.

    Recorre solo cabeceras: no descomprime nada. `root` puede ser la carpeta
    romfs, cualquier carpeta con `.fdata` dentro, o un `.fdata` suelto.
    """
    hallados = []
    for ruta in fdata.find_fdata(root):
        for entry in fdata.iter_entries(ruta):
            if entry.type_ktid == KIDSOBJDB_KTID:
                hallados.append(Source(fdata=ruta, entry=entry))
    if not hallados:
        raise ObjDbError(
            "no hay ningun kidsobjdb (tipo 0x%08x) en %s" % (KIDSOBJDB_KTID, root))
    return sorted(hallados, key=lambda s: (-s.size, s.fdata, s.entry.offset))


def largest(root: str) -> Source:
    """El `kidsobjdb` mayor bajo `root`: el de 50.152.112 B en el dump 655360."""
    return find_sources(root)[0]


def read_source(source: Source) -> bytes:
    """Descomprime (o copia) el payload del `kidsobjdb` localizado."""
    return fdata.read_entry_from(source.fdata, source.entry)


def _looks_like_blob(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(FILE_MAGIC)) == FILE_MAGIC


def load(source: str | os.PathLike | bytes | bytearray | memoryview) -> ObjDb:
    """Carga una base `kidsobjdb`.

    Acepta:

    * `bytes`/`bytearray`/`memoryview` ya descomprimidos;
    * la carpeta romfs (o cualquier carpeta con `.fdata`): lee el `kidsobjdb`
      mayor que encuentre, que es el de esta tarjeta;
    * un `.fdata` suelto: el `kidsobjdb` mayor de ese fichero;
    * un fichero que empieza por `_DOK0000`: se lee tal cual, sin pasar por el
      `.fdata` (util para lo que ya extrajo `pkp fdata extract`).

    El dump del juego no se toca: todo es lectura.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        return parse_blob(source, origin="<bytes>")

    ruta = os.path.abspath(os.path.expanduser(str(source)))
    if os.path.isdir(ruta) or ruta.lower().endswith(fdata.FDATA_SUFFIX):
        elegido = largest(ruta)
        blob = read_source(elegido)
        # `origin` es el `.fdata` del que salieron los bytes, no la carpeta pedida:
        # es el dato que el informe tiene que poder citar.
        return parse_blob(blob, origin=elegido.fdata, source_entry=elegido.entry)
    if not os.path.isfile(ruta):
        raise ObjDbError("no existe: %s" % ruta)
    if _looks_like_blob(ruta):
        with open(ruta, "rb") as fh:
            return parse_blob(fh.read(), origin=ruta)
    raise ObjDbError(
        "%s no empieza por %r y no es un contenedor %s\n"
        "  pasa la carpeta romfs, un .fdata o un kidsobjdb ya extraido"
        % (ruta, FILE_MAGIC, fdata.FDATA_SUFFIX))


__all__ = [
    "FILE_MAGIC",
    "KIDSOBJDB_KTID",
    "MIN_HEADER_SIZE",
    "PAIR_SIZE",
    "RECORD_HEADER_SIZE",
    "RECORD_MAGIC",
    "ObjDb",
    "ObjDbError",
    "ObjDbFormatError",
    "ObjDbTruncatedError",
    "Pair",
    "Record",
    "SizeCount",
    "Source",
    "TypeCount",
    "find_sources",
    "iter_records",
    "largest",
    "load",
    "parse_blob",
    "read_source",
]

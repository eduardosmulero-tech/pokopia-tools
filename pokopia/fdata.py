#!/usr/bin/env python3
"""Lector y escritor minimo de los contenedores `.fdata` del romfs (PDRK/IDRK).

Los `.fdata` son 24 ficheros del romfs (5,06 GB en el build 655360) que hasta
ahora eran caja negra: dentro van las escenas, las texturas, los sonidos y las
bases de objetos (`kidsobjdb`). Este modulo recorRe sus cabeceras, clasifica cada
entrada por `type_ktid` y descomprime su payload.

Formato (medido sobre el dump v2.0.1a; ver
`FDATA-PDRK-DESCIFRADO-2026-11-08.md` en el proyecto `dev/Switch2`):

    PDRK0000            (8 B)  magic
    u32 = 0x10          (4 B)  tamano de cabecera
    u32 = 0             (4 B)
    --- a partir de 0x10, entradas concatenadas, cada una alineada a 16 B ---
    IDRK0000            (8 B)  magic
    <3Q>                       entry_size, compressed_size, uncompressed_size
    <4I>                       entry_type, name_hash, type_ktid, flags
    metadata            (entry_size - compressed_size - 0x30) B
    datos:
      compressed_size == uncompressed_size -> crudo, tal cual
      si no, en trozos hasta llenar uncompressed_size:
         flags & 0x100000:  zsize = <I>            (4 B)   # modo FETH
         else:              zsize = <H> + 8 B      (10 B)  # lo normal aqui
         chunk = zlib.decompress(zsize bytes)

**Los tres tamanos son `u64`.** Leidos como `u32` el campo de 10 B del trozo
queda invisible y no descomprime nada: es la trampa que costo una hora y la
razon de que `tests/test_fdata.py` la fije con una entrada de mas de 4 GiB
declarada por campos.

Procedencia del formato (documentado por la comunidad, contrastado con el dump,
sin codigo copiado): `eArmada8/yumia_fdata_tools` -> `yumia_mod_lib.py`
(`read_fdata_file`, `read_fdata_for_idrk_information`), `bnnm/vgm-tools`
(`koei_rdb_fdata_file.bms`) y `DeathChaos25/fdata_dump`.

Solo stdlib. **Leer es lo de por defecto**: ninguna funcion de lectura escribe.
La escritura vive al final del modulo (`write_entry`, `repack`, `inject`) y solo
corre si se pide; `repack` pasa por `paths.guard_writable()`, asi que el dump del
juego sigue siendo de solo lectura por construccion. Forma de escritura, limites
y medidas en `docs/ESCRITURA-FDATA.md`.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, Iterator

PDRK_MAGIC = b"PDRK0000"
IDRK_MAGIC = b"IDRK0000"

#: Cabecera del contenedor: magic + 2 x u32 (tamano de cabecera, ceros).
FDATA_HEADER_SIZE = 0x10

#: Cabecera de una entrada: magic + 3 x u64 + 4 x u32.
ENTRY_HEADER_SIZE = 0x30

#: Alineacion de cada entrada dentro del fichero.
ENTRY_ALIGN = 0x10

#: Flag que cambia el tamano del campo `zsize` de cada trozo (modo "FETH").
FETH_FLAG = 0x100000

#: Sufijo de los ficheros que trata este modulo.
FDATA_SUFFIX = ".fdata"

#: Cabecera de entrada ya decodificada: 8 + 3*8 + 4*4 = 48 B.
ENTRY_HEADER = struct.Struct("<8s3Q4I")

#: Tabla `type_ktid` -> nombre, tomada de `yumia_mod_lib.py` (eArmada8) y
#: contrastada con el dump: los 26 tipos que aparecen aqui salen nombrados.
KTID_TYPES: dict[int, str] = {
    0x0BD05B27: "mit",
    0x0D34474D: "srst",
    0x133D2C3B: "sid",
    0x17614AF5: "g1mx",
    0x1AB40AE8: "oid",
    0x1FDCAA40: "kidstask",
    0x20A6A0BB: "kidsobjdb",
    0x27BC54B7: "rigbin",
    0x2BCC0C02: "g1frani",
    0x4D0102AC: "g1em",
    0x4F16D0EF: "kts",
    0x5153729B: "mtl",
    0x54738C76: "g1co",
    0x5599AA51: "kscl",
    0x563BDEF1: "g1m",
    0x56D8DEDA: "sid",
    0x56EFE45C: "grp",
    0x5C3E543C: "swg",
    0x6DBD6EA6: "mit",
    0x6FA91671: "g1a",
    0x757347E0: "bpo",
    0x786DCD84: "g1n",
    0x79C724C2: "g1p",
    0x7BCD279F: "g1s",
    0x82945A44: "lsqtree",
    0x8E39AA37: "ktid",
    0x9CB3A4B6: "oidex",
    0xA027E46B: "mov",
    0xA8D88566: "g1cox",
    0xAD57EBBA: "g1t_new",
    0xAFBEC60C: "g1t",
    0xB097D41F: "g1e",
    0xB0A14534: "sgcbin",
    0xB1630F51: "kidsrender",
    0xB340861A: "mtl",
    0xBBD39F2D: "srsa",
    0xBBF9B49D: "grp",
    0xBE144B78: "ktid",
    0xBF6B52C7: "name",
    0xD7F47FB1: "efpl",
    0xDBCB74A9: "oid",
    0xE6A3C3BB: "oidex",
    0xED410290: "kts",
    0xF13845EF: "sclshape",
    0xF20DE437: "texinfo",
}


class FdataError(Exception):
    """El `.fdata` no se puede leer con este formato. `exit_code` lo fija la CLI."""

    exit_code = 1


class FdataFormatError(FdataError):
    """Los bytes no siguen el formato PDRK/IDRK (firma, alineacion, trozo)."""


class FdataTruncatedError(FdataFormatError):
    """El fichero acaba antes de donde dicen sus propios campos."""


def align_up(value: int, alignment: int = ENTRY_ALIGN) -> int:
    """Sube `value` al siguiente multiplo de `alignment`."""
    resto = value % alignment
    return value if resto == 0 else value + (alignment - resto)


def type_name(ktid: int) -> str:
    """Nombre corto del tipo, o su hex si es uno de los que aun no tiene nombre."""
    return KTID_TYPES.get(ktid, "0x%08x" % ktid)


def parse_type(text: str) -> int:
    """Acepta `kidsobjdb` o `0x20a6a0bb`; devuelve el `type_ktid`."""
    limpio = text.strip().lower()
    if limpio.startswith("0x"):
        try:
            return int(limpio, 16)
        except ValueError:
            raise FdataError("tipo no interpretable como hex: %r" % text) from None
    for ktid, nombre in KTID_TYPES.items():
        if nombre == limpio:
            return ktid
    raise FdataError(
        "tipo desconocido: %r\n"
        "  se acepta un nombre de %s o un hex tipo 0x20a6a0bb"
        % (text, ", ".join(sorted(set(KTID_TYPES.values())))))


@dataclass(frozen=True)
class Entry:
    """Cabecera de una entrada IDRK, con su posicion dentro del fichero."""

    offset: int
    entry_size: int
    compressed_size: int
    uncompressed_size: int
    entry_type: int
    name_hash: int
    type_ktid: int
    flags: int

    @property
    def type_name(self) -> str:
        return type_name(self.type_ktid)

    @property
    def metadata_size(self) -> int:
        """Bytes entre la cabecera y los datos (lo que el juego no documenta)."""
        size = self.entry_size - self.compressed_size - ENTRY_HEADER_SIZE
        if size < 0:
            raise FdataFormatError(
                "entrada en 0x%x: entry_size %d < compressed_size %d + 0x30"
                % (self.offset, self.entry_size, self.compressed_size))
        return size

    @property
    def data_offset(self) -> int:
        return self.offset + ENTRY_HEADER_SIZE + self.metadata_size

    @property
    def end_offset(self) -> int:
        """Offset de la entrada siguiente: fin declarado, alineado a 16 B."""
        return align_up(self.offset + self.entry_size)

    @property
    def is_compressed(self) -> bool:
        return self.compressed_size != self.uncompressed_size

    @property
    def chunk_header_size(self) -> int:
        return 4 if self.flags & FETH_FLAG else 10

    def as_dict(self) -> dict:
        return {
            "offset": self.offset,
            "type": self.type_name,
            "type_ktid": "0x%08x" % self.type_ktid,
            "entry_size": self.entry_size,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
            "name_hash": "0x%08x" % self.name_hash,
            "entry_type": self.entry_type,
            "flags": self.flags,
            "metadata_size": self.metadata_size,
        }


def iter_entries(path: str) -> Iterator[Entry]:
    """Recorre las cabeceras de un `.fdata` sin descomprimir nada (barato).

    Es lo que usa `pkp fdata stat`: 79.710 cabeceras en unos segundos.
    """
    total = os.path.getsize(path)
    with open(path, "rb", buffering=0) as fh:
        head = fh.read(FDATA_HEADER_SIZE)
        if len(head) < FDATA_HEADER_SIZE:
            raise FdataFormatError(
                "%s: %d B, no llega a la cabecera PDRK de %d B"
                % (path, total, FDATA_HEADER_SIZE))
        if head[:8] != PDRK_MAGIC:
            raise FdataFormatError(
                "%s: no empieza por PDRK0000 (empieza por %r)" % (path, head[:8]))
        header_size = struct.unpack_from("<I", head, 8)[0]
        if header_size < FDATA_HEADER_SIZE:
            raise FdataFormatError(
                "%s: cabecera de %d B, menor que la firma" % (path, header_size))
        pos = header_size
        while pos + ENTRY_HEADER_SIZE <= total:
            fh.seek(pos)
            raw = fh.read(ENTRY_HEADER_SIZE)
            if len(raw) < ENTRY_HEADER_SIZE:
                raise FdataTruncatedError(
                    "%s: entrada en 0x%x cortada (%d de %d B)"
                    % (path, pos, len(raw), ENTRY_HEADER_SIZE))
            (magic, entry_size, cmp_size, unc_size,
             entry_type, name_hash, type_ktid, flags) = ENTRY_HEADER.unpack(raw)
            if magic != IDRK_MAGIC:
                raise FdataFormatError(
                    "%s: en 0x%x se esperaba IDRK0000 y hay %r" % (path, pos, magic))
            if entry_size < ENTRY_HEADER_SIZE:
                raise FdataFormatError(
                    "%s: entrada en 0x%x con entry_size %d (minimo 0x30)"
                    % (path, pos, entry_size))
            entry = Entry(pos, entry_size, cmp_size, unc_size,
                          entry_type, name_hash, type_ktid, flags)
            yield entry
            siguiente = entry.end_offset
            if siguiente <= pos:  # pragma: no cover - cubierto por entry_size >= 0x30
                raise FdataFormatError(
                    "%s: la entrada en 0x%x no avanza (fin 0x%x)"
                    % (path, pos, siguiente))
            pos = siguiente


def read_entry(fh, entry: Entry, limit: int | None = None) -> bytes:
    """Descomprime el payload de `entry`. `fh` es el `.fdata` ya abierto en rb.

    `limit` corta en cuanto el payload descomprimido llega a esos bytes: sirve
    para leer solo la cabecera de miles de entradas (censo de animaciones) sin
    descomprimir los 697 MB enteros. No valida el tamano final en ese caso.
    """
    if not entry.is_compressed:
        fh.seek(entry.data_offset)
        data = fh.read(entry.uncompressed_size if limit is None
                       else min(limit, entry.uncompressed_size))
        if limit is None and len(data) != entry.uncompressed_size:
            raise FdataTruncatedError(
                "entrada 0x%08x en 0x%x: cruda, se esperaban %d B y hay %d"
                % (entry.name_hash, entry.offset, entry.uncompressed_size, len(data)))
        return data

    fh.seek(entry.data_offset)
    blob = fh.read(entry.compressed_size)
    if len(blob) != entry.compressed_size:
        raise FdataTruncatedError(
            "entrada 0x%08x en 0x%x: se esperaban %d B comprimidos y hay %d"
            % (entry.name_hash, entry.offset, entry.compressed_size, len(blob)))

    cabecera = entry.chunk_header_size
    salida = bytearray()
    pos = 0
    while len(salida) < entry.uncompressed_size:
        if pos + cabecera > len(blob):
            raise FdataTruncatedError(
                "entrada 0x%08x en 0x%x: sin cabecera de trozo en +0x%x (%d B fuera)"
                % (entry.name_hash, entry.offset, pos, len(salida)))
        if entry.flags & FETH_FLAG:
            zsize = struct.unpack_from("<I", blob, pos)[0]
        else:
            zsize = struct.unpack_from("<H", blob, pos)[0]
        pos += cabecera
        if pos + zsize > len(blob):
            raise FdataTruncatedError(
                "entrada 0x%08x en 0x%x: trozo de %d B en +0x%x se sale del payload"
                % (entry.name_hash, entry.offset, zsize, pos))
        try:
            trozo = zlib.decompress(blob[pos:pos + zsize])
        except zlib.error as exc:
            raise FdataFormatError(
                "entrada 0x%08x en 0x%x: el trozo en +0x%x no descomprime (%s)"
                % (entry.name_hash, entry.offset, pos, exc)) from None
        pos += zsize
        salida += trozo
        if limit is not None and len(salida) >= limit:
            return bytes(salida[:limit])
    if limit is None and len(salida) != entry.uncompressed_size:
        raise FdataFormatError(
            "entrada 0x%08x en 0x%x: los trozos dan %d B y se declaran %d"
            % (entry.name_hash, entry.offset, len(salida), entry.uncompressed_size))
    return bytes(salida)


def read_entry_from(path: str, entry: Entry) -> bytes:
    """Igual que `read_entry`, abriendo y cerrando el fichero."""
    with open(path, "rb", buffering=0) as fh:
        return read_entry(fh, entry)


def find_fdata(root: str) -> list[str]:
    """Todos los `.fdata` bajo `root` (recursivo), ordenados y sin duplicados."""
    if os.path.isfile(root):
        if not root.lower().endswith(FDATA_SUFFIX):
            raise FdataError("no es un .fdata: %s" % root)
        return [root]
    if not os.path.isdir(root):
        raise FdataError("no existe la carpeta: %s" % root)
    hallados: list[str] = []
    for carpeta, _, ficheros in os.walk(root):
        for nombre in ficheros:
            if nombre.lower().endswith(FDATA_SUFFIX):
                hallados.append(os.path.join(carpeta, nombre))
    if not hallados:
        raise FdataError(
            "no hay ningun %s bajo %s\n"
            "  apunta a la carpeta romfs del juego (contiene motor_asset_re/...)"
            % (FDATA_SUFFIX, root))
    return sorted(hallados)


@dataclass(frozen=True)
class TypeCount:
    """Una fila de `pkp fdata stat`: cuantas entradas hay de un `type_ktid`."""

    ktid: int
    entries: int
    compressed: int
    uncompressed_bytes: int

    @property
    def name(self) -> str:
        return type_name(self.ktid)

    def as_dict(self) -> dict:
        return {
            "type": self.name,
            "type_ktid": "0x%08x" % self.ktid,
            "entries": self.entries,
            "compressed": self.compressed,
            "uncompressed_bytes": self.uncompressed_bytes,
        }


@dataclass(frozen=True)
class FileCount:
    """Una fila por fichero: es lo que permite detectar un `.fdata` raro."""

    path: str
    entries: int
    size: int

    def as_dict(self, root: str | None = None) -> dict:
        nombre = os.path.relpath(self.path, root) if root else self.path
        return {"file": nombre, "entries": self.entries, "size": self.size}


@dataclass(frozen=True)
class ScanResult:
    """Recuento por tipo de todos los `.fdata` de una carpeta."""

    root: str
    files: tuple[FileCount, ...]
    types: tuple[TypeCount, ...]

    @property
    def total_entries(self) -> int:
        return sum(f.entries for f in self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "files": len(self.files),
            "entries": self.total_entries,
            "size": self.total_size,
            "types": [t.as_dict() for t in self.types],
            "per_file": [f.as_dict(self.root) for f in self.files],
        }


def scan(paths: Iterable[str], root: str | None = None) -> ScanResult:
    """Recorre solo cabeceras y agrega por `type_ktid` (sin descomprimir)."""
    ficheros: list[FileCount] = []
    entradas: dict[int, int] = {}
    comprimidas: dict[int, int] = {}
    crudo: dict[int, int] = {}
    rutas = list(paths)
    for path in rutas:
        n = 0
        for entry in iter_entries(path):
            n += 1
            entradas[entry.type_ktid] = entradas.get(entry.type_ktid, 0) + 1
            if entry.is_compressed:
                comprimidas[entry.type_ktid] = comprimidas.get(entry.type_ktid, 0) + 1
            crudo[entry.type_ktid] = crudo.get(entry.type_ktid, 0) + entry.uncompressed_size
        ficheros.append(FileCount(path, n, os.path.getsize(path)))
    tipos = tuple(
        TypeCount(ktid, n, comprimidas.get(ktid, 0), crudo.get(ktid, 0))
        for ktid, n in sorted(entradas.items(), key=lambda kv: (-kv[1], kv[0])))
    if root is None:
        root = os.path.commonpath(rutas) if rutas else ""
    return ScanResult(root, tuple(ficheros), tipos)


def extract(reader_path: str, wanted: int, out_dir: str) -> list[tuple[Entry, str]]:
    """Escribe las entradas de tipo `wanted` como `<name_hash>.<tipo>`.

    Devuelve (entrada, ruta escrita) para que la CLI pueda informar. Volver a
    lanzarlo sobre la misma carpeta reescribe los mismos bytes (idempotente); lo
    que no hace es pisar dos entradas distintas con el mismo nombre: eso aborta.
    """
    from . import paths as pkp_paths  # local: evita ciclo al importar el paquete

    pkp_paths.guard_writable(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    escritos: list[tuple[Entry, str]] = []
    vistos: set[str] = set()
    with open(reader_path, "rb", buffering=0) as fh:
        for entry in iter_entries(reader_path):
            if entry.type_ktid != wanted:
                continue
            destino = os.path.join(
                out_dir, "0x%08x.%s" % (entry.name_hash, entry.type_name))
            if destino in vistos:
                raise FdataError(
                    "dos entradas %s con name_hash 0x%08x: %s se pisaria\n"
                    "  en el dump medido no pasa (79.710 entradas, 0 repetidas); "
                    "extrae fichero a fichero para quedarte con las dos"
                    % (entry.type_name, entry.name_hash, destino))
            vistos.add(destino)
            pkp_paths.guard_writable(destino)
            datos = read_entry(fh, entry)
            with open(destino, "wb") as salida:
                salida.write(datos)
            escritos.append((entry, destino))
    return escritos


# ---------------------------------------------------------------------------
# Escritura (contrato nuevo: se pide a mano, nunca por defecto)
# ---------------------------------------------------------------------------

#: Tamano descomprimido de cada trozo en la forma comprimida. Medido en la
#: entrada de 350.772 B del dump: 22 trozos, 21 de 16.384 B y el ultimo de 6.708.
CHUNK_SIZE = 0x4000

#: Nivel de zlib de los `.fdata` del juego. Medido: recomprimir el payload
#: original en trozos de 16.384 B a nivel 6 reproduce los 22 trozos byte a byte
#: (2.160 B frente a 2.162 del original, los 2 B de cola son relleno); nivel 9
#: acierta 0 de 22. Ojo: `LD_C0_R.BIN` usa nivel 9, no es la misma convencion.
CHUNK_ZLIB_LEVEL = 6


class FdataWriteError(FdataError):
    """No se puede escribir esa entrada, esa ruta o ese contenedor."""


@dataclass(frozen=True)
class RepackResult:
    """Lo que ha quedado en disco al reescribir un `.fdata`."""

    origen: str
    destino: str
    entries: int
    size: int
    sha256: str
    replaced: tuple[int, ...]

    def as_dict(self) -> dict:
        return {
            "source": os.path.abspath(self.origen),
            "out": os.path.abspath(self.destino),
            "entries": self.entries,
            "size": self.size,
            "sha256": self.sha256,
            "replaced": ["0x%08x" % h for h in self.replaced],
        }


@dataclass(frozen=True)
class InjectResult:
    """Resultado de `inject`: la entrada de antes, la de despues y el fichero."""

    origen: str
    destino: str
    route: str
    before: Entry
    entry_size: int
    compressed_size: int
    uncompressed_size: int
    metadata_size: int
    flags: int
    repack: RepackResult

    def as_dict(self) -> dict:
        return {
            "route": self.route,
            "source": os.path.abspath(self.origen),
            "out": os.path.abspath(self.destino),
            "name_hash": "0x%08x" % self.before.name_hash,
            "type": self.before.type_name,
            "entry_type": self.before.entry_type,
            "before": self.before.as_dict(),
            "after": {
                "offset": self.before.offset,
                "entry_size": self.entry_size,
                "compressed_size": self.compressed_size,
                "uncompressed_size": self.uncompressed_size,
                "metadata_size": self.metadata_size,
                "flags": self.flags,
            },
            "size_before": os.path.getsize(self.origen),
            "size_after": self.repack.size,
            "sha256": self.repack.sha256,
        }


def entry_metadata(path: str, entry: Entry) -> bytes:
    """Los bytes opacos entre la cabecera y los datos (`metadata_size`)."""
    if entry.metadata_size == 0:
        return b""
    with open(path, "rb", buffering=0) as fh:
        fh.seek(entry.offset + ENTRY_HEADER_SIZE)
        datos = fh.read(entry.metadata_size)
    if len(datos) != entry.metadata_size:
        raise FdataTruncatedError(
            "entrada 0x%08x en 0x%x: se esperaban %d B de metadatos y hay %d"
            % (entry.name_hash, entry.offset, entry.metadata_size, len(datos)))
    return datos


def write_entry(payload: bytes, *, metadata: bytes = b"", entry_type: int = 0,
                name_hash: int = 0, type_ktid: int = 0, flags: int = 0,
                stored: bytes | None = None) -> bytes:
    """Bytes de **una** entrada IDRK completa: cabecera + metadatos + datos.

    No escribe en disco: devuelve el bloque para que lo coloque `repack()`.

    Dos formas, las dos que el contenedor acepta (forma medida en
    `docs/ESCRITURA-FDATA.md`):

    * **cruda** (`stored=None`): los datos van tal cual y los dos tamanos
      declaran lo mismo (`compressed_size == uncompressed_size`). Es la forma
      que usan las 123 entradas crudas del dump y la que escribe la herramienta
      publica `eArmada8/yumia_fdata_tools` (GPL-3.0, citada, no copiada).
    * **comprimida-preservada** (`stored=<bytes ya comprimidos>`): se guardan
      esos bytes tal cual, sin re-trocear ni recomprimir, declarando
      `uncompressed_size = len(payload)`. Sirve para reescribir una entrada con
      su payload original comprimido.
    """
    payload = bytes(payload)
    metadata = bytes(metadata)
    if not payload:
        raise FdataWriteError("payload vacio: una entrada sin datos no es valida")
    if stored is None:
        datos = payload
        comprimido = len(payload)
    else:
        datos = bytes(stored)
        comprimido = len(datos)
        if not datos:
            raise FdataWriteError("payload comprimido vacio")
        if comprimido == len(payload):
            raise FdataWriteError(
                "los bytes comprimidos miden lo mismo que los crudos (%d B): el "
                "lector los tomaria por una entrada cruda y devolveria basura; "
                "usa la forma cruda sin `stored`" % comprimido)
    entry_size = ENTRY_HEADER_SIZE + len(metadata) + len(datos)
    for nombre, valor in (("entry_type", entry_type), ("name_hash", name_hash),
                          ("type_ktid", type_ktid), ("flags", flags)):
        if not 0 <= valor <= 0xFFFFFFFF:
            raise FdataWriteError("%s fuera de u32: %r" % (nombre, valor))
    return (IDRK_MAGIC
            + struct.pack("<3Q", entry_size, comprimido, len(payload))
            + struct.pack("<4I", entry_type, name_hash, type_ktid, flags)
            + metadata
            + datos)


def chunked_size(payload: bytes, *, level: int = CHUNK_ZLIB_LEVEL,
                 chunk: int = CHUNK_SIZE, header_size: int = 10) -> int:
    """Cuanto ocuparia `payload` en la forma comprimida del juego.

    Sirve para presupuesto (¿cabe en el hueco?), no para escribir: la cabecera
    de trozo tiene 8 B cuyo contenido **no** esta resuelto (`docs/ESCRITURA-FDATA.md`).
    """
    if chunk <= 0:
        raise FdataWriteError("trozo de %d B" % chunk)
    total = 0
    for inicio in range(0, len(payload), chunk):
        total += header_size + len(zlib.compress(payload[inicio:inicio + chunk], level))
    return total


def find_entry(path: str, name_hash: int) -> Entry:
    """La entrada con ese `name_hash`, exigiendo que sea unica."""
    halladas = [e for e in iter_entries(path) if e.name_hash == name_hash]
    if not halladas:
        raise FdataWriteError(
            "0x%08x no esta en %s (%d entradas)"
            % (name_hash, path, sum(1 for _ in iter_entries(path))))
    if len(halladas) > 1:
        raise FdataWriteError(
            "0x%08x aparece %d veces en %s: no se puede elegir por hash"
            % (name_hash, len(halladas), path))
    return halladas[0]


def _validar_reemplazo(name_hash: int, blob: bytes, origen: str) -> None:
    """El bloque tiene que ser una entrada IDRK entera y con el mismo hash."""
    if len(blob) < ENTRY_HEADER_SIZE:
        raise FdataWriteError(
            "0x%08x: el bloque tiene %d B y la cabecera sola son 0x30"
            % (name_hash, len(blob)))
    (magic, entry_size, _cmp, _unc,
     _tipo, hash_bloque, _ktid, _flags) = ENTRY_HEADER.unpack_from(blob)
    if magic != IDRK_MAGIC:
        raise FdataWriteError("0x%08x: el bloque no empieza por IDRK0000" % name_hash)
    if entry_size != len(blob):
        raise FdataWriteError(
            "0x%08x: la cabecera declara entry_size %d y el bloque mide %d"
            % (name_hash, entry_size, len(blob)))
    if hash_bloque != name_hash:
        raise FdataWriteError(
            "0x%08x: el bloque trae name_hash 0x%08x" % (name_hash, hash_bloque))


def repack(origen: str, destino: str,
           reemplazos: dict[int, bytes] | None = None) -> RepackResult:
    """Reescribe `origen` en `destino` con las entradas de `reemplazos` cambiadas.

    Las entradas que no estan en `reemplazos` se copian **byte a byte** desde el
    origen, relleno de alineacion incluido; las cambiadas se escriben tal cual
    vienen y se rellena con ceros hasta el siguiente multiplo de 16. Cabecera
    `PDRK0000` + `<u32 header_size, u32 0>` (el tercer campo del dump es 0;
    `yumia_fdata_tools` escribe ahi el tamano del fichero — convencion suya, no
    se copia).

    Sin reemplazos, el destino sale identico al origen byte a byte (es el
    criterio de aceptacion C1 de la tarjeta que pidio este escritor).

    Escribe en `<destino>.tmp` y lo renombra al final: si el proceso se corta,
    no queda un `.fdata` a medias y el origen nunca se toca. Se niega a escribir
    dentro del romfs (`paths.guard_writable`) y a escribir sobre el origen.
    """
    from . import paths as pkp_paths  # local: evita ciclo al importar el paquete

    cambios = dict(reemplazos or {})
    if pkp_paths.norm(origen) == pkp_paths.norm(destino):
        raise FdataWriteError(
            "origen y destino son el mismo fichero: %s\n"
            "  escribe una copia nueva con --out" % origen)
    pkp_paths.guard_writable(destino)

    total = os.path.getsize(origen)
    entradas = list(iter_entries(origen))
    if not entradas:
        raise FdataWriteError("%s no tiene ninguna entrada" % origen)
    with open(origen, "rb") as fh:
        cabecera = fh.read(FDATA_HEADER_SIZE)
        header_size = struct.unpack_from("<I", cabecera, 8)[0]
        extra = b""
        if header_size > FDATA_HEADER_SIZE:
            fh.seek(FDATA_HEADER_SIZE)
            extra = fh.read(header_size - FDATA_HEADER_SIZE)
            if len(extra) != header_size - FDATA_HEADER_SIZE:
                raise FdataTruncatedError(
                    "%s: la cabecera declara %d B y no llega" % (origen, header_size))

    por_hash = {e.name_hash: e for e in entradas}
    for name_hash, blob in cambios.items():
        if name_hash not in por_hash:
            raise FdataWriteError(
                "0x%08x no esta en %s: no hay nada que reemplazar" % (name_hash, origen))
        _validar_reemplazo(name_hash, blob, origen)

    ultima = entradas[-1]
    fin_declarado = ultima.offset + ultima.entry_size
    if fin_declarado > total:
        raise FdataTruncatedError(
            "%s: la ultima entrada acaba en %d y el fichero mide %d"
            % (origen, fin_declarado, total))

    tmp = destino + ".tmp"
    escrito = 0
    digest = hashlib.sha256()
    try:
        with open(origen, "rb", buffering=0) as src, open(tmp, "wb") as dst:

            def emitir(blob: bytes) -> None:
                nonlocal escrito
                dst.write(blob)
                digest.update(blob)
                escrito += len(blob)

            emitir(PDRK_MAGIC + struct.pack("<2I", header_size, 0) + extra)
            for i, entry in enumerate(entradas):
                es_ultima = i == len(entradas) - 1
                reemplazo = cambios.get(entry.name_hash)
                if reemplazo is not None:
                    emitir(reemplazo)
                    if not es_ultima and len(reemplazo) % ENTRY_ALIGN:
                        emitir(b"\x00" * (ENTRY_ALIGN - len(reemplazo) % ENTRY_ALIGN))
                    continue
                # Tramo del origen tal cual: entrada + su relleno. La ultima no
                # lleva relleno porque el fichero acaba en su entry_size (medido:
                # 84.073.115 B, no 84.073.120).
                fin = fin_declarado if es_ultima else entry.end_offset
                src.seek(entry.offset)
                datos = src.read(fin - entry.offset)
                if len(datos) != fin - entry.offset:
                    raise FdataTruncatedError(
                        "%s: entrada 0x%08x en 0x%x cortada (%d de %d B)"
                        % (origen, entry.name_hash, entry.offset,
                           len(datos), fin - entry.offset))
                emitir(datos)
            cola = total - fin_declarado
            if cola > 0:
                src.seek(fin_declarado)
                emitir(src.read(cola))
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    return RepackResult(origen, destino, len(entradas), escrito,
                        digest.hexdigest(), tuple(sorted(cambios)))


def inject(origen: str, destino: str, name_hash: int, payload: bytes, *,
           route: str = "raw", flags: int | None = None) -> InjectResult:
    """Mete `payload` en la entrada `name_hash` y escribe `destino`.

    `route="raw"` (la recomendada y la unica implementada): entrada cruda, con
    `compressed_size == uncompressed_size == len(payload)`, los metadatos y los
    campos `entry_type`/`name_hash`/`type_ktid` copiados del original y los
    `flags` tambien: en el dump **las 123 entradas crudas llevan 0x400000**, los
    mismos que las comprimidas, asi que conservarlos es lo medido (se puede
    forzar otro valor con `flags=`).

    `route="slot"`: parche en sitio sin desplazar nada. **No implementada**: solo
    comprueba el presupuesto y explica el motivo medido (los 8 B de la cabecera
    del trozo siguen sin resolver).
    """
    if route not in ("raw", "slot"):
        raise FdataWriteError("ruta desconocida: %r (raw|slot)" % (route,))
    payload = bytes(payload)
    entry = find_entry(origen, name_hash)
    if route == "slot":
        ocuparia = chunked_size(payload)
        if ocuparia > entry.compressed_size:
            raise FdataWriteError(
                "no cabe en la ranura: el payload nuevo ocuparia %d B "
                "comprimido (nivel %d, trozos de %d B) y el hueco de 0x%08x "
                "son %d B; faltan %d B"
                % (ocuparia, CHUNK_ZLIB_LEVEL, CHUNK_SIZE, name_hash,
                   entry.compressed_size, ocuparia - entry.compressed_size))
        raise FdataWriteError(
            "ruta slot no implementada: cabe (%d de %d B) pero cada trozo "
            "lleva 8 B en su cabecera que no son ninguna de las funciones "
            "probadas (crc32, crc32c, adler32, md5, sha1, sha256, blake2b, "
            "xxh64) ni funcion de solo el contenido del trozo (medido: dos "
            "trozos distintos comparten los mismos 8 B). Escribirlos a cero es "
            "una apuesta, no una medida: usa --route raw. Ver "
            "docs/ESCRITURA-FDATA.md"
            % (ocuparia, entry.compressed_size))

    blob = write_entry(payload,
                       metadata=entry_metadata(origen, entry),
                       entry_type=entry.entry_type,
                       name_hash=entry.name_hash,
                       type_ktid=entry.type_ktid,
                       flags=entry.flags if flags is None else flags)
    resultado = repack(origen, destino, {name_hash: blob})
    return InjectResult(
        origen, destino, route, entry,
        entry_size=len(blob),
        compressed_size=len(blob) - ENTRY_HEADER_SIZE - entry.metadata_size,
        uncompressed_size=len(payload),
        metadata_size=entry.metadata_size,
        flags=entry.flags if flags is None else flags,
        repack=resultado)


__all__ = [
    "CHUNK_SIZE",
    "CHUNK_ZLIB_LEVEL",
    "ENTRY_ALIGN",
    "ENTRY_HEADER",
    "ENTRY_HEADER_SIZE",
    "FDATA_HEADER_SIZE",
    "FDATA_SUFFIX",
    "FETH_FLAG",
    "IDRK_MAGIC",
    "KTID_TYPES",
    "PDRK_MAGIC",
    "Entry",
    "FdataError",
    "FdataFormatError",
    "FdataTruncatedError",
    "FdataWriteError",
    "FileCount",
    "InjectResult",
    "RepackResult",
    "ScanResult",
    "TypeCount",
    "align_up",
    "chunked_size",
    "entry_metadata",
    "extract",
    "find_entry",
    "find_fdata",
    "inject",
    "iter_entries",
    "parse_type",
    "read_entry",
    "read_entry_from",
    "repack",
    "scan",
    "type_name",
    "write_entry",
]

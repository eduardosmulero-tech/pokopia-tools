#!/usr/bin/env python3
"""pkp_pack.py - lector y EMPAQUETADOR del contenedor de datos de Pokemon Pokopia.

Este modulo es la capa **formato** del kit: se mueve aqui desde `pkp_pack.py`
(tarjeta t_df136634) sin cambios de comportamiento; `pkp_pack.py` queda como
envoltorio de compatibilidad de la CLI. Ver `docs/ARQUITECTURA-KIT.md` §2.

Contenedor: LI_C0_R.IDX (indice, 32 bytes por entrada) + LD_C0_R.BIN (datos).

Formato (verificado sobre las 12.298 entradas de la copia v2.0.1a, ver INFORME.md):

  IDX: N entradas de 32 bytes, little endian:
      int64 offset | int64 rawSize | int64 packedSize | int64 flag
      flag 0 = datos crudos (rawSize == packedSize, sin cabecera)
      flag 1 = entrada comprimida por bloques (ver abajo)
      rawSize == 0 y packedSize == 0 = entrada vacia: ocupa CERO bytes; su
      `offset` es simplemente la posicion de escritura en ese momento.

  Entrada comprimida (empieza en `offset`):
      u32 blockSize   - tamano de bloque descomprimido (0x10000, 0x20000, 0x80000)
      u32 nBlocks     - == ceil(rawSize / blockSize)
      u32 rawSize     - == rawSize del indice
      u32 table[nBlocks] - tamano del SLOT ocupado por cada bloque en el BIN
      pos = align128(12 + nBlocks*4)   <- primer bloque
      por bloque:
          si es comprimido: [u32 len][zlib(len)]  -> slot = len + 4
          si va crudo:      [datos del bloque]    -> slot = longitud del bloque
          siguiente bloque: pos = align128(pos + slot)
      el recorrido termina exactamente en packedSize.

  Un bloque se distingue por su contenido: el slot empieza con un u32 `len`
  seguido de un flujo zlib que descomprime con eof y da exactamente el tamano
  esperado. Si no, es crudo y su slot mide justo el tamano esperado.
  (En la copia real: 8.834 bloques comprimidos y 19 crudos, todos ellos colas
  diminutas de 16..18 bytes donde el zlib no comprime.)

  Las entradas se alinean a 256 bytes dentro del BIN; el relleno es cero.

Uso:
    python pkp_pack.py verify   LI_C0_R.IDX LD_C0_R.BIN
    python pkp_pack.py extract  LI_C0_R.IDX 983 salida.bin [--bin LD_C0_R.BIN]
    python pkp_pack.py unpack-all LI_C0_R.IDX LD_C0_R.BIN build/blobs
    python pkp_pack.py pack     build/blobs out.IDX out.BIN
    python pkp_pack.py repack   LI_C0_R.IDX LD_C0_R.BIN out.IDX out.BIN
    python pkp_pack.py roundtrip LI_C0_R.IDX LD_C0_R.BIN [--out-tag nombre]

Solo stdlib. El compresor por defecto busca una zlib "stock" en el sistema
(la DLL de Git para Windows, zlib 1.3.2) porque reproduce byte a byte los
flujos del juego; si no la encuentra cae al modulo zlib del interprete, que
en esta maquina es zlib-ng y produce flujos distintos (validos, pero no
identicos). Ver INFORME.md, seccion C3.

Referencia de formato de lectura: PokoHex de berichan (GPL-3.0)
https://github.com/berichan/PokoHex -> PokoHex.Parsing/GameArchive.cs
No se ha copiado codigo de ese proyecto: este fichero se ha escrito a partir
de la inspeccion directa del contenedor descrita arriba.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
import zlib

INDEX_ENTRY = struct.Struct("<qqqq")
INDEX_ENTRY_SIZE = INDEX_ENTRY.size          # 32
BLOCK_ALIGN = 128
ENTRY_ALIGN = 256
DEFAULT_BLOCK_SIZE = 0x10000
KNOWN_BLOCK_SIZES = (0x10000, 0x20000, 0x80000)
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = "pkp-blobs-v1"

__all__ = [
    "INDEX_ENTRY", "INDEX_ENTRY_SIZE", "BLOCK_ALIGN", "ENTRY_ALIGN",
    "DEFAULT_BLOCK_SIZE", "KNOWN_BLOCK_SIZES", "MANIFEST_NAME", "MANIFEST_FORMAT",
    "align_up", "Compressor", "StdlibCompressor", "StockZlibCompressor",
    "candidate_zlib_dlls", "get_compressor", "IndexEntry", "read_index",
    "index_to_bytes", "FormatError", "unpack_entry", "read_file", "read_container",
    "pack_compressed", "pack_empty", "pack_entry", "ContainerWriter",
    "write_container", "compare_payloads", "entry_block_size", "verify", "blob_name", "unpack_all",
    "pack_dir", "rebuild_with", "roundtrip", "sibling_bin", "main",
    "zlib", "struct", "os",
]


def align_up(n: int, a: int) -> int:
    return (n + a - 1) // a * a


# --------------------------------------------------------------------------
# Compresores
# --------------------------------------------------------------------------

class Compressor:
    """Interfaz minima: compress(bytes) -> bytes con flujo zlib completo."""

    name = "abstract"

    def version(self) -> str:
        raise NotImplementedError

    def compress(self, data: bytes) -> bytes:
        raise NotImplementedError

    def describe(self) -> str:
        return "%s (zlib %s)" % (self.name, self.version())


class StdlibCompressor(Compressor):
    """Modulo zlib del interprete. En esta maquina es zlib-ng en modo compat."""

    name = "stdlib"

    def __init__(self, level: int = 9):
        self.level = level

    def version(self) -> str:
        return zlib.ZLIB_RUNTIME_VERSION

    def compress(self, data: bytes) -> bytes:
        return zlib.compress(data, self.level)


class StockZlibCompressor(Compressor):
    """zlib stock via ctypes (compress2: windowBits 15, memLevel 8, estrategia normal).

    compress2(level=9) produce exactamente los mismos flujos que el build
    original del juego en las 12.298 entradas medidas.
    """

    name = "stock"

    def __init__(self, dll_path: str, level: int = 9):
        self.dll_path = dll_path
        self.level = level
        self.lib = ctypes.WinDLL(dll_path) if os.name == "nt" else ctypes.CDLL(dll_path)
        lib = self.lib
        lib.zlibVersion.restype = ctypes.c_char_p
        lib.zlibVersion.argtypes = []
        lib.compressBound.restype = ctypes.c_ulong
        lib.compressBound.argtypes = [ctypes.c_ulong]
        lib.compress2.restype = ctypes.c_int
        lib.compress2.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_int,
        ]
        self._version = lib.zlibVersion().decode("ascii", "replace")

    def version(self) -> str:
        return self._version

    def compress(self, data: bytes) -> bytes:
        bound = int(self.lib.compressBound(len(data)))
        dest = ctypes.create_string_buffer(bound)
        dest_len = ctypes.c_ulong(bound)
        rc = self.lib.compress2(dest, ctypes.byref(dest_len), data, len(data), self.level)
        if rc != 0:
            raise RuntimeError("compress2 devolvio %d" % rc)
        return dest.raw[: dest_len.value]

    def describe(self) -> str:
        return "%s (zlib %s) %s" % (self.name, self.version(), self.dll_path)


def candidate_zlib_dlls() -> list[str]:
    paths = []
    env = os.environ.get("PKP_ZLIB_DLL")
    if env:
        paths.append(env)
    if os.name == "nt":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            r"C:\Program Files",
            r"C:\Program Files (x86)",
        ):
            if not base:
                continue
            paths.append(os.path.join(base, "Git", "mingw64", "bin", "zlib1.dll"))
            paths.append(os.path.join(base, "Git", "usr", "bin", "zlib1.dll"))
    else:
        for p in ("/usr/lib/x86_64-linux-gnu/libz.so.1", "/lib/x86_64-linux-gnu/libz.so.1",
                  "/usr/lib/libz.dylib"):
            paths.append(p)
    seen, out = set(), []
    for p in paths:
        key = os.path.normcase(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def get_compressor(choice: str = "auto", level: int = 9) -> Compressor:
    """auto: prefiere una zlib stock real; stdlib: la del interprete; stock: exige DLL."""
    if choice in ("auto", "stock"):
        for path in candidate_zlib_dlls():
            if os.path.isfile(path):
                try:
                    comp = StockZlibCompressor(path, level)
                except OSError:
                    continue
                run = comp.version()
                if run.startswith("1.3.1.zlib-ng") or "zlib-ng" in run:
                    continue  # no es stock, no sirve para identidad
                return comp
        if choice == "stock":
            raise RuntimeError("no encuentro una zlib stock; define PKP_ZLIB_DLL")
    return StdlibCompressor(level)


# --------------------------------------------------------------------------
# Indice
# --------------------------------------------------------------------------

class IndexEntry:
    __slots__ = ("offset", "raw_size", "packed_size", "flag")

    def __init__(self, offset: int, raw_size: int, packed_size: int, flag: int):
        self.offset = offset
        self.raw_size = raw_size
        self.packed_size = packed_size
        self.flag = flag

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.offset, self.raw_size, self.packed_size, self.flag)

    def __repr__(self) -> str:
        return "IndexEntry(offset=%d, raw=%d, packed=%d, flag=%d)" % self.as_tuple()


def read_index(path: str) -> list[IndexEntry]:
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) % INDEX_ENTRY_SIZE:
        raise ValueError("%s: tamano %d no es multiplo de %d"
                         % (path, len(blob), INDEX_ENTRY_SIZE))
    return [IndexEntry(*INDEX_ENTRY.unpack_from(blob, i))
            for i in range(0, len(blob), INDEX_ENTRY_SIZE)]


def index_to_bytes(entries: list[IndexEntry]) -> bytes:
    out = bytearray(len(entries) * INDEX_ENTRY_SIZE)
    for i, ent in enumerate(entries):
        INDEX_ENTRY.pack_into(out, i * INDEX_ENTRY_SIZE, *ent.as_tuple())
    return bytes(out)


# --------------------------------------------------------------------------
# Desempaquetar
# --------------------------------------------------------------------------

class FormatError(ValueError):
    """El contenedor no cuadra con el formato documentado."""


def _decode_block(chunk: bytes, want: int, where: str) -> tuple[bytes, str]:
    """Devuelve (datos, 'comp'|'raw'). Acepta el slot tal cual, sin recortar."""
    if len(chunk) > 4 and chunk[4] == 0x78:
        dec = zlib.decompressobj()
        data = None
        try:
            data = dec.decompress(chunk[4:]) + dec.flush()
        except zlib.error:
            data = None
        if data is not None and dec.eof and len(data) == want:
            return data, "comp"
    if len(chunk) == want:
        return chunk, "raw"
    raise FormatError("%s: bloque de %d bytes no interpretable (esperados %d)"
                      % (where, len(chunk), want))


def unpack_entry(bin_data: bytes, entry: IndexEntry, index: int = -1,
                 stats: dict | None = None) -> bytes:
    """Blob descomprimido de una entrada (b'' para las entradas vacias)."""
    where = "entrada #%d" % index
    if entry.packed_size == 0:
        if entry.raw_size != 0:
            raise FormatError("%s: packedSize=0 pero rawSize=%d" % (where, entry.raw_size))
        return b""
    if entry.offset < 0 or entry.offset + entry.packed_size > len(bin_data):
        raise FormatError("%s: rango %d..%d fuera del BIN (%d bytes)"
                          % (where, entry.offset, entry.offset + entry.packed_size,
                             len(bin_data)))
    if entry.flag == 0:
        if entry.raw_size != entry.packed_size:
            raise FormatError("%s: flag=0 con rawSize=%d != packedSize=%d"
                              % (where, entry.raw_size, entry.packed_size))
        if stats is not None:
            stats["raw_entries"] = stats.get("raw_entries", 0) + 1
        return bin_data[entry.offset:entry.offset + entry.raw_size]
    if entry.flag != 1:
        raise FormatError("%s: flag desconocido %d" % (where, entry.flag))

    base = entry.offset
    block_size, n_blocks, raw_size = struct.unpack_from("<III", bin_data, base)
    if raw_size != entry.raw_size:
        raise FormatError("%s: rawSize de cabecera %d != indice %d"
                          % (where, raw_size, entry.raw_size))
    if block_size == 0 or block_size > 0x1000000:
        raise FormatError("%s: blockSize absurdo %d" % (where, block_size))
    if n_blocks != -(-raw_size // block_size):
        raise FormatError("%s: nBlocks %d != ceil(%d/%d)"
                          % (where, n_blocks, raw_size, block_size))
    table = struct.unpack_from("<%dI" % n_blocks, bin_data, base + 12)

    pos = align_up(12 + n_blocks * 4, BLOCK_ALIGN)
    out = []
    for b in range(n_blocks):
        slot = table[b]
        want = min(block_size, raw_size - b * block_size)
        if pos + slot > entry.packed_size:
            raise FormatError("%s: bloque %d se sale del slot (pos=%d slot=%d packed=%d)"
                              % (where, b, pos, slot, entry.packed_size))
        chunk = bin_data[base + pos:base + pos + slot]
        data, kind = _decode_block(chunk, want, "%s bloque %d" % (where, b))
        if stats is not None:
            key = "blocks_" + kind
            stats[key] = stats.get(key, 0) + 1
            sizes = stats.setdefault("block_sizes", {})
            sizes[block_size] = sizes.get(block_size, 0) + 1
        out.append(data)
        pos = align_up(pos + slot, BLOCK_ALIGN)
    if pos != entry.packed_size:
        raise FormatError("%s: recorrido acaba en %d, packedSize=%d"
                          % (where, pos, entry.packed_size))
    blob = b"".join(out)
    if len(blob) != raw_size:
        raise FormatError("%s: %d bytes descomprimidos != %d" % (where, len(blob), raw_size))
    return blob


def read_file(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def read_container(idx_path: str, bin_path: str) -> tuple[list[IndexEntry], bytes]:
    return read_index(idx_path), read_file(bin_path)


# --------------------------------------------------------------------------
# Empaquetar
# --------------------------------------------------------------------------

def pack_compressed(blob: bytes, block_size: int, compressor: Compressor,
                    raw_threshold: bool = True) -> bytes:
    """Serializa `blob` como entrada comprimida (cabecera + tabla + bloques)."""
    if not blob:
        raise ValueError("no se empaqueta un blob vacio como entrada comprimida")
    if block_size <= 0:
        raise ValueError("blockSize invalido %d" % block_size)
    n_blocks = -(-len(blob) // block_size)
    header = struct.pack("<III", block_size, n_blocks, len(blob))
    table = bytearray(n_blocks * 4)
    body = bytearray()
    pos = align_up(12 + n_blocks * 4, BLOCK_ALIGN)
    body.extend(b"\x00" * (pos - len(header) - len(table)))
    for b in range(n_blocks):
        chunk = blob[b * block_size:(b + 1) * block_size]
        comp = compressor.compress(chunk)
        if raw_threshold and len(comp) + 4 >= len(chunk):
            slot = chunk
            payload = chunk            # bloque crudo: sin prefijo de longitud
        else:
            slot = struct.pack("<I", len(comp)) + comp
            payload = slot
        struct.pack_into("<I", table, b * 4, len(slot))
        body.extend(slot)
        nxt = align_up(pos + len(slot), BLOCK_ALIGN)
        body.extend(b"\x00" * (nxt - pos - len(slot)))
        pos = nxt
    return header + bytes(table) + bytes(body)


def pack_empty(block_size: int = DEFAULT_BLOCK_SIZE) -> bytes:
    """Entrada vacia serializada como cabecera con nBlocks=0 (128 bytes tras alinear)."""
    header = struct.pack("<III", block_size, 0, 0)
    return header + b"\x00" * (align_up(len(header), BLOCK_ALIGN) - len(header))


def pack_entry(blob: bytes, flag: int = 1, block_size: int = DEFAULT_BLOCK_SIZE,
               compressor: Compressor | None = None,
               raw_threshold: bool = True,
               empty_header: bool = False) -> tuple[bytes, int]:
    """Devuelve (bytes que van al BIN, flag efectivo) para un blob."""
    if not blob:
        return (pack_empty(block_size) if empty_header else b""), flag
    if flag == 0:
        return blob, 0
    if compressor is None:
        compressor = get_compressor("auto")
    return pack_compressed(blob, block_size, compressor, raw_threshold), 1


class ContainerWriter:
    """Construye BIN+IDX de forma incremental (streaming, sin tener 250 MB en RAM)."""

    def __init__(self, bin_path: str, compressor: Compressor):
        self.fh = open(bin_path, "wb")
        self.compressor = compressor
        self.entries: list[IndexEntry] = []
        self.pos = 0

    def add(self, blob: bytes, flag: int = 1, block_size: int = DEFAULT_BLOCK_SIZE,
            empty_header: bool = False) -> None:
        offset = align_up(self.pos, ENTRY_ALIGN)
        if offset > self.pos:
            self.fh.write(b"\x00" * (offset - self.pos))
            self.pos = offset
        if not blob:
            packed = pack_empty(block_size) if empty_header else b""
        elif flag == 0:
            packed = blob
        else:
            packed = pack_compressed(blob, block_size, self.compressor)
            flag = 1
        self.fh.write(packed)
        self.pos += len(packed)
        self.entries.append(IndexEntry(offset, len(blob), len(packed), flag))

    def add_slot(self, packed: bytes, raw_size: int, flag: int) -> None:
        """Copia un slot ya empaquetado tal cual (sin recomprimir).

        Se usa para conservar byte a byte las entradas que no se editan: el
        slot original ya cumple el formato y su tamano no cambia.
        """
        offset = align_up(self.pos, ENTRY_ALIGN)
        if offset > self.pos:
            self.fh.write(b"\x00" * (offset - self.pos))
            self.pos = offset
        self.fh.write(packed)
        self.pos += len(packed)
        self.entries.append(IndexEntry(offset, raw_size, len(packed), flag))

    def close(self, idx_path: str) -> list[IndexEntry]:
        self.fh.flush()
        os.fsync(self.fh.fileno())
        self.fh.close()
        with open(idx_path, "wb") as fh:
            fh.write(index_to_bytes(self.entries))
        return self.entries


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------

def verify(idx_path: str, bin_path: str, verbose: bool = True) -> dict:
    entries = read_index(idx_path)
    with open(bin_path, "rb") as fh:
        bin_size = os.fstat(fh.fileno()).st_size
    problems: list[tuple[int, str]] = []
    stats: dict = {}
    flags: dict[int, int] = {}

    if bin_size == 0:
        problems.append((-1, "BIN vacio"))

    prev_off = -1
    n_empty = 0
    total_raw = 0
    total_packed = 0
    with open(bin_path, "rb") as fh:
        for i, ent in enumerate(entries):
            flags[ent.flag] = flags.get(ent.flag, 0) + 1
            total_raw += ent.raw_size
            total_packed += ent.packed_size
            if ent.offset % ENTRY_ALIGN:
                problems.append((i, "offset %d no alineado a %d" % (ent.offset, ENTRY_ALIGN)))
            if ent.offset < prev_off:
                problems.append((i, "offset %d retrocede (anterior %d)" % (ent.offset, prev_off)))
            if ent.offset + ent.packed_size > bin_size:
                problems.append((i, "entrada se sale del BIN"))
                continue
            if ent.packed_size == 0:
                n_empty += 1
                prev_off = ent.offset
                continue
            # relleno entre entradas
            if prev_off >= 0:
                gap = ent.offset - prev_off
                if gap > 0:
                    fh.seek(prev_off)
                    if any(fh.read(gap)):
                        problems.append((i, "relleno no cero antes del offset %d" % ent.offset))
            fh.seek(ent.offset)
            chunk = fh.read(ent.packed_size)
            try:
                unpack_entry(chunk, IndexEntry(0, ent.raw_size, ent.packed_size, ent.flag),
                             index=i, stats=stats)
            except FormatError as exc:
                problems.append((i, str(exc)))
            prev_off = ent.offset + ent.packed_size
        # cola del fichero
        if prev_off >= 0 and prev_off != bin_size:
            problems.append((-1, "el BIN no acaba en la ultima entrada: %d != %d"
                             % (prev_off, bin_size)))

    result = {
        "entries": len(entries),
        "bin_size": bin_size,
        "idx_size": len(entries) * INDEX_ENTRY_SIZE,
        "flags": flags,
        "empty_entries": n_empty,
        "total_raw": total_raw,
        "total_packed": total_packed,
        "problems": problems,
        **stats,
    }
    if verbose:
        print("verify %s" % idx_path)
        print("  entradas          : %d" % result["entries"])
        print("  tamano BIN        : %d" % bin_size)
        print("  flags             : %s" % flags)
        print("  entradas vacias   : %d" % n_empty)
        print("  suma rawSize      : %d" % total_raw)
        print("  suma packedSize   : %d" % total_packed)
        print("  bloques comprimidos: %d" % stats.get("blocks_comp", 0))
        print("  bloques crudos    : %d" % stats.get("blocks_raw", 0))
        print("  blockSizes usados : %s" % {hex(k): v for k, v in
                                             sorted(stats.get("block_sizes", {}).items())})
        print("  problemas         : %d" % len(problems))
        for p in problems[:20]:
            print("    #%d %s" % p)
    return result


# --------------------------------------------------------------------------
# Blobs en disco
# --------------------------------------------------------------------------

def blob_name(index: int) -> str:
    return "%05d.bin" % index


def unpack_all(idx_path: str, bin_path: str, out_dir: str, verbose: bool = True) -> int:
    entries, bin_data = read_container(idx_path, bin_path)
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"format": MANIFEST_FORMAT,
                "source_index": os.path.basename(idx_path),
                "source_bin": os.path.basename(bin_path),
                "entries": []}
    t0 = time.time()
    for i, ent in enumerate(entries):
        blob = unpack_entry(bin_data, ent, index=i)
        path = os.path.join(out_dir, blob_name(i))
        if blob:
            with open(path, "wb") as fh:
                fh.write(blob)
        elif os.path.exists(path):
            os.remove(path)
        info = {"i": i, "flag": ent.flag, "raw_size": ent.raw_size, "block_size": None,
                "empty_header": bool(ent.raw_size == 0 and ent.packed_size > 0)}
        if ent.flag == 1 and ent.packed_size:
            info["block_size"] = struct.unpack_from("<I", bin_data, ent.offset)[0]
        manifest["entries"].append(info)
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=0)
    if verbose:
        print("unpack-all: %d blobs en %s (%.1f s)"
              % (len(entries), out_dir, time.time() - t0))
    return len(entries)


def pack_dir(src_dir: str, out_idx: str, out_bin: str, compressor: Compressor,
             verbose: bool = True) -> list[IndexEntry]:
    manifest_path = os.path.join(src_dir, MANIFEST_NAME)
    meta = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("format") != MANIFEST_FORMAT:
            raise ValueError("manifest con formato desconocido: %r" % doc.get("format"))
        meta = {item["i"]: item for item in doc["entries"]}
        indices = sorted(meta)
    else:
        indices = sorted(int(name[:-4]) for name in os.listdir(src_dir)
                         if name.endswith(".bin") and name[:-4].isdigit())
    if not indices:
        raise ValueError("%s: no hay blobs ni %s" % (src_dir, MANIFEST_NAME))

    t0 = time.time()
    writer = ContainerWriter(out_bin, compressor)
    try:
        for i in indices:
            path = os.path.join(src_dir, blob_name(i))
            blob = read_file(path) if os.path.exists(path) else b""
            info = meta.get(i, {})
            flag = info.get("flag", 1)
            block_size = info.get("block_size") or DEFAULT_BLOCK_SIZE
            empty_header = bool(info.get("empty_header", False))
            want = info.get("raw_size")
            if want is not None and want != len(blob):
                raise ValueError("%s: %d bytes en disco, el manifest dice %d"
                                 % (path, len(blob), want))
            writer.add(blob, flag=flag, block_size=block_size, empty_header=empty_header)
    finally:
        entries = writer.close(out_idx)
    if verbose:
        print("pack: %d entradas -> %s + %s (%.1f s)"
              % (len(entries), out_idx, out_bin, time.time() - t0))
    return entries


# --------------------------------------------------------------------------
# Ida y vuelta completa
# --------------------------------------------------------------------------

def rebuild_with(idx_path: str, bin_path: str, out_idx: str, out_bin: str,
                 compressor: Compressor, replace: dict[int, bytes] | None = None,
                 verbose: bool = True) -> list[IndexEntry]:
    """Reconstruye el contenedor sustituyendo los blobs indicados en `replace`."""
    entries, bin_data = read_container(idx_path, bin_path)
    replace = replace or {}
    for i in replace:
        if not 0 <= i < len(entries):
            raise IndexError("entrada %d fuera de rango (0..%d)" % (i, len(entries) - 1))
    t0 = time.time()
    writer = ContainerWriter(out_bin, compressor)
    for i, ent in enumerate(entries):
        blob = replace.get(i)
        if blob is None:
            blob = unpack_entry(bin_data, ent, index=i)
        block_size = DEFAULT_BLOCK_SIZE
        if ent.flag == 1 and ent.packed_size:
            block_size = struct.unpack_from("<I", bin_data, ent.offset)[0]
        writer.add(blob, flag=ent.flag, block_size=block_size,
                   empty_header=bool(ent.raw_size == 0 and ent.packed_size > 0 and i not in replace))
        if verbose and i and i % 4000 == 0:
            print("  ... %d/%d (%.1f s)" % (i, len(entries), time.time() - t0))
    new_entries = writer.close(out_idx)
    if verbose:
        print("rebuild: %d entradas -> %s + %s (%.1f s)"
              % (len(new_entries), out_idx, out_bin, time.time() - t0))
    return new_entries


def entry_block_size(bin_data: bytes, entry: IndexEntry) -> int:
    """blockSize que declara la propia entrada comprimida (metadato del build)."""
    if entry.flag == 1 and entry.packed_size >= 12:
        value = struct.unpack_from("<I", bin_data, entry.offset)[0]
        if value:
            return value
    return DEFAULT_BLOCK_SIZE


def write_container(idx_path: str, bin_path: str, out_idx: str, out_bin: str,
                    replace: dict[int, bytes] | None = None,
                    compressor: Compressor | None = None,
                    copy_unchanged: bool = True,
                    verbose: bool = False) -> list[IndexEntry]:
    """Escribe un contenedor nuevo sustituyendo los payloads de `replace`.

    `replace` = {indice: payload nuevo}. Con `copy_unchanged=True` (por defecto)
    las entradas no sustituidas se copian byte a byte desde el BIN original: el
    resultado solo puede diferir en los slots reempaquetados y se conserva el
    `flag` y el `blockSize` de cada entrada. Con `copy_unchanged=False` se
    reempaqueta todo (hace falta zlib stock para reproducir el build).
    """
    entries, bin_data = read_container(idx_path, bin_path)
    replace = dict(replace or {})
    for i in replace:
        if not 0 <= i < len(entries):
            raise IndexError("entrada %d fuera de rango (0..%d)" % (i, len(entries) - 1))
    compressor = compressor or get_compressor("auto")
    writer = ContainerWriter(out_bin, compressor)
    for i, ent in enumerate(entries):
        if i in replace:
            blob = replace[i]
            flag = ent.flag if (ent.flag == 0 or blob) else 1
            writer.add(blob, flag=flag, block_size=entry_block_size(bin_data, ent))
            continue
        if copy_unchanged:
            writer.add_slot(bin_data[ent.offset:ent.offset + ent.packed_size],
                            ent.raw_size, ent.flag)
            continue
        blob = unpack_entry(bin_data, ent, index=i)
        writer.add(blob, flag=ent.flag, block_size=entry_block_size(bin_data, ent),
                   empty_header=bool(ent.raw_size == 0 and ent.packed_size > 0))
    new_entries = writer.close(out_idx)
    if verbose:
        print("write_container: %d entradas -> %s + %s"
              % (len(new_entries), out_idx, out_bin))
    return new_entries


def compare_payloads(idx_a: str, bin_a: str, idx_b: str, bin_b: str,
                     limit: int = 200) -> dict:
    """Compara payload por payload dos contenedores usando el lector del modulo."""
    entries_a, data_a = read_container(idx_a, bin_a)
    entries_b, data_b = read_container(idx_b, bin_b)
    res = {"entries_a": len(entries_a), "entries_b": len(entries_b),
           "compared": 0, "identical": 0, "different_count": 0,
           "different": [], "errors": []}
    if len(entries_a) != len(entries_b):
        res["errors"].append("numero de entradas distinto: %d != %d"
                             % (len(entries_a), len(entries_b)))
    for i, (ea, eb) in enumerate(zip(entries_a, entries_b)):
        try:
            pa = unpack_entry(data_a, ea, index=i)
            pb = unpack_entry(data_b, eb, index=i)
        except FormatError as exc:
            res["errors"].append("#%d %s" % (i, exc))
            continue
        res["compared"] += 1
        if pa == pb:
            res["identical"] += 1
        else:
            res["different_count"] += 1
            if len(res["different"]) < limit:
                res["different"].append(i)
    return res


def roundtrip(idx_path: str, bin_path: str, out_idx: str, out_bin: str,
              compressor: Compressor, verbose: bool = True) -> dict:
    entries, bin_data = read_container(idx_path, bin_path)
    t0 = time.time()
    new_entries = rebuild_with(idx_path, bin_path, out_idx, out_bin, compressor, verbose=verbose)

    # C3 parcial: entrada a entrada, comparacion byte a byte de lo reempaquetado
    new_bin = read_file(out_bin)
    identical_packed = 0
    packed_diffs = []
    for i, (old, new) in enumerate(zip(entries, new_entries)):
        a = bin_data[old.offset:old.offset + old.packed_size]
        b = new_bin[new.offset:new.offset + new.packed_size]
        if a == b and old.offset == new.offset:
            identical_packed += 1
        else:
            if len(packed_diffs) < 20:
                first = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), None)
                packed_diffs.append({"i": i, "off_old": old.offset, "off_new": new.offset,
                                     "len_old": len(a), "len_new": len(b),
                                     "primer_byte_distinto": first})

    # C1: descomprimir lo reconstruido y comparar con lo original
    identicas = distintas = 0
    fallos = []
    for i, (old, new) in enumerate(zip(entries, new_entries)):
        blob_old = unpack_entry(bin_data, old, index=i)
        try:
            blob_new = unpack_entry(new_bin, new, index=i)
        except FormatError as exc:
            fallos.append((i, str(exc)))
            distintas += 1
            continue
        if blob_old == blob_new:
            identicas += 1
        else:
            distintas += 1
            fallos.append((i, "blob distinto (%d vs %d bytes)"
                           % (len(blob_new), len(blob_old))))

    old_idx = index_to_bytes(entries)
    new_idx = index_to_bytes(new_entries)
    orig_bin = bin_data
    rebuilt_bin = new_bin
    diff_bin = sum(1 for a, b in zip(orig_bin, rebuilt_bin) if a != b)
    res = {
        "entries": len(entries),
        "identicas": identicas,
        "distintas": distintas,
        "fallos": fallos[:50],
        "entradas_reempaquetadas_identicas": identical_packed,
        "diferencias_entrada": packed_diffs,
        "idx_identico": old_idx == new_idx,
        "idx_diff_bytes": sum(1 for a, b in zip(old_idx, new_idx) if a != b),
        "bin_identico": orig_bin == rebuilt_bin,
        "bin_diff_bytes": diff_bin,
        "bin_size_orig": len(orig_bin),
        "bin_size_new": len(rebuilt_bin),
        "elapsed_s": round(time.time() - t0, 1),
    }
    if verbose:
        print("roundtrip: %d entradas" % res["entries"])
        print("  C1 identicas=%d distintas=%d" % (identicas, distintas))
        for f in res["fallos"][:10]:
            print("     #%d %s" % f)
        print("  entradas identicas byte a byte en el BIN: %d/%d"
              % (identical_packed, len(entries)))
        print("  IDX identico: %s (%d bytes distintos)" % (res["idx_identico"], res["idx_diff_bytes"]))
        print("  BIN identico: %s (%d bytes distintos, %d vs %d)"
              % (res["bin_identico"], res["bin_diff_bytes"],
                 len(orig_bin), len(rebuilt_bin)))
        print("  tiempo: %.1f s" % res["elapsed_s"])
    return res


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def sibling_bin(idx_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(idx_path)), "LD_C0_R.BIN")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Contenedor LD_C0_R.BIN / LI_C0_R.IDX de Pokopia")
    ap.add_argument("--backend", choices=("auto", "stdlib", "stock"), default="auto",
                    help="compresor a usar (auto prefiere una zlib stock)")
    ap.add_argument("--level", type=int, default=9, help="nivel zlib (por defecto 9)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="recorre el contenedor y comprueba coherencia")
    p.add_argument("idx")
    p.add_argument("bin")

    p = sub.add_parser("extract", help="escribe el blob descomprimido de una entrada")
    p.add_argument("idx")
    p.add_argument("entry", type=int)
    p.add_argument("out")
    p.add_argument("--bin", dest="bin_path", default=None,
                   help="BIN de datos (por defecto LD_C0_R.BIN junto al IDX)")

    p = sub.add_parser("unpack-all", help="extrae los 12.298 blobs y un manifest")
    p.add_argument("idx")
    p.add_argument("bin")
    p.add_argument("out_dir")

    p = sub.add_parser("pack", help="reconstruye el contenedor desde un directorio de blobs")
    p.add_argument("dir")
    p.add_argument("out_idx")
    p.add_argument("out_bin")

    p = sub.add_parser("set", help="sustituye el blob de UNA entrada y reconstruye el contenedor")
    p.add_argument("idx")
    p.add_argument("bin")
    p.add_argument("entry", type=int)
    p.add_argument("blob", help="fichero con el blob descomprimido nuevo")
    p.add_argument("out_idx")
    p.add_argument("out_bin")

    p = sub.add_parser("repack", help="contenedor -> contenedor (copia y reempaqueta)")
    p.add_argument("idx")
    p.add_argument("bin")
    p.add_argument("out_idx")
    p.add_argument("out_bin")

    p = sub.add_parser("roundtrip", help="ida y vuelta completa con medicion de C1/C2/C3")
    p.add_argument("idx")
    p.add_argument("bin")
    p.add_argument("--tag", default="roundtrip")
    p.add_argument("--out-dir", default="build")

    args = ap.parse_args(argv)

    if args.cmd == "verify":
        res = verify(args.idx, args.bin)
        return 0 if not res["problems"] else 1

    if args.cmd == "extract":
        bin_path = args.bin_path or sibling_bin(args.idx)
        entries, bin_data = read_container(args.idx, bin_path)
        if not 0 <= args.entry < len(entries):
            print("entrada %d fuera de rango (0..%d)" % (args.entry, len(entries) - 1),
                  file=sys.stderr)
            return 2
        blob = unpack_entry(bin_data, entries[args.entry], index=args.entry)
        with open(args.out, "wb") as fh:
            fh.write(blob)
        print("extract #%d -> %s (%d bytes)" % (args.entry, args.out, len(blob)))
        return 0

    compressor = get_compressor(args.backend, args.level)

    if args.cmd == "unpack-all":
        unpack_all(args.idx, args.bin, args.out_dir)
        return 0

    if args.cmd == "pack":
        print("compresor: %s" % compressor.describe())
        pack_dir(args.dir, args.out_idx, args.out_bin, compressor)
        return 0

    if args.cmd == "set":
        print("compresor: %s" % compressor.describe())
        nuevo = read_file(args.blob)
        entries, bin_data = read_container(args.idx, args.bin)
        if not 0 <= args.entry < len(entries):
            print("entrada %d fuera de rango (0..%d)" % (args.entry, len(entries) - 1),
                  file=sys.stderr)
            return 2
        rebuild_with(args.idx, args.bin, args.out_idx, args.out_bin, compressor,
                     replace={args.entry: nuevo})
        res = verify(args.out_idx, args.out_bin, verbose=False)
        print("set #%d: %d -> %d bytes, contenedor reconstruido, problemas=%d"
              % (args.entry, entries[args.entry].raw_size, len(nuevo), len(res["problems"])))
        return 0 if not res["problems"] else 1

    if args.cmd == "repack":
        print("compresor: %s" % compressor.describe())
        entries, bin_data = read_container(args.idx, args.bin)
        writer = ContainerWriter(args.out_bin, compressor)
        for i, ent in enumerate(entries):
            blob = unpack_entry(bin_data, ent, index=i)
            bs = DEFAULT_BLOCK_SIZE
            if ent.flag == 1 and ent.packed_size:
                bs = struct.unpack_from("<I", bin_data, ent.offset)[0]
            writer.add(blob, flag=ent.flag, block_size=bs,
                       empty_header=bool(ent.raw_size == 0 and ent.packed_size > 0))
        writer.close(args.out_idx)
        print("repack: %d entradas -> %s + %s" % (len(entries), args.out_idx, args.out_bin))
        return 0

    if args.cmd == "roundtrip":
        print("compresor: %s" % compressor.describe())
        os.makedirs(args.out_dir, exist_ok=True)
        out_idx = os.path.join(args.out_dir, args.tag + ".IDX")
        out_bin = os.path.join(args.out_dir, args.tag + ".BIN")
        res = roundtrip(args.idx, args.bin, out_idx, out_bin, compressor)
        report = os.path.join(args.out_dir, args.tag + ".json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print("informe: %s" % report)
        return 0 if res["distintas"] == 0 else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())

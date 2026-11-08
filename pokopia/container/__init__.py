"""Capa de formato: contenedor `LI_C0_R.IDX` + `LD_C0_R.BIN`.

API publica (la que usa el resto del kit):

    read_index(path)                 -> list[IndexEntry]
    unpack_entry(bin_data, entry)    -> bytes
    pack_entry(blob, flag, ...)      -> (bytes, flag)
    write_container(idx, bin, out_idx, out_bin, replace={...})

El resto (verify, unpack_all, pack_dir, rebuild_with, roundtrip, compresores)
se reexporta sin cambios desde `pokopia.container.ktgl`, que es el antiguo
`pkp_pack.py` movido tal cual.
"""

from .ktgl import (  # noqa: F401
    BLOCK_ALIGN,
    DEFAULT_BLOCK_SIZE,
    ENTRY_ALIGN,
    INDEX_ENTRY,
    INDEX_ENTRY_SIZE,
    KNOWN_BLOCK_SIZES,
    MANIFEST_FORMAT,
    MANIFEST_NAME,
    Compressor,
    ContainerWriter,
    FormatError,
    IndexEntry,
    StdlibCompressor,
    StockZlibCompressor,
    align_up,
    blob_name,
    candidate_zlib_dlls,
    compare_payloads,
    entry_block_size,
    get_compressor,
    index_to_bytes,
    main,
    pack_compressed,
    pack_dir,
    pack_empty,
    pack_entry,
    read_container,
    read_file,
    read_index,
    rebuild_with,
    roundtrip,
    sibling_bin,
    unpack_all,
    unpack_entry,
    verify,
    write_container,
)

__all__ = [
    "BLOCK_ALIGN", "DEFAULT_BLOCK_SIZE", "ENTRY_ALIGN", "INDEX_ENTRY",
    "INDEX_ENTRY_SIZE", "KNOWN_BLOCK_SIZES", "MANIFEST_FORMAT", "MANIFEST_NAME",
    "Compressor", "ContainerWriter", "FormatError", "IndexEntry",
    "StdlibCompressor", "StockZlibCompressor", "align_up", "blob_name",
    "candidate_zlib_dlls", "compare_payloads", "entry_block_size", "get_compressor",
    "index_to_bytes", "main", "pack_compressed", "pack_dir", "pack_empty",
    "pack_entry", "read_container", "read_file", "read_index", "rebuild_with",
    "roundtrip", "sibling_bin", "unpack_all", "unpack_entry", "verify",
    "write_container",
]

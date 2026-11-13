"""Capa de esquema: que es cada campo, por tabla (no contenido del juego)."""

from .registry import (  # noqa: F401
    NAMES_LANGS,
    PLURAL_SLOT,
    SINGULAR_SLOT,
    SLOTS_PER_BLOCK,
    TABLES,
    TEXT_FIRST_ID,
    FieldSpec,
    TableError,
    TableSpec,
    block_sha256,
    block_slots,
    build_pool,
    check_header,
    con_conteo,
    get,
    known,
    parse_pool,
    read_row,
    slot_ordinal,
    table_name,
)

__all__ = [
    "NAMES_LANGS", "PLURAL_SLOT", "SINGULAR_SLOT", "SLOTS_PER_BLOCK", "TABLES",
    "TEXT_FIRST_ID", "FieldSpec", "TableError", "TableSpec", "block_sha256",
    "block_slots", "build_pool", "check_header", "con_conteo", "get", "known",
    "parse_pool", "read_row", "slot_ordinal", "table_name",
]

"""Capa de save: regiones por version, inventario, progreso y escritura con copia.

Uso rapido:

    from pokopia import save
    page = save.open_page("G00")                 # save real, solo lectura
    registros = save.read_items(page)
    parte = save.build_report(page)
    print("\\n".join(save.format_report(parte)))

Nada de este paquete lee ni escribe contenido del juego (nombres, textos, trama): solo
geometria, cifras e indices.
"""
from . import items, layout, progress, writer, zones
from .errors import SaveError, SaveFormatError, SaveReadOnlyError, SaveVersionError, SlotError
from .items import ITEM_ID_MASK, MAX_COUNT, ItemRecord, distinct_ids, occupied, read_items
from .layout import LAYOUTS, Layout, ProgressSpec, Region, get, known
from .page import DEFAULT_SAVE, PAGES, SavePage, page_path, resolve_save
from .progress import (ProgressReport, ProgressValue, build_report, confidence_lines,
                       format_report, union_ids, zone_value)
from .writer import WriteResult, backup_dir, build_raw, copy_page_to, undo, write_payload

__all__ = [
    "DEFAULT_SAVE", "ITEM_ID_MASK", "LAYOUTS", "Layout", "MAX_COUNT", "PAGES",
    "ItemRecord", "ProgressReport", "ProgressSpec", "ProgressValue", "Region",
    "SaveError", "SaveFormatError", "SavePage", "SaveReadOnlyError", "SaveVersionError",
    "SlotError", "WriteResult", "backup_dir", "build_raw", "build_report",
    "confidence_lines",
    "copy_page_to", "distinct_ids", "format_report", "get", "items", "known", "layout",
    "occupied", "open_page", "page_path", "progress", "read_items", "resolve_save",
    "undo", "union_ids", "write_payload", "writer", "zone_value", "zones",
]


def open_page(save_dir: str | None = None, page: str = "G00") -> SavePage:
    """Abre una pagina del save (por defecto PKP_SAVE o ./save, solo lectura)."""
    return SavePage.open_save(save_dir, page)

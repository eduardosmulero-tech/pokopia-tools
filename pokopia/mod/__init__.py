"""Capa de empaquetado: mod declarativo (`mod.json`), validacion, merge y apply.

Ninguna de estas funciones escribe en el dump: `apply` solo toca una copia y lo
comprueba con `pokopia.paths.guard_writable` antes de abrir nada en escritura.
"""

from .apply import apply_mod, diff_ranges, make_plan, verify_plan  # noqa: F401
from .errors import GuardError, Issue, ModError, Report, UsageError  # noqa: F401
from .manifest import (  # noqa: F401
    MOD_FORMAT,
    ContainerView,
    Edit,
    Mod,
    TextEdit,
    load_mod,
    parse_mod,
    validate,
)
from .merge import MergeResult, merge_mods  # noqa: F401

__all__ = [
    "apply_mod", "diff_ranges", "make_plan", "verify_plan", "GuardError", "Issue",
    "ModError", "Report", "UsageError", "MOD_FORMAT", "ContainerView", "Edit", "Mod",
    "TextEdit", "load_mod", "parse_mod", "validate", "MergeResult", "merge_mods",
]

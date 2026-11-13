"""Capa de empaquetado: mod declarativo (`mod.json`), validacion, merge y apply.

Ninguna de estas funciones escribe en el dump ni en el `RomFS.img`: `apply` solo
toca una copia y lo comprueba con `pokopia.paths.guard_writable` antes de abrir
nada en escritura; `install`/`uninstall` escriben en la carpeta de overlay, que es
la capa que el runtime consulta antes que el `img` (docs/MOD-OVERLAY.es.md).
"""

from .apply import apply_mod, diff_ranges, make_plan, verify_plan  # noqa: F401
from .errors import GuardError, Issue, ModError, Report, UsageError  # noqa: F401
from .manifest import (  # noqa: F401
    MOD_FORMAT,
    ContainerView,
    Edit,
    Mod,
    RomfsFile,
    TextEdit,
    load_mod,
    parse_mod,
    romfs_path_problem,
    validate,
)
from .merge import MergeResult, merge_mods  # noqa: F401
from .overlay import (  # noqa: F401
    Servido,
    comprobar_originales,
    desinstalar,
    doctor,
    empaquetar,
    estado,
    instalar,
    leer_registro,
    motivo_no_instalable,
    resolver,
)

__all__ = [
    "apply_mod", "diff_ranges", "make_plan", "verify_plan", "GuardError", "Issue",
    "ModError", "Report", "UsageError", "MOD_FORMAT", "ContainerView", "Edit", "Mod",
    "RomfsFile", "TextEdit", "load_mod", "parse_mod", "romfs_path_problem", "validate",
    "MergeResult", "merge_mods",
    "Servido", "comprobar_originales", "desinstalar", "doctor", "empaquetar", "estado",
    "instalar", "leer_registro", "motivo_no_instalable", "resolver",
]

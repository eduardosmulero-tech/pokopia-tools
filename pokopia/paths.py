"""Rutas del contenedor y utilidades de fichero.

El dump del juego es **solo lectura**: nada del kit escribe ahi. Para escribir se
trabaja siempre sobre una copia; `guard_writable()` es la puerta que lo impone.

Aqui no vive ninguna ruta de una maquina concreta: la carpeta del contenedor sale
de `PKP_ROMFS` (o de `./romfs`) y los arboles que nunca se tocan se amplian con
`PKP_PROTECTED` (rutas separadas por `os.pathsep`). Ver docs/GLOSSARY.md §5.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

IDX_NAME = "LI_C0_R.IDX"
BIN_NAME = "LD_C0_R.BIN"

#: Carpeta del contenedor por defecto, relativa al directorio de trabajo.
#: `PKP_ROMFS` la sustituye; se lee en cada llamada (ver `configured_romfs()`).
DEFAULT_ROMFS = "romfs"

#: Variable con rutas extra que el kit nunca escribe, separadas por `os.pathsep`.
PROTECTED_ENV = "PKP_PROTECTED"

#: Arboles protegidos de base. `protected_trees()` anade el romfs resuelto y los
#: que liste `PKP_PROTECTED`, leidos en cada llamada.
PROTECTED_TREES: tuple[str, ...] = (DEFAULT_ROMFS,)


class ContainerNotFound(FileNotFoundError):
    """No hay `LI_C0_R.IDX` + `LD_C0_R.BIN` en la carpeta pedida (exit 2)."""

    exit_code = 2


def configured_romfs() -> str:
    """Carpeta del contenedor configurada: `PKP_ROMFS` si esta, si no `./romfs`."""
    return os.environ.get("PKP_ROMFS") or DEFAULT_ROMFS


def protected_trees() -> tuple[str, ...]:
    """Arboles donde el kit no escribe nunca: romfs resuelto + `PKP_PROTECTED`."""
    trees = [configured_romfs(), *PROTECTED_TREES]
    extra = os.environ.get(PROTECTED_ENV, "")
    trees.extend(part for part in extra.split(os.pathsep) if part.strip())
    return tuple(dict.fromkeys(tree for tree in trees if tree))


@dataclass(frozen=True)
class Container:
    """Par IDX+BIN resuelto en disco."""

    dir: str
    idx: str
    bin: str

    def __str__(self) -> str:
        return self.dir


def resolve_container(path: str | None = None, *, must_exist: bool = True) -> Container:
    """Directorio que contiene LI_C0_R.IDX y LD_C0_R.BIN (o el IDX suelto)."""
    base = path or configured_romfs()
    base = os.path.abspath(os.path.expanduser(base))
    if os.path.isfile(base):
        base = os.path.dirname(base)
    idx = os.path.join(base, IDX_NAME)
    binp = os.path.join(base, BIN_NAME)
    if must_exist:
        missing = [p for p in (idx, binp) if not os.path.isfile(p)]
        if missing:
            raise ContainerNotFound(
                "no encuentro %s en %s\n"
                "  el kit no incluye el contenedor: apunta a la carpeta que tiene tus dos\n"
                "  ficheros con PKP_ROMFS=<carpeta>, o pasala con --container <carpeta>.\n"
                "  por defecto se busca en ./%s"
                % (", ".join(os.path.basename(p) for p in missing), base, DEFAULT_ROMFS))
    return Container(base, idx, binp)


def norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def is_protected(path: str) -> bool:
    """True si `path` cae dentro del romfs configurado o de un arbol de `PKP_PROTECTED`."""
    target = norm(path)
    for tree in protected_trees():
        if not tree:
            continue
        root = norm(tree)
        if target == root or target.startswith(root + os.sep):
            return True
    return False


def guard_writable(path: str) -> None:
    """Aborta si el destino es el dump original. Se llama antes de escribir."""
    if is_protected(path):
        raise PermissionError(
            "destino protegido (solo lectura): %s\n"
            "  el kit nunca escribe en el romfs del juego ni en los arboles de %s.\n"
            "  copia el contenedor a una carpeta de trabajo y pasa --container <copia>."
            % (path, PROTECTED_ENV))


def md5_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def container_md5(container: Container) -> dict[str, str]:
    return {BIN_NAME: md5_file(container.bin), IDX_NAME: md5_file(container.idx)}

"""De donde salen los bytes de una animacion: fichero suelto o `.fdata`.

Los 17.457 `g1a` del dump viven dentro de un unico `.fdata`
(`KIDS_PLATFORM_OUNCE/0x05d525ae.fdata`, 836 MiB, 697 MB de `g1a`
descomprimidos). Aqui esta el puente: o un `.g1a`/`.g2a` ya extraido, o el
`.fdata` y el `name_hash` de la entrada que se quiere.
"""

from __future__ import annotations

import os

from .. import fdata
from .g2a import HEADER_SIZE, AnimError, Animation, parse, peek

#: `type_ktid` con el que el contenedor llama a las animaciones.
KTID_G1A = 0x6FA91671

#: Sufijos que se aceptan como animacion ya extraida.
SUFIJOS = (".g2a", ".g1a")


def es_fdata(ruta: str) -> bool:
    return ruta.lower().endswith(".fdata")


def es_animacion(ruta: str) -> bool:
    return ruta.lower().endswith(SUFIJOS)


def find_fdata(root: str) -> list[str]:
    """Todos los `.fdata` bajo `root` (lo reusa `pkp fdata`)."""
    return fdata.find_fdata(root)


def iter_fdata_entries(path: str):
    """Solo las entradas de tipo animacion de un `.fdata`, con su cabecera."""
    for entry in fdata.iter_entries(path):
        if entry.type_ktid == KTID_G1A:
            yield entry


def read_entry(path: str, entry, *, limit: int | None = None) -> bytes:
    """Bytes de una entrada; `limit` corta en la cabecera (lista rapida)."""
    with open(path, "rb", buffering=0) as fh:
        return fdata.read_entry(fh, entry, limit=limit)


def find_entry(path: str, name_hash: int):
    """Entrada por `name_hash`; falla si no esta o si no es una animacion."""
    for entry in iter_fdata_entries(path):
        if entry.name_hash == name_hash:
            return entry
    raise AnimError(
        "%s: no hay animacion (g1a, 0x%08x) con name_hash 0x%08x"
        % (path, KTID_G1A, name_hash))


def iter_files(root: str) -> list[str]:
    """`.g1a`/`.g2a` de una carpeta (sin bajar), ordenados."""
    if os.path.isfile(root):
        if not es_animacion(root):
            raise AnimError(
                "%s no acaba en %s: para leer un .fdata pasa --fdata"
                % (root, " ni ".join(SUFIJOS)))
        return [root]
    if not os.path.isdir(root):
        raise AnimError("no existe la carpeta: %s" % root)
    hallados = sorted(os.path.join(root, n) for n in os.listdir(root)
                      if n.lower().endswith(SUFIJOS))
    if not hallados:
        raise AnimError(
            "no hay .g1a/.g2a en %s\n"
            "  extrae un .fdata con: pkp fdata extract --type g1a --out <carpeta> <fichero.fdata>"
            % root)
    return hallados


def load_bytes(ruta: str, name_hash: int | None = None) -> tuple[str, bytes]:
    """`(etiqueta, bytes)` de una animacion, venga de un fichero o de un .fdata."""
    if es_fdata(ruta):
        if name_hash is None:
            raise AnimError(
                "%s es un .fdata: hay que elegir la entrada con --hash 0x........\n"
                "  se listan con: pkp anim list %s" % (ruta, ruta))
        entry = find_entry(ruta, name_hash)
        etiqueta = "0x%08x.g1a" % entry.name_hash
        return etiqueta, read_entry(ruta, entry)
    if name_hash is not None:
        raise AnimError("--hash solo vale con un .fdata, y %s no lo es" % ruta)
    if not os.path.isfile(ruta):
        raise AnimError("no existe el fichero: %s" % ruta)
    with open(ruta, "rb") as fh:
        return os.path.basename(ruta), fh.read()


def load(ruta: str, name_hash: int | None = None) -> tuple[str, Animation, bytes]:
    """`(etiqueta, animacion, bytes)`."""
    etiqueta, datos = load_bytes(ruta, name_hash)
    return etiqueta, parse(datos), datos


def peek_bytes(datos: bytes):
    """Cabecera de una animacion sin parsear el resto."""
    return peek(datos[:HEADER_SIZE])


__all__ = [
    "KTID_G1A",
    "SUFIJOS",
    "es_animacion",
    "es_fdata",
    "find_entry",
    "find_fdata",
    "iter_fdata_entries",
    "iter_files",
    "load",
    "load_bytes",
    "peek_bytes",
    "read_entry",
]

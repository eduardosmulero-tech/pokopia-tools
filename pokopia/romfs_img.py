"""Lector del `RomFS.img` del runtime nativo (formato `DMROMFS1`).

El runtime de `nxrt` monta el romfs desde una imagen o desde una carpeta. La imagen
tiene cabecera de 24 bytes, indice al final y entradas de 24 bytes:

    0   "DMROMFS1"
    8   u64 ioff        offset del indice dentro del fichero
    16  u64 isz         tamano del indice (el runtime exige isz == fichero - ioff)
    24  u64 n           numero de entradas

    indice: n x 24 B  u64 a | u64 b | u32 name | u16 nlen | u8 type | u8 pad
        directorio (type 0): a = indice del primer hijo, b = numero de hijos
        fichero   (type 1): a = offset de los datos,    b = tamano
    despues de las entradas, el pozo de nombres UTF-8 (name/nlen lo direccionan).

Los hijos van en anchura (BFS) y ordenados por nombre dentro de cada directorio.
El formato viene de `src/nxrt/hle/romfs_image.h` del proyecto pokopia-native
(MIT, (c) seedds), el mismo que cita `CONTRIB-POKOHEX.md`; la lectura esta
contrastada contra la imagen real (ver `informes/t_88d29217/MOD-LOADER-NATIVO.md`).

Aqui solo se LEE: este modulo abre el fichero en modo lectura y no expone ninguna
escritura. La escritura del romfs no forma parte del kit (`docs/MOD-OVERLAY.es.md`).
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

MAGIC = b"DMROMFS1"
HEADER = 32
ENTRY = 24
DIR, FILE = 0, 1


class RomFSImageError(ValueError):
    """La imagen no es un `DMROMFS1` coherente o la ruta pedida no existe."""

    exit_code = 1


@dataclass(frozen=True)
class ImageEntry:
    """Un nodo del arbol: ruta relativa sin `/` inicial, offset, tamano y tipo."""

    path: str
    index: int
    offset: int
    size: int
    is_dir: bool

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


class RomFSImage:
    """Lectura de solo lectura de la tabla y del contenido de un `RomFS.img`."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._fh = open(self.path, "rb")
        try:
            self._leer_cabecera()
        except Exception:
            self._fh.close()
            raise

    # -- construccion -------------------------------------------------------

    def _leer_cabecera(self) -> None:
        head = self._fh.read(HEADER)
        if len(head) < HEADER or head[:8] != MAGIC:
            raise RomFSImageError("%s: no empieza por %s" % (self.path, MAGIC.decode()))
        self.ioff, self.isz, self.count = struct.unpack_from("<QQQ", head, 8)
        self.size = self._fh.seek(0, os.SEEK_END)
        if self.ioff < HEADER or self.ioff > self.size or self.isz != self.size - self.ioff:
            raise RomFSImageError(
                "%s: indices incoherentes (ioff=%d isz=%d tamano=%d): el runtime "
                "exige isz == tamano - ioff" % (self.path, self.ioff, self.isz, self.size))
        if self.count == 0 or self.count * ENTRY > self.isz:
            raise RomFSImageError("%s: %d entradas no caben en un indice de %d B"
                                  % (self.path, self.count, self.isz))
        self._fh.seek(self.ioff)
        self._indice = self._fh.read(self.isz)
        self._names = self._indice[self.count * ENTRY:]
        self._entries = [struct.unpack_from("<QQIHBB", self._indice, k * ENTRY)
                         for k in range(self.count)]
        self._por_ruta: dict[str, ImageEntry] = {}
        for ruta, k in self.walk():
            a, b, _, _, typ, _ = self._entries[k]
            clave = ruta.lstrip("/")
            self._por_ruta[clave] = ImageEntry(clave, k, a, b, typ == DIR)

    # -- tabla --------------------------------------------------------------

    def _nombre(self, k: int) -> str:
        _, _, off, nlen, _, _ = self._entries[k]
        return self._names[off:off + nlen].decode("utf-8", "replace")

    def _hijos(self, k: int) -> list[int]:
        a, b, _, _, typ, _ = self._entries[k]
        if typ != DIR:
            return []
        if a + b > self.count:
            raise RomFSImageError("%s: entrada %d apunta a hijos fuera de la tabla"
                                  % (self.path, k))
        return list(range(a, a + b))

    def walk(self, k: int = 0, prefix: str = ""):
        """`(ruta, indice)` de todos los descendientes, en el orden del arbol."""
        for hijo in self._hijos(k):
            ruta = prefix + "/" + self._nombre(hijo)
            yield ruta, hijo
            if self._entries[hijo][4] == DIR:
                yield from self.walk(hijo, ruta)

    def entries(self) -> list[ImageEntry]:
        """Todos los nodos, sin repetir y en orden de tabla."""
        return [e for _, e in sorted(self._por_ruta.items(),
                                     key=lambda kv: kv[1].index)]

    def files(self) -> list[ImageEntry]:
        return [e for e in self.entries() if not e.is_dir]

    def find(self, path: str) -> ImageEntry | None:
        return self._por_ruta.get(_normalizar(path))

    def __contains__(self, path: str) -> bool:
        return self.find(path) is not None

    # -- contenido ----------------------------------------------------------

    def read(self, path: str) -> bytes:
        entry = self._pedir(path)
        self._fh.seek(entry.offset)
        datos = self._fh.read(entry.size)
        if len(datos) != entry.size:
            raise RomFSImageError("%s: la entrada %s dice %d B y hay %d"
                                  % (self.path, entry.path, entry.size, len(datos)))
        return datos

    def sha256(self, path: str, chunk: int = 1 << 20) -> str:
        """sha256 del contenido que el `img` sirve para esa ruta, sin cargarlo entero."""
        entry = self._pedir(path)
        h = hashlib.sha256()
        self._fh.seek(entry.offset)
        quedan = entry.size
        while quedan:
            bloque = self._fh.read(min(chunk, quedan))
            if not bloque:
                raise RomFSImageError("%s: lectura corta en %s (%d B sin leer)"
                                      % (self.path, entry.path, quedan))
            h.update(bloque)
            quedan -= len(bloque)
        return h.hexdigest()

    def _pedir(self, path: str) -> ImageEntry:
        entry = self.find(path)
        if entry is None:
            raise RomFSImageError("%s: %r no esta en la imagen" % (self.path, path))
        if entry.is_dir:
            raise RomFSImageError("%s: %r es un directorio" % (self.path, path))
        return entry

    def fingerprint(self) -> dict:
        """Huella barata del build: tamano, entradas y sha256 de cabecera + indice.

        No lee el contenido (el `img` real tiene 7 GB): sirve para responder «este
        `img` es el mismo build que el que se uso al instalar» en milisegundos. El
        indice guarda offsets y tamanos de cada entrada, asi que cambia cuando
        cambia el contenido, no solo cuando cambia la lista de ficheros.
        """
        h = hashlib.sha256()
        h.update(struct.pack("<QQQ", self.ioff, self.isz, self.count))
        h.update(self._indice)
        return {"size": self.size, "entries": self.count,
                "index_sha256": h.hexdigest()}

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "RomFSImage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - comodidad en depuracion
        return "<RomFSImage %s: %d entradas, %d B>" % (self.path, self.count, self.size)


def _normalizar(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def abrir(path: str | None) -> RomFSImage | None:
    """Abre la imagen si se ha pedido; `None` si no hay ruta."""
    if not path:
        return None
    return RomFSImage(path)

"""Una pagina del save (`G00/CMNDAT.BIN`, `B00/CMNDAT.BIN`): cabecera, zlib y regiones.

Formato medido (save 2.0.1):

    +0x00  u32  magic 0x31227687
    +0x04  u32  version de save
    +0x08  u32  0x40001
    +0x10  i32  longitud total declarada (desde el byte 0 del fichero)
    +0x130      flujo zlib -> cuerpo crudo del tamano que declara el layout

Este modulo no escribe: solo abre, valida y trocea. La escritura esta en `writer.py`.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib
from dataclasses import dataclass

from . import layout as layouts
from .errors import SaveFormatError

#: Paginas conocidas del save y su papel (misma forma, contenido distinto).
PAGES = {"G00": "pagina principal", "B00": "segunda pagina"}

#: Carpeta del save por defecto, relativa al directorio de trabajo. `PKP_SAVE` manda.
#: Solo lectura por defecto: se abre para leer y nunca se escribe aqui sin permiso.
DEFAULT_SAVE = "save"


def configured_save() -> str:
    """Carpeta del save configurada: `PKP_SAVE` si esta, si no `./save`."""
    return os.environ.get("PKP_SAVE") or DEFAULT_SAVE


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve_save(path: str | None = None) -> str:
    """Directorio del save (contiene G00/ y B00/)."""
    base = os.path.abspath(os.path.expanduser(path or configured_save()))
    if os.path.isfile(base):
        base = os.path.dirname(os.path.dirname(base))
    return base


def page_path(save_dir: str, page: str = "G00") -> str:
    if page not in PAGES:
        raise SaveFormatError("pagina desconocida %r (conocidas: %s)"
                              % (page, ", ".join(sorted(PAGES))))
    return os.path.join(save_dir, page, "CMNDAT.BIN")


@dataclass(frozen=True)
class SavePage:
    """Un CMNDAT.BIN abierto y descomprimido, con su geometria resuelta."""

    path: str
    page: str
    raw: bytes
    payload: bytes
    layout: layouts.Layout
    md5: str

    # -- construccion ----------------------------------------------------
    @classmethod
    def open(cls, path: str, page: str | None = None) -> "SavePage":
        if not os.path.isfile(path):
            raise SaveFormatError("no existe el fichero %s" % path)
        raw = open(path, "rb").read()
        if len(raw) < layouts.HEADER_SIZE:
            raise SaveFormatError("%s: %d B, menos que la cabecera de %d B"
                                  % (path, len(raw), layouts.HEADER_SIZE))
        magic, version, _unk = struct.unpack_from("<III", raw, 0)
        if magic != layouts.SAVE_MAGIC:
            raise SaveFormatError("%s: magic %#010x, se esperaba %#010x"
                                  % (path, magic, layouts.SAVE_MAGIC))
        declared = struct.unpack_from("<i", raw, 0x10)[0]
        if not layouts.HEADER_SIZE < declared <= len(raw):
            raise SaveFormatError(
                "%s: longitud declarada %d fuera de rango (%d..%d)"
                % (path, declared, layouts.HEADER_SIZE + 1, len(raw)))
        lay = layouts.get(version)
        try:
            payload = zlib.decompress(raw[layouts.HEADER_SIZE:declared])
        except zlib.error as exc:
            raise SaveFormatError("%s: el cuerpo no es zlib valido (%s)" % (path, exc))
        if len(payload) != lay.payload_size:
            raise SaveFormatError(
                "%s: cuerpo crudo de %d B, el layout de la version %#010x declara %d B"
                % (path, len(payload), version, lay.payload_size))
        return cls(path=path, page=page or os.path.basename(os.path.dirname(path)),
                   raw=raw, payload=payload, layout=lay,
                   md5=hashlib.md5(raw).hexdigest())

    @classmethod
    def open_save(cls, save_dir: str | None = None, page: str = "G00") -> "SavePage":
        base = resolve_save(save_dir)
        return cls.open(page_path(base, page), page)

    # -- lectura ---------------------------------------------------------
    @property
    def version(self) -> int:
        return self.layout.version

    @property
    def declared_length(self) -> int:
        return struct.unpack_from("<i", self.raw, 0x10)[0]

    def region_bytes(self, name: str) -> bytes:
        reg = self.layout.region(name)
        if reg.end > len(self.payload):
            raise SaveFormatError("%s: la region %s acaba en %d, mas alla del cuerpo (%d B)"
                                  % (self.path, name, reg.end, len(self.payload)))
        return self.payload[reg.offset:reg.end]

    def record(self, region: str, index: int) -> bytes:
        start, end = self.layout.region(region).record(index)
        return self.payload[start:end]

    def summary(self) -> dict:
        return {
            "path": self.path,
            "page": self.page,
            "md5": self.md5,
            "bytes": len(self.raw),
            "version": "%#010x" % self.version,
            "game": self.layout.game,
            "declared_length": self.declared_length,
            "payload": len(self.payload),
            "regions": [{"name": r.name, "offset": r.offset, "count": r.count,
                         "stride": r.stride, "confidence": r.confidence}
                        for r in self.layout.regions],
        }

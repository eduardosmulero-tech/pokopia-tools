"""Ficheros de zona del save (`STGDATnn.BIN`): cuantos hay y cual es su cabecera.

Formato medido (save 2.0.1, solo lectura):

    +0x000  48 B  floats de camara/encuadre (varian entre guardados)
    +0x010  i32   longitud total declarada del fichero (desde el byte 0)
    +0x124        un solo flujo zlib -> cuerpo crudo de 138.411.448 B

Cada zona de la partida tiene su propio fichero, numerado en el nombre. El save **no**
declara cuantas zonas existen en el juego: ese total no esta en `CMNDAT` ni en la
cabecera de estos ficheros, asi que el parte no publica denominador.

Este modulo **no descomprime** el cuerpo (138 MB por zona y por lectura): valida la
cabecera y el tamano declarado, que es lo unico que hace falta para contarlas.
"""
from __future__ import annotations

import os
import re
import struct

from .errors import SaveFormatError

#: Cabecera de los ficheros de zona (bytes antes del flujo zlib).
ZONE_HEADER_SIZE = 0x124

#: Tamano del cuerpo crudo medido en las dos zonas del save 2.0.1.
ZONE_PAYLOAD_SIZE = 138411448

_ZONE_RE = re.compile(r"^STGDAT(\d{2})\.BIN$")


class ZoneFile:
    """Un `STGDATnn.BIN` validado por cabecera."""

    __slots__ = ("index", "path", "size", "declared")

    def __init__(self, index: int, path: str, size: int, declared: int) -> None:
        self.index = index
        self.path = path
        self.size = size
        self.declared = declared

    def as_dict(self) -> dict:
        return {"index": self.index, "bytes": self.size, "declared": self.declared}


def zone_path(save_dir: str, page: str, index: int) -> str:
    return os.path.join(save_dir, page, "STGDAT%02d.BIN" % index)


def zone_files(save_dir: str, page: str = "G00") -> list[ZoneFile]:
    """Ficheros de zona presentes en la pagina, ordenados por indice.

    Un fichero con la cabecera rota **no se cuenta** y se informa en `rejected`.
    """
    directory = os.path.join(save_dir, page)
    if not os.path.isdir(directory):
        raise SaveFormatError("no existe la carpeta de la pagina %s" % directory)
    out = []
    for name in sorted(os.listdir(directory)):
        m = _ZONE_RE.match(name)
        if not m:
            continue
        path = os.path.join(directory, name)
        size = os.path.getsize(path)
        if size <= ZONE_HEADER_SIZE:
            raise SaveFormatError("%s: %d B, menos que la cabecera de %d B"
                                  % (path, size, ZONE_HEADER_SIZE))
        with open(path, "rb") as fh:
            head = fh.read(ZONE_HEADER_SIZE)
        declared = struct.unpack_from("<i", head, 0x10)[0]
        if not ZONE_HEADER_SIZE < declared <= size:
            raise SaveFormatError("%s: longitud declarada %d fuera de rango (%d..%d)"
                                  % (path, declared, ZONE_HEADER_SIZE + 1, size))
        out.append(ZoneFile(int(m.group(1)), path, size, declared))
    return out


def zone_indices(save_dir: str, page: str = "G00") -> list[int]:
    return [z.index for z in zone_files(save_dir, page)]


def evidence_text(zone_count: int, indices: list[int], page: str) -> str:
    """Evidencia de la cifra, sin contenido del juego."""
    nombres = ", ".join("%02d" % i for i in indices) if indices else "ninguno"
    return ("%d fichero(s) de zona STGDATnn.BIN en la pagina %s (indices %s). "
            "Medido: es un recuento de ficheros, no un campo del payload. El save no "
            "declara cuantas zonas tiene el juego, asi que no hay denominador. "
            "Semantica 'zonas con datos' inferida: en las copias, la pagina G00 tiene "
            "2 y la B00 1, y la B00 va por detras en aldeanos/casas/catalogo"
            % (zone_count, page, nombres))

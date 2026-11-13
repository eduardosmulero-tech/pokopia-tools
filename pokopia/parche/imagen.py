"""Imagen de modulo de un ejecutable NSO0: cabecera + segmentos descomprimidos.

Para que sirve. El emulador aplica el parche de ejecutable (`.ips`) sobre la
**imagen ya descomprimida** del modulo: la cabecera de 0x100 B seguida de los
tres segmentos en su direccion de modulo (`offset_ips = 0x100 + offset_modulo`).
Por eso un parche se declara por offset de modulo y aqui se reproduce esa misma
imagen en memoria para comprobar los bytes antes de escribir nada.

El dump es de solo lectura: este modulo abre el `.nso` en modo lectura y nunca
escribe. La escritura la decide `aplicar` y va siempre a una carpeta de trabajo.

Formato del NSO0 (cabecera de 0x100 B), tomado de la especificacion publica y
contrastado con el build 655360 de este proyecto:

    00  magic "NSO0" | 04 version u32 | 08 reservado | 0C flags (bit i = segmento i comprimido)
    10  text  { file_offset u32, location u32, size u32, align u32 }   (0x10 + i*0x10)
    40  build id (0x20 B)
    60  packed_size u32 x3
    A0  sha256 del segmento descomprimido x3 (0x20 B cada uno)

`location` es la direccion de modulo donde se carga el segmento; el `.text` del
build 655360 arranca en 0 y por eso la imagen empieza ahi.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

from .errors import ParcheError, UsageError

NSO_MAGIC = b"NSO0"
CABECERA = 0x100
SEGMENTOS = ("text", "rodata", "data")


@dataclass(frozen=True)
class Segmento:
    """Un segmento del NSO0 y donde cae en la imagen del modulo."""

    nombre: str
    base: int          # location: direccion de modulo del primer byte
    tam: int           # tamano descomprimido
    pack: int          # tamano en el fichero
    off: int           # offset en el fichero
    comprimido: bool
    sha256: str        # sha256 esperado del descomprimido, segun la cabecera

    @property
    def fin(self) -> int:
        return self.base + self.tam


@dataclass(frozen=True)
class Cabecera:
    version: int
    flags: int
    build_id: str
    segmentos: tuple[Segmento, ...]

    def segmento(self, nombre: str) -> Segmento:
        for seg in self.segmentos:
            if seg.nombre == nombre:
                return seg
        raise ParcheError("segmento desconocido: %r" % nombre, code="segmento")


def leer_cabecera(raw: bytes) -> Cabecera:
    """Valida y decodifica la cabecera de 0x100 B de un NSO0."""
    if len(raw) < CABECERA:
        raise ParcheError("cabecera truncada: %d B" % len(raw), code="cabecera")
    if raw[:4] != NSO_MAGIC:
        raise ParcheError("no empieza por NSO0 (primeros 4 B: %s)" % raw[:4].hex(),
                          code="cabecera")
    version, _reservado, flags = struct.unpack_from("<III", raw, 0x04)
    segs = []
    for i, nombre in enumerate(SEGMENTOS):
        off, location, size, _align = struct.unpack_from("<IIII", raw, 0x10 + i * 0x10)
        pack = struct.unpack_from("<I", raw, 0x60 + i * 4)[0]
        sha = raw[0xA0 + i * 0x20:0xC0 + i * 0x20].hex()
        segs.append(Segmento(nombre=nombre, base=location, tam=size, pack=pack, off=off,
                             comprimido=bool(flags & (1 << i)), sha256=sha))
    return Cabecera(version=version, flags=flags, build_id=raw[0x40:0x60].hex(),
                    segmentos=tuple(segs))


def descomprimir_lz4(src: bytes, esperado: int) -> bytes:
    """Decodifica un bloque LZ4 (formato bloque, sin cabecera de frame).

    Misma rutina que `tools/nso_dump.py` (que se queda como esta: esta congelado
    y verificado). Las secuencias llevan token(u8), literales, offset(u16 le) y
    match; el match puede solaparse consigo mismo y se copia por tramos.
    """
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1

        lit = token >> 4
        if lit == 15:
            while True:
                if i >= n:
                    raise ParcheError("bloque LZ4 truncado en la longitud de literales",
                                      code="lz4")
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        if lit:
            out += src[i:i + lit]
            i += lit
            if i >= n:      # ultima secuencia: solo literales
                break

        if i + 2 > n:
            raise ParcheError("bloque LZ4 truncado en el offset de match", code="lz4")
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0 or off > len(out):
            raise ParcheError("bloque LZ4 corrupto: desplazamiento %d con %d B de salida"
                              % (off, len(out)), code="lz4")

        mlen = token & 0x0F
        if mlen == 15:
            while True:
                if i >= n:
                    raise ParcheError("bloque LZ4 truncado en la longitud de match",
                                      code="lz4")
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4

        start = len(out) - off
        copied = 0
        while copied < mlen:
            take = off if mlen - copied > off else mlen - copied
            out += out[start + copied:start + copied + take]
            copied += take

    if len(out) != esperado:
        raise ParcheError("bloque LZ4 de %d B: la cabecera dice %d B" % (len(out), esperado),
                          code="lz4")
    return bytes(out)


def leer(ruta: str) -> tuple[bytes, Cabecera]:
    """Devuelve (imagen del modulo, cabecera). No escribe nada."""
    if not os.path.isfile(ruta):
        raise UsageError("no existe el ejecutable: %s" % ruta, code="fichero")
    with open(ruta, "rb") as fh:
        cab = leer_cabecera(fh.read(CABECERA))
        for seg in cab.segmentos:
            if seg.tam and seg.off + seg.pack > os.path.getsize(ruta):
                raise ParcheError(
                    "segmento %s fuera del fichero (offset %#x + %d B > %d B)"
                    % (seg.nombre, seg.off, seg.pack, os.path.getsize(ruta)),
                    code="cabecera")
        imagen = bytearray(CABECERA + max(seg.fin for seg in cab.segmentos))
        imagen[:CABECERA] = _cabecera_bytes(fh, cab)
        for seg in cab.segmentos:
            fh.seek(seg.off)
            crudo = fh.read(seg.pack)
            datos = descomprimir_lz4(crudo, seg.tam) if seg.comprimido else crudo
            if len(datos) != seg.tam:
                raise ParcheError("segmento %s: %d B leidos, %d B declarados"
                                  % (seg.nombre, len(datos), seg.tam), code="cabecera")
            real = hashlib.sha256(datos).hexdigest()
            if seg.sha256.strip("0") and real != seg.sha256.lower():
                raise ParcheError(
                    "segmento %s: sha256 %s no casa con la cabecera (%s)"
                    % (seg.nombre, real[:16], seg.sha256[:16]), code="cabecera")
            imagen[CABECERA + seg.base:CABECERA + seg.fin] = datos
    return bytes(imagen), cab


def _cabecera_bytes(fh, cab: Cabecera) -> bytes:
    fh.seek(0)
    return fh.read(CABECERA)


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()

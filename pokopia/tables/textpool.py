"""Tablas de texto con **pool y punteros** del contenedor de Pokopia.

Familia medida: `#3250`–`#3258` (9 entradas, una por idioma). Esquema, verificado
fila a fila sobre las 9 entradas (docs/SPEC-DIALOGOS.md):

    +0   u32  count                     (391 en la copia v2.0.1a)
    +4   u32  version                   (2)
    +8   ...  ceros hasta 64
    +64  count registros de 8 B:
             u32 a | u32 b               (b: sin semantica demostrada)
    pool  a partir de 64 + count*8: cadenas UTF-8 terminadas en NUL, en el
          orden de las filas

El campo `a` **no es un offset directo al pool**: es el offset medido sobre una
maqueta en la que cada fila arrastraba sus 8 bytes de registro, de forma que

    inicio(fila) = a - 8 * (count - fila)

Esa formula cuadra en las 391 filas de las 9 entradas (3.519 filas): el inicio
cae siempre en 0 o justo detras de un NUL, y las cadenas son contiguas.

Nada de esto se apoya en `PokoHex`: el esquema salio del barrido y de la
comprobacion fila a fila (ver `informes/t_097dee0b/TEXTO-LARGO.md`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 64
STRIDE = 8
VERSION = 2


class PoolError(ValueError):
    """El payload no sigue el esquema de tabla con pool."""


@dataclass(frozen=True)
class PoolTable:
    """Geometria de una tabla con pool: header, registros y zona de texto."""

    index: int
    count: int
    version: int
    header: int = HEADER
    stride: int = STRIDE

    @property
    def pool_start(self) -> int:
        return self.header + self.count * self.stride

    def raw_offsets(self, blob: bytes) -> list[int]:
        """Los `a` tal y como estan guardados, fila a fila."""
        if len(blob) < self.pool_start:
            raise PoolError("#%d: payload de %d B y el pool empieza en %d"
                            % (self.index, len(blob), self.pool_start))
        return [struct.unpack_from("<I", blob, self.header + r * self.stride)[0]
                for r in range(self.count)]

    def flags(self, blob: bytes) -> list[int]:
        """Los `b` de cada registro (campo sin semantica demostrada)."""
        return [struct.unpack_from("<I", blob, self.header + r * self.stride + 4)[0]
                for r in range(self.count)]

    def starts(self, blob: bytes) -> list[int]:
        """Inicio real de la cadena de cada fila dentro del pool."""
        crudos = self.raw_offsets(blob)
        return [a - self.stride * (self.count - r) for r, a in enumerate(crudos)]

    def ends(self, blob: bytes) -> list[int]:
        """Offset del NUL que cierra la cadena de cada fila."""
        pool = blob[self.pool_start:]
        fines = []
        for ini in self.starts(blob):
            if ini < 0 or ini > len(pool):
                fines.append(-1)
                continue
            fin = pool.find(b"\x00", ini)
            fines.append(len(pool) if fin < 0 else fin)
        return fines

    def slots(self, blob: bytes) -> list[bytes]:
        """Texto crudo (bytes UTF-8) de cada fila, en el orden de las filas."""
        pool = blob[self.pool_start:]
        return [pool[i:f] for i, f in zip(self.starts(blob), self.ends(blob))]

    def textos(self, blob: bytes) -> list[str]:
        """Texto decodificado de cada fila; ValueError si alguna no es UTF-8."""
        return [s.decode("utf-8") for s in self.slots(blob)]


def parse(index: int, blob: bytes) -> PoolTable:
    """Lee la cabecera y comprueba la geometria basica de una tabla con pool."""
    if len(blob) < HEADER:
        raise PoolError("#%d: payload de %d B, no llega al header de %d B"
                        % (index, len(blob), HEADER))
    count, version = struct.unpack_from("<II", blob, 0)
    if count == 0 or count > 1_000_000:
        raise PoolError("#%d: count %d fuera de rango" % (index, count))
    if version != VERSION:
        raise PoolError("#%d: version %d, esperada %d" % (index, version, VERSION))
    tabla = PoolTable(index=index, count=count, version=version)
    if len(blob) < tabla.pool_start:
        raise PoolError("#%d: payload de %d B y el pool empieza en %d"
                        % (index, len(blob), tabla.pool_start))
    return tabla


def es_tabla(blob: bytes, index: int = -1) -> PoolTable | None:
    """Devuelve la geometria si el payload **cuadra entero** con el esquema.

    Criterio de aceptacion (todo o nada):

      - `count > 0` y `version == 2` en la cabecera
      - el pool empieza en `64 + count*8` y cabe en el payload
      - `inicio[r] = a[r] - 8*(count-r)` cae en 0 o justo detras de un NUL,
        la secuencia de inicios no retrocede y **las cadenas son contiguas**
        (`inicio[r] == fin[r-1] + 1`): el pool es exactamente la concatenacion
        de `count` cadenas terminadas en NUL, con 32 bytes de cola como mucho
      - todas las cadenas decodifican como UTF-8
      - el texto ocupa al menos el 10 % del pool (si no, es otra cosa que
        casualmente empieza por dos enteros)

    La contiguidad total es el criterio que separa este esquema de una tabla de
    registros de 32 B: en las 2.409 entradas que lo cumplen, la suma de
    `longitud + 1` de las `count` cadenas da el tamano del pool con 0..16 bytes
    de cola (medido; ver docs/SPEC-DIALOGOS.md §6).
    """
    if len(blob) < HEADER + STRIDE:
        return None
    count, version = struct.unpack_from("<II", blob, 0)
    if count == 0 or count > 1_000_000 or version != VERSION:
        return None
    tabla = PoolTable(index=index, count=count, version=version)
    if tabla.pool_start >= len(blob):
        return None
    pool = blob[tabla.pool_start:]
    if len(pool) < 64:
        return None
    anteriores_fin = None
    texto = 0
    for r in range(count):
        a = struct.unpack_from("<I", blob, HEADER + r * STRIDE)[0]
        ini = a - STRIDE * (count - r)
        if ini != 0 and not (0 < ini <= len(pool) and pool[ini - 1] == 0):
            return None
        if anteriores_fin is not None and ini != anteriores_fin + 1:
            return None
        fin = pool.find(b"\x00", ini)
        if fin < 0:
            return None
        try:
            pool[ini:fin].decode("utf-8")
        except UnicodeDecodeError:
            return None
        texto += fin - ini
        anteriores_fin = fin
    if anteriores_fin is None:
        return None
    if len(pool) - (anteriores_fin + 1) > 32:
        return None
    if texto < 0.10 * len(pool):
        return None
    return tabla


def validar(tabla: PoolTable, blob: bytes) -> list[str]:
    """Problemas estructurales del payload. Lista vacia = estructura valida."""
    problemas: list[str] = []
    count, version = struct.unpack_from("<II", blob, 0)
    if count != tabla.count:
        problemas.append("count del header %d != %d" % (count, tabla.count))
    if version != tabla.version:
        problemas.append("version del header %d != %d" % (version, tabla.version))
    if tabla.pool_start > len(blob):
        problemas.append("pool empieza en %d y el payload mide %d"
                         % (tabla.pool_start, len(blob)))
        return problemas
    pool = blob[tabla.pool_start:]
    crudos = tabla.raw_offsets(blob)
    inicios = tabla.starts(blob)
    anterior = -1
    invalidas = 0
    for r, (a, ini) in enumerate(zip(crudos, inicios)):
        if ini != a - tabla.stride * (tabla.count - r):
            problemas.append("fila %d: inicio %d no sale de a=%d" % (r, ini, a))
        if ini < 0 or ini > len(pool):
            problemas.append("fila %d: inicio %d fuera del pool (0..%d)"
                             % (r, ini, len(pool)))
            continue
        if ini and pool[ini - 1] != 0:
            problemas.append("fila %d: inicio %d no cae detras de un NUL" % (r, ini))
        if ini < anterior:
            problemas.append("fila %d: inicio %d retrocede respecto a %d"
                             % (r, ini, anterior))
        anterior = ini
        fin = pool.find(b"\x00", ini)
        if fin < 0:
            problemas.append("fila %d: cadena sin NUL de cierre" % r)
            continue
        try:
            pool[ini:fin].decode("utf-8")
        except UnicodeDecodeError:
            invalidas += 1
    if invalidas:
        problemas.append("%d filas con texto no UTF-8" % invalidas)
    if len(problemas) > 40:
        problemas = problemas[:40] + ["... y %d mas" % (len(problemas) - 40)]
    return problemas


def counts_utf8(tabla: PoolTable, blob: bytes) -> int:
    """Filas cuyo texto decodifica como UTF-8 (dato de comparacion antes/despues)."""
    n = 0
    for slot in tabla.slots(blob):
        try:
            slot.decode("utf-8")
        except UnicodeDecodeError:
            continue
        n += 1
    return n


def sustituir(tabla: PoolTable, blob: bytes, fila: int, texto: bytes,
              modo: str = "igual") -> bytes:
    """Devuelve un payload nuevo con el texto de `fila` cambiado.

    Modos:
      igual   - el texto nuevo mide exactamente lo mismo; no se mueve ni un byte
                del resto del payload.
      relleno - el texto nuevo es igual o mas corto y se rellena con NUL hasta
                la longitud original: los offsets del pool quedan intactos y el
                payload mide lo mismo (quedan huecos vacios entre cadenas).
      ajuste  - el texto nuevo es igual o mas corto y se recorta el pool: el
                payload encoge y los `a` de todas las filas siguientes bajan en
                la misma cantidad de bytes.
    """
    if modo not in ("igual", "relleno", "ajuste"):
        raise PoolError("modo %r desconocido (igual | relleno | ajuste)" % (modo,))
    if not 0 <= fila < tabla.count:
        raise PoolError("fila %d fuera de rango (0..%d)" % (fila, tabla.count - 1))
    texto.decode("utf-8")  # el texto nuevo tiene que ser UTF-8 valido
    if b"\x00" in texto:
        raise PoolError("el texto nuevo no puede llevar NUL")
    ini, fin = tabla.starts(blob)[fila], tabla.ends(blob)[fila]
    if fin < 0:
        raise PoolError("fila %d: cadena sin cierre" % fila)
    viejo = blob[tabla.pool_start + ini:tabla.pool_start + fin]
    if modo == "igual" and len(texto) != len(viejo):
        raise PoolError("modo igual: el texto nuevo mide %d B y el viejo %d B"
                        % (len(texto), len(viejo)))
    if modo in ("relleno", "ajuste") and len(texto) > len(viejo):
        raise PoolError("modo %s: el texto nuevo mide %d B y no cabe en %d B"
                        % (modo, len(texto), len(viejo)))
    cabecera = blob[:tabla.header]
    registros = bytearray(blob[tabla.header:tabla.pool_start])
    pool = bytearray(blob[tabla.pool_start:])
    if modo == "igual":
        pool[ini:fin] = texto
    elif modo == "relleno":
        pool[ini:fin] = texto + b"\x00" * (len(viejo) - len(texto))
    else:
        delta = len(viejo) - len(texto)
        pool[ini:fin + 1] = texto + b"\x00"
        for r in range(fila + 1, tabla.count):
            off = r * tabla.stride
            a = struct.unpack_from("<I", registros, off)[0]
            if a < delta:
                raise PoolError("fila %d: a=%d no admite recortar %d" % (r, a, delta))
            struct.pack_into("<I", registros, off, a - delta)
    nuevo = cabecera + bytes(registros) + bytes(pool)
    problemas = validar(tabla, nuevo)
    if problemas:
        raise PoolError("la sustitucion deja el payload invalido: " + "; ".join(problemas[:5]))
    return nuevo

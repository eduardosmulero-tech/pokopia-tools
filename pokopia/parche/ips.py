"""Emision del parche de ejecutable en formato IPS32.

El emulador parchea la imagen **descomprimida** del modulo en tiempo de carga, y
el offset del `.ips` es `0x100 + offset_modulo` (la cabecera NSO son 0x100 B).
El formato IPS32 es el que se verifico sobre este juego: la variante "PATCH" sin
IPS32 se descarto porque el `.text` arranca en 0 y hay offsets por encima de
0xFFFFFF; en la variante vieja el terminador es la cadena "EOF" y un offset cuyos
tres primeros bytes fueran 45 4F 46 se leeria como fin de parche.

    "IPS32" | (offset u32 big endian | tamano u16 big endian | datos) * n | "EEOF"

Aqui no se usa RLE (tamano 0): todos los registros llevan sus bytes. El parche
declara pocos bytes y revisables, y un RLE seria una forma opaca de escribirlos.
"""

from __future__ import annotations

import struct

from .errors import ParcheError

MAGIC = b"IPS32"
FIN = b"EEOF"
#: La cabecera del NSO ocupa los primeros 0x100 B de la imagen que ve el emulador.
BASE_IMAGEN = 0x100
#: Offset maximo que cabe en un registro IPS32.
OFFSET_MAX = 0xFFFFFFFF


def construir(ediciones) -> bytes:
    """Serializa `[(offset_modulo, bytes_nuevos), ...]` como un `.ips` IPS32."""
    if not ediciones:
        raise ParcheError("un parche sin ediciones no se puede emitir", code="ips")
    salida = bytearray(MAGIC)
    for offset, datos in ediciones:
        if not isinstance(offset, int) or offset < 0:
            raise ParcheError("offset invalido: %r" % (offset,), code="ips")
        if not datos:
            raise ParcheError("edicion sin bytes nuevos en %#x" % offset, code="ips")
        if len(datos) > 0xFFFF:
            raise ParcheError("edicion de %d B en %#x: el registro IPS32 admite 65535"
                              % (len(datos), offset), code="ips")
        ips = BASE_IMAGEN + offset
        if ips > OFFSET_MAX:
            raise ParcheError("offset %#x no cabe en IPS32" % ips, code="ips")
        if len(datos) >= 3 and datos[:3] == b"EOF":
            raise ParcheError("bytes nuevos en %#x empiezan por 'EOF': ambiguo en IPS"
                              % offset, code="ips")
        salida += struct.pack(">IH", ips, len(datos)) + datos
    salida += FIN
    return bytes(salida)


def leer(datos: bytes) -> list[tuple[int, bytes]]:
    """Lee un `.ips` IPS32 y devuelve `[(offset_imagen, bytes), ...]`."""
    if not datos.startswith(MAGIC):
        raise ParcheError("no empieza por IPS32 (%r)" % datos[:5], code="ips")
    i = len(MAGIC)
    out = []
    while True:
        if datos[i:i + 4] == FIN:
            i += 4
            break
        if i + 6 > len(datos):
            raise ParcheError("registro IPS32 truncado en la posicion %d" % i, code="ips")
        offset, tam = struct.unpack_from(">IH", datos, i)
        i += 6
        out.append((offset, datos[i:i + tam]))
        i += tam
    if i != len(datos):
        raise ParcheError("%d B de sobra despues de EEOF" % (len(datos) - i), code="ips")
    return out

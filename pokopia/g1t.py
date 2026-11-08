#!/usr/bin/env python3
"""`G1T`: contenedor de texturas de KTGL (`GT1G`). Lectura, hasta el byte, y reescritura.

Un `.g1t` es un archivo con una o varias texturas comprimidas en bloque (BC1, BC5,
BC7...) o en crudo. La cabecera viene documentada desde hace años por la
comunidad; aqui se ha **medido** sobre el build 655360 (juego 2.0.1a, plataforma
`0x18`) y se deja escrito campo a campo en `docs/G1T-FORMAT.md`.

    +0x00  char[4]  "GT1G"                  (en big endian seria "G1TG")
    +0x04  u32      version                 (0x00000006 -> bytes "0600")
    +0x08  u32      total_size              (tamano del fichero)
    +0x0C  u32      header_size             (donde empieza la tabla, 0x1C aqui)
    +0x10  u32      texture_count
    +0x14  u32      platform                (0x18 = Switch 2; 0x10 = Switch 1)
    +0x18  u32      extra_size              (datos extra globales; 1008 en 3 ficheros)
    --- en 0x1C ---
    u32 flags_globales[texture_count]       (solo si header_size > 0x1C; a cero aqui)
    --- en header_size ---
    u32 offset[texture_count]               relativos a header_size
    --- tras la tabla ---
    u8 datos_extra_globales[extra_size]     (0 en casi todos)
    --- en header_size + offset[i] ---
    u8  mip_sys     (alto: numero de mips; bajo: sistema de tiles)
    u8  format
    u8  dxdy        (alto: log2(alto); bajo: log2(ancho))
    u8  flags[5]    (los 40 bits bajos del u64 de flags, con los nibbles cambiados)
    --- solo si el flag EXTENDED_DATA esta puesto ---
    u32 tamano_seccion[]                    (12, 16 o 20; empieza en 8 fijos)
        [0] tamano en bytes | [1] float depth | [2] flags[1] en BIG endian
        [3] ancho real (si la seccion mide 16) | [4] alto real (si mide 20)
    --- pixeles ---
    mip 0, luego mips 1..n contiguos; cada nivel con su relleno hasta tiles de
    8x8 bloques (medido: reproduce el tamano exacto en 9.850 de las 14.713 texturas)

Referencias de comunidad usadas para contrastar (sin copiar codigo): `gust_tools`
(VitaSmith, `gust_g1t.c`, **GPL-3.0**) y `fmt_g1m` (Joschuka, Noesis). De `gust_g1t.c`
salen los nombres y mascaras de flags, el reparto de bits del Morton y la forma de la
seccion `data[]`; todo se ha vuelto a medir sobre el build 655360 antes de darlo por
bueno (ver `docs/G1T-FORMAT.md`), y la licencia de ese codigo no se contagia aqui
porque no se copia: solo se usan hechos del formato.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

MAGIC = b"GT1G"
MAGIC_BE = b"G1TG"

#: Cabecera del fichero: magic + 6 x u32.
HEADER_SIZE = 0x1C

#: Cabecera de una textura antes del bloque extra.
TEX_HEADER_SIZE = 8

#: Flags de textura (`gust_g1t.c`: nombres y mascaras). Solo caben 40 bits en la
#: cabecera; lo que en `gust_g1t.c` pasa del bit 39 (`DOUBLE_HEIGHT`, `CUBE_MAP`...)
#: vive en la tabla de flags globales, que aqui se conserva tal cual y no se interpreta.
FLAG_EXTENDED_DATA = 0x000000000001   # lleva seccion `data[]` tras la cabecera de 8 B
FLAG_STANDARD_FLAGS = 0x000000011200  # combinacion que traen casi todas
FLAG_SRGB = 0x000000002000
FLAG_TEXTURE_ARRAY = 0x0000F00F0000
FLAG_DOUBLE_HEIGHT = 0x001000000000   # (fuera de los 40 bits guardados; no visto)
FLAG_NORMAL_MAP = 0x030000000000      # (idem)
FLAG_SURFACE_TEX = 0x000000000001     # (en el segundo u64: `data[2]` de la seccion)
FLAG_CUBE_MAP = 0x000100000000        # (idem)


#: Plataformas conocidas (gust_g1t.c) mas la de este dump.
PLATFORMS: dict[int, str] = {
    0x00: "ps2", 0x01: "ps3", 0x02: "x360", 0x03: "wii", 0x04: "ds", 0x05: "3ds",
    0x06: "vita", 0x07: "android", 0x08: "ios", 0x09: "wiiu", 0x0A: "windows",
    0x0B: "ps4", 0x0C: "xboxone", 0x10: "switch", 0x18: "switch2",
}


class G1TError(Exception):
    """El `.g1t` no se puede leer o escribir con este formato. `exit_code` lo fija la CLI."""

    exit_code = 1


@dataclass(frozen=True)
class Format:
    """Un formato de pixel: nombre, bytes por bloque y si va en orden de tiles.

    `block` es el tamano en bytes de la unidad de swizzle: 8 o 16 para BC (bloque
    4x4), o los bytes por pixel en los formatos crudos.
    """

    code: int
    name: str
    block: int
    block_px: int          # 4 en BC (bloque 4x4), 1 en crudo
    channels: int          # canales utiles (BC4=1, BC5=2, resto 4)
    swizzled: bool
    tile: int = 8          # lado del tile en unidades de bloque

    @property
    def compressed(self) -> bool:
        return self.block_px == 4

    def size(self, width: int, height: int) -> int:
        """Bytes que ocupa un nivel de mip de `width` x `height`."""
        if self.compressed:
            return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * self.block
        return width * height * self.block


#: Formatos vistos en el dump (`pkp tex stat`). Los codigos son los de KTGL; los
#: nombres, los de `gust_g1t.c` y `fmt_g1m`, contrastados aqui por su tamano.
#: `tile` es el lado del tile en unidades de bloque; medido, ver docs/G1T-FORMAT.md §4:
#: en BC el valor que cuadra mip 0 con mip 1 es 8 bloques (32x32 px); en los crudos de
#: 4 B/pixel la discontinuidad minima esta en 16 px, y `rg8` sale mejor en orden de filas.
FORMATS: dict[int, Format] = {
    0x01: Format(0x01, "rgba8", 4, 1, 4, True, 16),
    0x0A: Format(0x0A, "bgra8", 4, 1, 4, True, 16),
    0x0B: Format(0x0B, "r32f", 4, 1, 1, False),
    0x0C: Format(0x0C, "rg8", 2, 1, 2, False),
    0x0D: Format(0x0D, "rgba32f", 16, 1, 4, True, 16),
    0x10: Format(0x10, "dxt1", 8, 4, 4, True),
    0x12: Format(0x12, "dxt5", 16, 4, 4, True),
    0x59: Format(0x59, "dxt1", 8, 4, 4, False),
    0x5B: Format(0x5B, "dxt5", 16, 4, 4, False),
    0x5F: Format(0x5F, "bc7", 16, 4, 4, False),
    0x60: Format(0x60, "dxt1", 8, 4, 4, True),
    0x62: Format(0x62, "dxt5", 16, 4, 4, True),
    0x63: Format(0x63, "bc4", 8, 4, 1, True),
    0x64: Format(0x64, "bc5", 16, 4, 2, True),
    0x65: Format(0x65, "bc6h", 16, 4, 3, True),
    0x66: Format(0x66, "bc7", 16, 4, 4, True),
}


def format_of(code: int) -> Format:
    """El formato pedido; si no esta medido, se devuelve uno generico de 4 B/pixel."""
    return FORMATS.get(code) or Format(code, "0x%02x" % code, 4, 1, 4, False)


def _canonical_flags(raw: bytes) -> int:
    """Los 5 bytes de flags del fichero -> entero en orden canonico.

    `gust_g1t.c` guarda los 5 bytes del u64 de flags en orden **inverso** (el byte 0 de
    la tabla es el mas significativo de la parte guardada) y, en little endian, con los
    nibbles de cada byte cambiados. Aqui se deshace todo eso para poder comparar con las
    mascaras conocidas (`FLAG_*`).
    """
    valor = 0
    for i, byte in enumerate(raw):
        valor |= ((byte >> 4) | ((byte & 0x0F) << 4)) << (8 * (len(raw) - 1 - i))
    return valor


def _dims_from_dxdy(dxdy: int, flags: int) -> tuple[int, int]:
    """Ancho y alto a partir de los nibbles `dx`/`dy` de la cabecera."""
    ancho = 1 << (dxdy & 0x0F)
    alto = 1 << (dxdy >> 4)
    return ancho, alto * 2 if flags & FLAG_DOUBLE_HEIGHT else alto


def _chain(width: int, height: int, fmt: "Format", mips: int) -> int:
    """Bytes de la cadena completa de mips, del nivel 0 al ultimo."""
    total = 0
    for _ in range(mips):
        total += fmt.size(width, height)
        width, height = max(1, width // 2), max(1, height // 2)
    return total


def _seccion_extra(data: bytes, pos: int, siguiente: int, mip_sys: int,
                   fmt_code: int, dxdy: int, flags_raw: bytes) -> bytes:
    """Devuelve la seccion `data[]` si la hay, o `b""` si la textura no la lleva.

    La anuncia el flag `EXTENDED_DATA` (bit 0) y empieza con su propio tamano. Se
    comprueba ademas por aritmetica —lo que queda hasta la textura siguiente tiene que
    ser la seccion mas la cadena de mips— para no cortar ficheros donde el flag no
    viniera puesto.
    """
    resto = siguiente - pos
    if resto <= 0 or resto < 8:
        return b""
    (largo,) = struct.unpack_from("<I", data, pos)
    plausible = largo % 4 == 0 and 8 <= largo <= 64 and largo <= resto
    flags = _canonical_flags(flags_raw)
    if flags & FLAG_EXTENDED_DATA and plausible:
        return data[pos:pos + largo]
    fmt = format_of(fmt_code)
    mips = max(1, mip_sys >> 4)
    ancho, alto = _dims_from_dxdy(dxdy, flags)
    cadena = _chain(ancho, alto, fmt, mips)
    if resto == cadena:
        return b""
    if not plausible or resto - largo < cadena:
        return b""
    # Si la seccion trae dimensiones (texturas que no son potencia de 2), mandan ellas.
    ancho2, alto2 = ancho, alto
    if largo >= 16:
        (ancho2,) = struct.unpack_from("<I", data, pos + 12)
    if largo >= 20:
        (alto2,) = struct.unpack_from("<I", data, pos + 16)
        if _canonical_flags(flags_raw) & FLAG_DOUBLE_HEIGHT:
            alto2 *= 2
    if not ancho2 or not alto2:
        return b""
    cadena2 = _chain(ancho2, alto2, fmt, mips)
    if not (resto - largo == cadena2 or 0 <= resto - largo - cadena2 <= 4096):
        return b""
    return data[pos:pos + largo]


@dataclass(frozen=True)
class Texture:
    """Una textura dentro del `.g1t`: cabecera de 8 B + bloque extra + pixeles."""

    index: int
    offset: int            # absoluto, donde empieza la cabecera
    mip_sys: int
    format_code: int
    dxdy: int
    flags_raw: bytes       # los 5 bytes de flags TAL CUAL (con los nibbles cambiados)
    extra: bytes           # seccion `data[]` completa, incluido su u32 de tamano
    data_offset: int       # absoluto, primer byte de pixeles
    data_size: int         # bytes hasta la textura siguiente (o el fin del fichero)

    @property
    def format(self) -> Format:
        return format_of(self.format_code)

    @property
    def flags(self) -> int:
        """Flags de 64 bits en su orden canonico (ver `_canonical_flags`)."""
        return _canonical_flags(self.flags_raw)

    def has_flag(self, mask: int) -> bool:
        return (self.flags & mask) == mask

    @property
    def mip_count(self) -> int:
        return max(1, self.mip_sys >> 4)

    @property
    def tile_system(self) -> int:
        return self.mip_sys & 0x0F

    @property
    def extended(self) -> bool:
        """True si la cabecera lleva seccion `data[]` (flag `EXTENDED_DATA`, bit 0)."""
        return bool(self.flags & FLAG_EXTENDED_DATA)

    @property
    def extra_size_field(self) -> int:
        """El u32 con el que empieza `data[]`: su propio tamano en bytes."""
        if len(self.extra) < 4:
            return 0
        return struct.unpack_from("<I", self.extra, 0)[0]

    @property
    def extra_width(self) -> int:
        """Ancho de `data[3]` (solo con seccion de 16 o 20 B, texturas no potencia de 2)."""
        if len(self.extra) >= 16:
            return struct.unpack_from("<I", self.extra, 12)[0]
        return 0

    @property
    def extra_height(self) -> int:
        """Alto de `data[4]` (solo con seccion de 20 B)."""
        if len(self.extra) >= 20:
            return struct.unpack_from("<I", self.extra, 16)[0]
        return 0

    @property
    def nb_frames(self) -> int:
        """Fotogramas de un array de texturas; 1 si no lo es (`GET_NB_FRAMES`).

        El contador va en los bits 28-31 y 12-19 del **segundo** u64 de flags, que en
        este formato es `data[2]` de la seccion, guardado en big endian.
        """
        if not (self.extended and len(self.extra) >= 12):
            return 1
        segundo = struct.unpack_from(">I", self.extra, 8)[0]
        return (((segundo >> 28) & 0x0F) + ((segundo >> 12) & 0xF0)) or 1

    @property
    def cubemap(self) -> bool:
        return self.has_flag(FLAG_CUBE_MAP)

    @property
    def width(self) -> int:
        return self.extra_width or (1 << (self.dxdy & 0x0F))

    @property
    def height(self) -> int:
        alto = self.extra_height or (1 << (self.dxdy >> 4))
        return alto * 2 if self.has_flag(FLAG_DOUBLE_HEIGHT) else alto

    @property
    def header_size(self) -> int:
        return TEX_HEADER_SIZE + len(self.extra)

    @property
    def mip0_size(self) -> int:
        return self.format.size(self.width, self.height)

    def mip_sizes(self) -> list[tuple[int, int, int]]:
        """[(ancho, alto, bytes)] de cada nivel, sin relleno."""
        salida = []
        ancho, alto = self.width, self.height
        for _ in range(self.mip_count):
            salida.append((ancho, alto, self.format.size(ancho, alto)))
            ancho, alto = max(1, ancho // 2), max(1, alto // 2)
        return salida

    @property
    def chain_size(self) -> int:
        return sum(t[2] for t in self.mip_sizes())

    @property
    def frames_size(self) -> int:
        """Bytes esperados de pixeles: cadena de mips x fotogramas.

        No se multiplica por 6 en el flag que `gust_g1t.c` llama `CUBE_MAP`: ese bit
        viene puesto en las 14.412 texturas medidas y ninguna es un cubemap (el tamano
        cuadra con una sola cara).
        """
        return self.chain_size * self.nb_frames

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "format": self.format.name,
            "format_code": "0x%02x" % self.format_code,
            "width": self.width,
            "height": self.height,
            "mips": self.mip_count,
            "frames": self.nb_frames,
            "tile_system": self.tile_system,
            "flags": "0x%010x" % self.flags,
            "extended": self.extended,
            "header_offset": self.offset,
            "data_offset": self.data_offset,
            "data_size": self.data_size,
            "mip0_size": self.mip0_size,
            "chain_size": self.chain_size,
            "expected_size": self.frames_size,
            "padding": self.data_size - self.frames_size,
        }


@dataclass(frozen=True)
class G1TFile:
    """El `.g1t` entero, con todo lo necesario para reconstruirlo byte a byte."""

    version: bytes
    total_size: int
    header_size: int
    platform: int
    extra_size: int
    textures: tuple[Texture, ...]
    source: bytes          # los bytes originales (para poder copiar lo que no se toca)
    #: Bytes entre la cabecera fija (0x1C) y la tabla: `header_size` menos 0x1C.
    #: Medido: 4 B por textura de flags globales (a cero en los casos vistos), o vacio.
    pre_table: bytes = b""
    #: Datos extra globales, entre la tabla y la primera textura (`extra_size` B).
    #: Medido: 1008 B en las 3 G1T de version "1600"; 0 en el resto.
    global_extra: bytes = b""

    @property
    def platform_name(self) -> str:
        return PLATFORMS.get(self.platform, "0x%02x" % self.platform)

    def payload(self, texture: Texture | int) -> bytes:
        tex = texture if isinstance(texture, Texture) else self.textures[texture]
        return self.source[tex.data_offset:tex.data_offset + tex.data_size]

    def rebuild(self) -> bytes:
        """Reconstruye el fichero desde los campos parseados.

        La prueba de fuego del formato: si el parseo esta bien, los bytes salen
        identicos. Los 5 bytes de flags y la seccion `data[]` se conservan tal cual
        (se copian del original) porque su contenido es dato del juego, no geometria.
        """
        salida = bytearray()
        salida += MAGIC
        salida += self.version
        salida += struct.pack("<5I", self.total_size, self.header_size,
                              len(self.textures), self.platform, self.extra_size)
        salida += self.pre_table
        tabla = bytearray()
        cuerpo = bytearray()
        for tex in self.textures:
            # los offsets de la tabla son relativos a `header_size` e incluyen el
            # tamano de la propia tabla y los datos extra globales (medido)
            tabla += struct.pack("<I", 4 * len(self.textures) + len(self.global_extra)
                                 + len(cuerpo))
            cuerpo += bytes((tex.mip_sys, tex.format_code, tex.dxdy))
            cuerpo += tex.flags_raw
            cuerpo += tex.extra
            cuerpo += self.payload(tex)
        salida += tabla
        salida += self.global_extra
        salida += cuerpo
        return bytes(salida)

    def with_payload(self, index: int, datos: bytes) -> bytes:
        """Devuelve el fichero con el payload de `index` sustituido por `datos`.

        Exige que el payload nuevo mida exactamente lo mismo: reinyectar no puede
        mover los offsets de las demas texturas ni el tamano del `.g1t`.
        """
        tex = self.textures[index]
        if len(datos) != tex.data_size:
            raise G1TError(
                "textura %d: el payload nuevo mide %d B y el original %d B; la "
                "reinyeccion solo reescribe bytes, no cambia tamanos"
                % (index, len(datos), tex.data_size))
        fuente = bytearray(self.source)
        fuente[tex.data_offset:tex.data_offset + tex.data_size] = datos
        return bytes(fuente)


def parse(data: bytes, *, source_name: str = "") -> G1TFile:
    """Parsea un `.g1t` completo. Lanza `G1TError` si no cuadra."""
    if len(data) < HEADER_SIZE:
        raise G1TError("%s: %d B, no llega a la cabecera de %d B"
                       % (source_name or "g1t", len(data), HEADER_SIZE))
    if data[:4] != MAGIC:
        if data[:4] == MAGIC_BE:
            raise G1TError("%s: es un G1T big endian (\"G1TG\"); no medido en este "
                           "dump y no soportado" % (source_name or "g1t"))
        raise G1TError("%s: no empieza por GT1G (empieza por %r)"
                       % (source_name or "g1t", data[:4]))
    version = data[4:8]
    total_size, header_size, count, platform, extra_size = struct.unpack_from(
        "<5I", data, 8)
    if total_size != len(data):
        raise G1TError("%s: la cabecera declara %d B y el fichero mide %d"
                       % (source_name or "g1t", total_size, len(data)))
    if header_size < HEADER_SIZE or header_size + 4 * count + extra_size > len(data):
        raise G1TError("%s: header_size 0x%x con %d texturas y %d B extra no cabe en %d B"
                       % (source_name or "g1t", header_size, count, extra_size, len(data)))
    pre_table = data[HEADER_SIZE:header_size]
    tabla_fin = header_size + 4 * count
    global_extra = data[tabla_fin:tabla_fin + extra_size]
    offsets = struct.unpack_from("<%dI" % count, data, header_size)
    if any(off < 4 * count + extra_size for off in offsets):
        raise G1TError("%s: la tabla de offsets apunta dentro de la cabecera (%s)"
                       % (source_name or "g1t", offsets[:4]))
    textos: list[Texture] = []
    for i, off in enumerate(offsets):
        base = header_size + off
        if base + TEX_HEADER_SIZE > len(data):
            raise G1TError("%s: textura %d en 0x%x se sale del fichero"
                           % (source_name or "g1t", i, base))
        mip_sys, fmt, dxdy = struct.unpack_from("<3B", data, base)
        flags_raw = data[base + 3:base + TEX_HEADER_SIZE]
        pos = base + TEX_HEADER_SIZE
        siguiente = (header_size + offsets[i + 1]) if i + 1 < count else len(data)
        if siguiente < pos:
            raise G1TError("%s: textura %d no avanza (siguiente 0x%x < datos 0x%x)"
                           % (source_name or "g1t", i, siguiente, pos))
        # La seccion `data[]` va tras la cabecera de 8 B y empieza con su propio
        # tamano. NO se detecta por el flag EXTENDED_DATA: en este build el flag no
        # viene puesto y la seccion esta siempre (medido, ver docs/G1T-FORMAT.md).
        # Se detecta por coherencia: con seccion, los pixeles que quedan cuadran
        # exactos con la cadena de mips; sin ella, tambien.
        extra = _seccion_extra(data, pos, siguiente, mip_sys, fmt, dxdy, flags_raw)
        if extra:
            pos += len(extra)
        textos.append(Texture(
            index=i, offset=base, mip_sys=mip_sys, format_code=fmt, dxdy=dxdy,
            flags_raw=flags_raw, extra=extra,
            data_offset=pos, data_size=siguiente - pos))
    return G1TFile(version=version, total_size=total_size, header_size=header_size,
                   platform=platform, extra_size=extra_size,
                   textures=tuple(textos), source=data,
                   pre_table=pre_table, global_extra=global_extra)


def parse_file(path: str) -> G1TFile:
    with open(path, "rb") as fh:
        return parse(fh.read(), source_name=path)


def is_g1t(path: str) -> bool:
    """True si el fichero empieza por `GT1G`."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == MAGIC
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Swizzle: tiles de `format.tile` x `format.tile` bloques, con orden Z dentro
# ---------------------------------------------------------------------------

def _morton(x: int, y: int) -> int:
    """Valor Z de (x, y): bits de y en las posiciones pares, x en las impares."""
    m = 0
    bit = 0
    while (x >> bit) or (y >> bit):
        m |= ((y >> bit) & 1) << (2 * bit)
        m |= ((x >> bit) & 1) << (2 * bit + 1)
        bit += 1
    return m


def _grid(width: int, height: int, fmt: Format) -> tuple[int, int]:
    if fmt.compressed:
        return max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    return width, height


def tile_map(width: int, height: int, fmt: Format) -> list[int]:
    """Para cada bloque en orden de filas, el indice del bloque en el fichero.

    El tile se recorta cuando la textura es mas pequena que el: en Tegra el tile son
    8x8 bloques, pero una textura de 4x16 bloques no puede usar tiles de 8 (no caben
    y el tamano guardado es exacto, sin relleno), asi que baja a la potencia de 2 que
    divide las dos dimensiones. Es la misma restriccion que aplica `gust_g1t.c`.
    """
    bw, bh = _grid(width, height, fmt)
    if not fmt.swizzled:
        return list(range(bw * bh))
    t = max(1, fmt.tile)
    while t > 1 and (t > bw or t > bh or bw % t or bh % t):
        t //= 2
    columnas = (bw + t - 1) // t
    indice = [0] * (bw * bh)
    for y in range(bh):
        for x in range(bw):
            tile = (y // t) * columnas + (x // t)
            dentro = _morton(x % t, y % t)
            indice[y * bw + x] = tile * t * t + dentro
    return indice


def untile(payload: bytes, width: int, height: int, fmt: Format) -> bytes:
    """Pasa los pixeles del orden del fichero al orden de filas."""
    bw, bh = _grid(width, height, fmt)
    mapa = tile_map(width, height, fmt)
    b = fmt.block
    salida = bytearray(bw * bh * b)
    for i, origen in enumerate(mapa):
        salida[i * b:(i + 1) * b] = payload[origen * b:origen * b + b]
    return bytes(salida)


def retile(blocks: bytes, width: int, height: int, fmt: Format) -> bytes:
    """Pasa los pixeles del orden de filas al orden del fichero (inversa de `untile`)."""
    bw, bh = _grid(width, height, fmt)
    mapa = tile_map(width, height, fmt)
    b = fmt.block
    salida = bytearray(bw * bh * b)
    for i, destino in enumerate(mapa):
        salida[destino * b:destino * b + b] = blocks[i * b:(i + 1) * b]
    return bytes(salida)


__all__ = [
    "FLAG_CUBE_MAP",
    "FLAG_DOUBLE_HEIGHT",
    "FLAG_EXTENDED_DATA",
    "FLAG_NORMAL_MAP",
    "FLAG_SRGB",
    "FLAG_STANDARD_FLAGS",
    "FLAG_SURFACE_TEX",
    "FLAG_TEXTURE_ARRAY",
    "FORMATS",
    "Format",
    "G1TError",
    "G1TFile",
    "HEADER_SIZE",
    "MAGIC",
    "PLATFORMS",
    "TEX_HEADER_SIZE",
    "Texture",
    "format_of",
    "is_g1t",
    "parse",
    "parse_file",
    "retile",
    "tile_map",
    "untile",
]

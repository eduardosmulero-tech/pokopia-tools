"""Bancos de sonido `ASRS`/`KTSR` de los `.srsa`: leer, extraer y sustituir.

Un banco `.srsa` es un mini-contenedor `ASRS` (16 B) con un `KTSR` dentro. El
`KTSR` es una lista de *chunks* concatenados desde 0x50 hasta el final:

    u32  tipo      (big endian: 0xc5cccb70 sonido, 0xbd888c36 configuracion)
    u32  tamano    (little endian, INCLUYE la cabecera de 8 B)
    datos

Cada chunk de sonido lleva su propia cabecera y sus datos **dentro del chunk**,
con todos los desplazamientos relativos a su inicio: por eso mover un chunk de
sitio no rompe nada y sustituir un sonido es reescribir su chunk y tres
tamanos. Los chunks que no son sonido solo llevan el id del sonido (no
desplazamientos absolutos): 0 punteros medidos en los 403 bancos, ver
`informes/t_0ff3babd/AUDIO-KTSR.md`.

Cabecera del sonido (subcabecera de tipo `6fcab62e`, la unica interna que
aparece en este dump; los campos son los que lee `vgmstream` en
`src/meta/ktsr.c`, ISC):

    +0x00  u32be  tipo de subcabecera (6fcab62e interno, 793a1fd7 externo)
    +0x04  u32    tamano del chunk menos la cabecera de sonido (chunk - 0x48)
    +0x08  u32    hash del subtipo
    +0x0c  u32    canales
    +0x10  u8     formato (0x00 MS ADPCM, 0x01 KA1A)   [+0x11..+0x13 a cero]
    +0x14  s32    frecuencia de muestreo
    +0x18  s32    muestras
    +0x1c  u32    0
    +0x20  s32    inicio del bucle (-1 = sin bucle; el fin es `muestras`)
    +0x24  u32    disposicion de canales
    +0x28  u32    desplazamiento (relativo) a la cabecera extra
    +0x2c  u32    tamano de esa cabecera (4 en este dump)
    +0x30  u32    desplazamiento (relativo) a la tabla de inicios
    +0x34  u32    desplazamiento (relativo) a la tabla de tamanos
    +0x38  u32    hash
    +0x3c  u32    0
    +0x40  u32    desplazamiento (relativo) a un hash mas
    +0x44  u32    hash en coma flotante
    -- cabecera extra (en +0x28) --
    +0x00  s32    modo de bitrate KA1A (puede ser negativo) / tamano de frame u16
                  en MS ADPCM, en +0x02
    +0x04  u32    desplazamiento (relativo) del primer bloque de datos (= tabla
                  de inicios, alineado a 16)
    +0x08  u32    tamano de los datos (= tabla de tamanos; 1 entrada por canal)

Los nombres van cifrados con el LCG clasico de MSVC sembrado con el `audio_id`
del banco cuando el flag 0x0008 del chunk de sonido esta puesto; el algoritmo es
el de `decrypt_string_ktsr` de `vgmstream` (ISC) y se reproduce aqui.

Nada de este modulo escribe en el dump: `paths.guard_writable` lo impide.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Iterator

ASRS_MAGIC = b"ASRS"
KTSR_MAGIC = b"KTSR"

#: Identificador del KTSR de sonido (`77 7b 48 1a`, que vgmstream compara como
#: u32be contra 0x777B481A); aqui se lee little endian, como el resto del banco.
KTSR_ID_SOUND = 0x1A487B77

#: El `KTSR` empieza en 0x10 dentro del `ASRS`; sus chunks, en 0x40 + eso.
ASRS_HEADER_SIZE = 0x10
KTSR_CHUNKS_OFFSET = 0x40 + ASRS_HEADER_SIZE

#: Chunk de sonido y de configuracion.
CHUNK_SOUND = 0xC5CCCB70
CHUNK_CONFIG = 0xBD888C36

#: Subcabeceras de sonido: datos dentro del banco o en un `.srst` aparte.
SUBTYPES_INTERNAL = frozenset({0x41FDBD4E, 0x6FF273F9, 0x6FCAB62E, 0x6AD86FE9,
                               0x10250527})
SUBTYPES_EXTERNAL = frozenset({0x38D0437D, 0x3DEA478D, 0xDF92529F, 0x6422007C,
                               0x793A1FD7, 0xA0F4FC6C})

#: Subcabeceras que colocan sus tablas en +0x2c en vez de en +0x30.
SUBTYPES_TABLES_AT_2C = frozenset({0x41FDBD4E, 0x6FF273F9})

#: Formato de audio declarado en +0x10 de la subcabecera interna.
CODEC_BY_FORMAT = {0x00: "msadpcm", 0x01: "ka1a"}
FORMAT_BY_CODEC = {v: k for k, v in CODEC_BY_FORMAT.items()}

#: Extension con la que se extrae el flujo crudo de cada codec.
EXTENSION_BY_CODEC = {"ka1a": "ka1a", "msadpcm": "adpcm", "externo": "bin"}

#: Flag del chunk de sonido que cifra el nombre.
FLAG_ENCRYPTED_NAME = 0x0008

#: Relleno de los chunks: el siguiente empieza alineado a 16 B.
CHUNK_ALIGN = 0x10

#: Longitud maxima de un nombre en el banco.
NAME_MAX = 255

#: Vocabulario del LCG que cifra los nombres (MSVC rand, `vgmstream` ktsr.c).
LCG_MUL = 0x343FD
LCG_ADD = 0x269EC3


class SndError(Exception):
    """El banco no se puede leer o escribir con lo medido. `exit_code` es de la CLI."""

    exit_code = 1


class SndFormatError(SndError):
    """Los bytes no siguen el formato ASRS/KTSR (firma, chunk, subcabecera)."""


class SndStreamError(SndError):
    """Se ha pedido un stream que no existe o que no se puede sustituir asi."""


# ---------------------------------------------------------------------------
# Lectura de campos
# ---------------------------------------------------------------------------

def _u32be(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _u32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _s32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def _put_u32le(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", buf, offset, value)


def _put_u64le(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<Q", buf, offset, value)


def _align_up(value: int, alignment: int = CHUNK_ALIGN) -> int:
    resto = value % alignment
    return value if resto == 0 else value + alignment - resto


def decrypt_name(raw: bytes, seed: int) -> str:
    """Nombre del sonido tal cual lo guarda el juego (LCG + XOR, luego texto).

    Se reproduce `decrypt_string_ktsr` de `vgmstream` (`src/meta/ktsr.c`, ISC):
    el byte se descifra con el tercer byte del LCG y un 0 descifrado termina.
    El texto es ASCII casi siempre y Shift-JIS en contadas ocasiones.
    """
    salida = bytearray()
    for byte in raw[:NAME_MAX]:
        if byte == 0:
            break
        seed = (LCG_MUL * seed + LCG_ADD) & 0xFFFFFFFF
        valor = byte ^ ((seed >> 16) & 0xFF)
        if valor == 0:
            break
        salida.append(valor)
    return salida.decode("cp932", "replace")


def _read_string(data: bytes, offset: int) -> bytes:
    fin = data.find(b"\x00", offset, offset + NAME_MAX)
    return data[offset:] if fin < 0 else data[offset:fin]


# ---------------------------------------------------------------------------
# Estructuras
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """Un chunk del KTSR: tipo, posicion y tamano declarado (cabecera incluida)."""

    type: int
    offset: int
    size: int

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def is_sound(self) -> bool:
        return self.type == CHUNK_SOUND


@dataclass(frozen=True)
class Stream:
    """Un sonido del banco, con lo que hace falta para leerlo y para escribirlo."""

    index: int
    chunk_offset: int
    chunk_size: int
    sound_id: int
    flags: int
    header_offset: int
    subtype: int
    codec: str
    channels: int
    sample_rate: int
    num_samples: int
    loop_start: int
    data_offset: int
    data_size: int
    name: str
    external: bool

    @property
    def duration(self) -> float:
        return self.num_samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def data_end(self) -> int:
        return self.data_offset + self.data_size

    @property
    def prefix_size(self) -> int:
        """Bytes del chunk antes de los datos (cabecera de sonido + tablas)."""
        return self.data_offset - self.chunk_offset

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "sound_id": self.sound_id,
            "name": self.name,
            "codec": self.codec,
            "external": self.external,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "num_samples": self.num_samples,
            "duration": round(self.duration, 6),
            "loop_start": self.loop_start,
            "data_offset": self.data_offset,
            "data_size": self.data_size,
            "chunk_offset": self.chunk_offset,
            "chunk_size": self.chunk_size,
            "subtype": "0x%08x" % self.subtype,
            "flags": "0x%08x" % self.flags,
        }


@dataclass(frozen=True)
class Bank:
    """Cabecera de un banco y sus chunks, sin el audio."""

    size: int
    platform: int
    audio_id: int
    declared_size: int
    ktsr_size: int
    chunks: tuple[Chunk, ...]
    streams: tuple[Stream, ...]

    def stream(self, index: int) -> Stream:
        """El stream `index` (1..N) o `SndStreamError` con el rango valido."""
        if not 1 <= index <= len(self.streams):
            raise SndStreamError(
                "stream %d fuera de rango: el banco tiene %d (1..%d)"
                % (index, len(self.streams), len(self.streams)))
        return self.streams[index - 1]

    def as_dict(self) -> dict:
        return {
            "size": self.size,
            "declared_size": self.declared_size,
            "ktsr_size": self.ktsr_size,
            "platform": self.platform,
            "audio_id": "0x%08x" % self.audio_id,
            "chunks": len(self.chunks),
            "stream_count": len(self.streams),
        }

    @property
    def codecs(self) -> dict[str, int]:
        cuenta: dict[str, int] = {}
        for stream in self.streams:
            cuenta[stream.codec] = cuenta.get(stream.codec, 0) + 1
        return cuenta


# ---------------------------------------------------------------------------
# Analisis del banco
# ---------------------------------------------------------------------------

def iter_chunks(data: bytes, start: int = KTSR_CHUNKS_OFFSET) -> Iterator[Chunk]:
    """Recorre los chunks del KTSR. Un chunk roto corta el recorrido, no lo inventa."""
    pos = start
    total = len(data)
    while pos + 8 <= total:
        tipo = _u32be(data, pos)
        tam = _u32le(data, pos + 4)
        if tipo == 0xFFFFFFFF or tam < 8 or pos + tam > total:
            return
        yield Chunk(tipo, pos, tam)
        pos += tam


def _check_header(data: bytes) -> tuple[int, int, int]:
    """Valida ASRS/KTSR y devuelve (platform, audio_id, tamano declarado)."""
    if len(data) < KTSR_CHUNKS_OFFSET:
        raise SndFormatError(
            "banco de %d B: no llega a la cabecera de %d B"
            % (len(data), KTSR_CHUNKS_OFFSET))
    if data[:4] != ASRS_MAGIC:
        raise SndFormatError(
            "no empieza por ASRS (empieza por %r); solo se tratan los `.srsa`"
            % data[:4])
    declarado = struct.unpack_from("<Q", data, 8)[0]
    if data[ASRS_HEADER_SIZE:ASRS_HEADER_SIZE + 4] != KTSR_MAGIC:
        raise SndFormatError(
            "en 0x%x se esperaba KTSR y hay %r"
            % (ASRS_HEADER_SIZE, data[ASRS_HEADER_SIZE:ASRS_HEADER_SIZE + 4]))
    if _u32le(data, ASRS_HEADER_SIZE + 0x04) != KTSR_ID_SOUND:
        raise SndFormatError(
            "KTSR con id 0x%08x: se esperaba 0x%08x (sonido)"
            % (_u32le(data, ASRS_HEADER_SIZE + 0x04), KTSR_ID_SOUND))
    return data[ASRS_HEADER_SIZE + 0x0b], _u32le(data, ASRS_HEADER_SIZE + 0x0c), declarado


def _parse_stream(data: bytes, index: int, chunk: Chunk, audio_id: int) -> Stream:
    # Dos saltos, como vgmstream: delta en +0x14 y delta final en chunk+delta.
    rel = _u32le(data, chunk.offset + 0x14)
    hoff = chunk.offset + _u32le(data, chunk.offset + rel)
    if not chunk.offset < hoff < chunk.end:
        raise SndFormatError(
            "sonido %d en 0x%x: la cabecera cae en 0x%x, fuera del chunk"
            % (index, chunk.offset, hoff))
    subtype = _u32be(data, hoff)
    sound_id = _u32le(data, chunk.offset + 0x08)
    flags = _u32le(data, chunk.offset + 0x0c)
    canales = _u32le(data, hoff + 0x0c)

    name = ""
    rel_name = _u32le(data, chunk.offset + 0x18)
    if rel_name:
        crudo = _read_string(data, chunk.offset + rel_name)
        name = (decrypt_name(crudo, audio_id) if flags & FLAG_ENCRYPTED_NAME
                else crudo.decode("cp932", "replace"))

    if subtype in SUBTYPES_EXTERNAL:
        # Los datos viven en un `.srst` aparte: no estan en este banco.
        formato = _u32le(data, hoff + 0x14)
        return Stream(
            index=index, chunk_offset=chunk.offset, chunk_size=chunk.size,
            sound_id=sound_id, flags=flags, header_offset=hoff, subtype=subtype,
            codec="externo" if formato == 0x1001 else "0x%04x" % formato,
            channels=canales, sample_rate=0, num_samples=0, loop_start=-1,
            data_offset=_u32le(data, hoff + 0x34),
            data_size=_u32le(data, hoff + 0x38), name=name, external=True)

    if subtype not in SUBTYPES_INTERNAL:
        raise SndFormatError(
            "sonido %d en 0x%x: subcabecera 0x%08x desconocida (no medida en este dump)"
            % (index, chunk.offset, subtype))

    formato = data[hoff + 0x10]
    codec = CODEC_BY_FORMAT.get(formato, "fmt0x%02x" % formato)
    tablas = hoff + (0x2C if subtype in SUBTYPES_TABLES_AT_2C else 0x30)
    inicios = hoff + _u32le(data, tablas)
    tamanos = hoff + _u32le(data, tablas + 4)
    if not (hoff < inicios < chunk.end and hoff < tamanos < chunk.end):
        raise SndFormatError(
            "sonido %d en 0x%x: las tablas de datos caen fuera del chunk"
            % (index, chunk.offset))
    data_offset = hoff + _u32le(data, inicios)
    data_size = _u32le(data, tamanos)
    if data_offset + data_size > chunk.end or data_offset < hoff:
        raise SndFormatError(
            "sonido %d en 0x%x: datos 0x%x..0x%x fuera del chunk (fin 0x%x)"
            % (index, chunk.offset, data_offset, data_offset + data_size, chunk.end))
    return Stream(
        index=index, chunk_offset=chunk.offset, chunk_size=chunk.size,
        sound_id=sound_id, flags=flags, header_offset=hoff, subtype=subtype,
        codec=codec, channels=canales,
        sample_rate=_s32le(data, hoff + 0x14),
        num_samples=_s32le(data, hoff + 0x18),
        loop_start=_s32le(data, hoff + 0x20),
        data_offset=data_offset, data_size=data_size, name=name, external=False)


def parse(data: bytes) -> Bank:
    """Analiza el banco entero. No descomprime nada: el audio va crudo."""
    platform, audio_id, declarado = _check_header(data)
    if declarado != len(data):
        raise SndFormatError(
            "tamano declarado %d != tamano real %d (volcado mal hecho?)"
            % (declarado, len(data)))
    ktsr_size = _u32le(data, ASRS_HEADER_SIZE + 0x18)
    chunks = tuple(iter_chunks(data))
    if not chunks:
        raise SndFormatError("no hay chunks a partir de 0x%x" % KTSR_CHUNKS_OFFSET)
    ultimo = chunks[-1]
    if ultimo.end != len(data):
        raise SndFormatError(
            "los chunks acaban en 0x%x y el fichero en 0x%x"
            % (ultimo.end, len(data)))
    streams = []
    for chunk in chunks:
        if chunk.is_sound:
            streams.append(_parse_stream(data, len(streams) + 1, chunk, audio_id))
    return Bank(size=len(data), platform=platform, audio_id=audio_id,
                declared_size=declarado, ktsr_size=ktsr_size,
                chunks=chunks, streams=tuple(streams))


def read_bank(path: str) -> tuple[Bank, bytes]:
    """Devuelve (banco analizado, bytes) para no leer el fichero dos veces."""
    with open(path, "rb") as fh:
        data = fh.read()
    return parse(data), data


def payload(data: bytes, stream: Stream) -> bytes:
    """Bytes crudos del codec que toca el stream (sin cabeceras de banco)."""
    if stream.external:
        raise SndStreamError(
            "el stream %d es externo: sus datos viven en un `.srst` que este banco no lleva"
            % stream.index)
    return data[stream.data_offset:stream.data_end]


# ---------------------------------------------------------------------------
# Analisis de los bancos de una carpeta (para estadisticas y eleccion)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FolderStats:
    """Recuento de los bancos de una carpeta: lo que decide que via es viable."""

    banks: int
    streams: int
    internal: int
    codecs: dict[str, int]
    swappable: int
    same_size_same_bank: int
    same_size_anywhere: int
    same_size_groups: int
    problems: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "banks": self.banks,
            "streams": self.streams,
            "internal": self.internal,
            "codecs": dict(sorted(self.codecs.items())),
            "swappable": self.swappable,
            "same_size_same_bank": self.same_size_same_bank,
            "same_size_anywhere": self.same_size_anywhere,
            "same_size_groups": self.same_size_groups,
            "problems": list(self.problems),
        }


def scan_folder(paths: list[str]) -> FolderStats:
    """Analiza bancos sueltos y cuenta codecs, tamanos y pares sustituibles.

    * `swappable`: streams internos que viven en un banco con al menos otro
      stream interno — intercambiar dos chunks de sitio no necesita ni codec
      comun ni tamano comun, solo que los dos esten dentro del banco.
    * `same_size_same_bank`: streams internos que comparten (codec, tamano) con
      otro del **mismo** banco: eso es lo que permite copiar un flujo sin
      cambiar un solo tamano.
    * `same_size_anywhere`: lo mismo contando todo el arbol (el flujo puede
      venir de otro banco).
    """
    codecs: dict[str, int] = {}
    problemas: list[str] = []
    bancos = 0
    streams = 0
    internos = 0
    swappable = 0
    global_grupos: dict[tuple[str, int], int] = {}
    por_banco: dict[str, dict[tuple[str, int], int]] = {}
    for path in paths:
        try:
            banco, _ = read_bank(path)
        except (SndError, OSError) as exc:
            problemas.append("%s: %s" % (os.path.basename(path), exc))
            continue
        bancos += 1
        streams += len(banco.streams)
        propios = [s for s in banco.streams if not s.external]
        internos += len(propios)
        if len(propios) > 1:
            swappable += len(propios)
        cuenta: dict[tuple[str, int], int] = {}
        for stream in propios:
            codecs[stream.codec] = codecs.get(stream.codec, 0) + 1
            clave = (stream.codec, stream.data_size)
            cuenta[clave] = cuenta.get(clave, 0) + 1
            global_grupos[clave] = global_grupos.get(clave, 0) + 1
        por_banco[os.path.basename(path)] = cuenta
    mismo_banco = sum(n for cuenta in por_banco.values()
                      for n in cuenta.values() if n > 1)
    return FolderStats(
        banks=bancos, streams=streams, internal=internos, codecs=codecs,
        swappable=swappable, same_size_same_bank=mismo_banco,
        same_size_anywhere=sum(n for n in global_grupos.values() if n > 1),
        same_size_groups=sum(1 for n in global_grupos.values() if n > 1),
        problems=tuple(problemas))


def find_banks(root: str) -> list[str]:
    """Bancos `.srsa` de una carpeta (o el fichero suelto), ordenados."""
    if os.path.isfile(root):
        if not root.lower().endswith(".srsa"):
            raise SndError("no es un banco .srsa: %s" % root)
        return [root]
    if not os.path.isdir(root):
        raise SndError("no existe la carpeta: %s" % root)
    hallados = []
    for carpeta, _, ficheros in os.walk(root):
        for nombre in ficheros:
            if nombre.lower().endswith(".srsa"):
                hallados.append(os.path.join(carpeta, nombre))
    if not hallados:
        raise SndError(
            "no hay ningun .srsa bajo %s\n"
            "  extrae los bancos del .fdata con: pkp fdata extract --type srsa --out ..." % root)
    return sorted(hallados)


# ---------------------------------------------------------------------------
# Escritura: cambiar el orden de dos chunks (sin encoder)
# ---------------------------------------------------------------------------

def assemble(data: bytes, bodies: list[bytes]) -> bytes:
    """Reconstruye el banco con los cuerpos dados, en ese orden.

    La cabecera ASRS/KTSR (0x50 B) se copia tal cual y los tamanos se recalculan
    para que el resultado cuadre consigo mismo. Cada cuerpo es el chunk completo
    (cabecera de chunk incluida), de modo que sus desplazamientos relativos
    siguen siendo validos aunque cambie de posicion.
    """
    salida = bytearray(data[:KTSR_CHUNKS_OFFSET])
    for cuerpo in bodies:
        if len(cuerpo) < 8 or _u32le(cuerpo, 4) != len(cuerpo):
            raise SndError(
                "assemble: un cuerpo de %d B no declara ese tamano en su cabecera"
                % len(cuerpo))
        salida += cuerpo
    total = len(salida)
    _put_u64le(salida, 8, total)
    _put_u32le(salida, ASRS_HEADER_SIZE + 0x18, total - ASRS_HEADER_SIZE)
    _put_u32le(salida, ASRS_HEADER_SIZE + 0x1c, total - ASRS_HEADER_SIZE)
    return bytes(salida)


def _chunk_positions(banco: Bank) -> dict[int, int]:
    """Posicion de cada chunk en la lista, por su desplazamiento."""
    return {chunk.offset: pos for pos, chunk in enumerate(banco.chunks)}


def swap_streams(data: bytes, first: int, second: int) -> bytes:
    """Intercambia de sitio dos chunks de sonido. El banco conserva su tamano.

    El sonido que ocupaba la posicion N suena en la M y al reves: cambia el
    orden del indice, no los bytes de audio. No necesita encoder ni que los dos
    sonidos compartan codec o tamano, y los demas streams quedan intactos.
    """
    banco = parse(data)
    a = banco.stream(first)
    b = banco.stream(second)
    if a.external or b.external:
        raise SndStreamError(
            "no se intercambian streams externos (sus datos no estan en el banco)")
    if a.chunk_offset == b.chunk_offset:
        raise SndStreamError("swap: los dos indices son el mismo stream (%d)" % first)
    posiciones = _chunk_positions(banco)
    pos_a, pos_b = posiciones[a.chunk_offset], posiciones[b.chunk_offset]
    chunks = list(banco.chunks)
    bodies = [data[c.offset:c.end] for c in chunks]
    bodies[pos_a], bodies[pos_b] = bodies[pos_b], bodies[pos_a]
    return assemble(data, bodies)


# ---------------------------------------------------------------------------
# Escritura: sustituir los datos de un stream
# ---------------------------------------------------------------------------

def _audio_extra(data: bytes, stream: Stream) -> tuple[int, int]:
    """(desplazamiento relativo, tamano) de la cabecera extra de un sonido interno."""
    extra = _u32le(data, stream.header_offset + 0x28)
    tamano = _u32le(data, stream.header_offset + 0x2C)
    return extra, tamano


def _tables_rel(stream: Stream) -> int:
    """Desplazamiento relativo a la cabecera de sonido de la tabla de inicios."""
    return 0x2C if stream.subtype in SUBTYPES_TABLES_AT_2C else 0x30


def replace_stream(data: bytes, index: int, nuevo: bytes,
                   donor: tuple[bytes, Stream] | None = None) -> bytes:
    """Sustituye los datos del stream `index` por `nuevo` y ajusta los tamanos.

    Con `donor` (los bytes del banco de origen y su stream) copia tambien la
    cabecera que describe el audio —formato, canales, frecuencia, muestras,
    bucle y modo de bitrate—, que es lo que hace falta cuando el flujo viene de
    otro sonido. Sin `donor` se conserva la cabecera del destino y el que llama
    responde de que los datos encajan con ella.

    El chunk crece o mengua con los datos; los chunks siguientes se desplazan y
    los tres tamanos del banco (ASRS, KTSR y chunk) se recalculan. El resto del
    banco se copia byte a byte.
    """
    banco = parse(data)
    stream = banco.stream(index)
    if stream.external:
        raise SndStreamError(
            "el stream %d es externo: sus datos no estan en este banco" % index)
    if not nuevo:
        raise SndStreamError("el reemplazo esta vacio (0 B)")

    hoff = stream.header_offset
    cabecera = hoff - stream.chunk_offset
    cuerpo = bytearray(data[stream.chunk_offset:stream.data_offset])
    extra_dest, extra_size = _audio_extra(data, stream)
    tablas = cabecera + _tables_rel(stream)
    inicios_rel = _u32le(bytes(cuerpo), tablas)
    tamanos_rel = _u32le(bytes(cuerpo), tablas + 4)
    if extra_dest + extra_size > min(inicios_rel, tamanos_rel):
        raise SndFormatError(
            "sonido %d: la cabecera extra (0x%x+%d) pisa las tablas de datos (0x%x, 0x%x)"
            % (index, extra_dest, extra_size, inicios_rel, tamanos_rel))

    if donor is not None:
        donor_data, donor_stream = donor
        if donor_stream.external:
            raise SndStreamError("el origen es un stream externo: no trae datos")
        if donor_stream.codec != stream.codec:
            raise SndStreamError(
                "codec distinto: el destino es %s y el origen %s"
                % (stream.codec, donor_stream.codec))
        origen = donor_stream.header_offset
        extra_org, _ = _audio_extra(donor_data, donor_stream)
        for desde, hasta in ((0x0C, 0x14), (0x14, 0x1C), (0x20, 0x28)):
            cuerpo[cabecera + desde:cabecera + hasta] = (
                donor_data[origen + desde:origen + hasta])
        cuerpo[cabecera + extra_dest:cabecera + extra_dest + extra_size] = (
            donor_data[origen + extra_org:origen + extra_org + extra_size])

    _put_u32le(cuerpo, cabecera + tamanos_rel, len(nuevo))
    cuerpo += nuevo
    relleno = _align_up(len(cuerpo)) - len(cuerpo)
    if relleno:
        cuerpo += b"\x00" * relleno
    _put_u32le(cuerpo, 4, len(cuerpo))
    _put_u32le(cuerpo, cabecera + 4, len(cuerpo) - cabecera)

    chunks = list(banco.chunks)
    pos = _chunk_positions(banco)[stream.chunk_offset]
    bodies = [data[c.offset:c.end] for c in chunks]
    bodies[pos] = bytes(cuerpo)
    return assemble(data, bodies)


# ---------------------------------------------------------------------------
# Escritura: meter audio propio (codificado por nosotros) en un stream
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StreamAudio:
    """Audio ya codificado, listo para ocupar el sitio de un stream.

    `payload` son los bytes crudos del codec (sin cabecera de banco).
    `block_size` solo lo usa MS ADPCM: es el tamano de bloque que se escribe en
    la cabecera extra y el que hay que usar para codificar `payload`.
    """

    codec: str
    sample_rate: int
    num_samples: int
    payload: bytes
    block_size: int = 0
    loop_start: int = -1

    def as_dict(self) -> dict:
        return {
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "num_samples": self.num_samples,
            "duration": (round(self.num_samples / self.sample_rate, 6)
                         if self.sample_rate else 0.0),
            "payload_bytes": len(self.payload),
            "block_size": self.block_size,
            "loop_start": self.loop_start,
        }


def msadpcm_block_size(data: bytes, stream: Stream) -> int:
    """Bytes por bloque que declara la cabecera extra de un stream MS ADPCM."""
    if stream.codec != "msadpcm":
        raise SndStreamError(
            "el stream %d es %s: el tamano de bloque solo se lee en MS ADPCM"
            % (stream.index, stream.codec))
    extra, tamano = _audio_extra(data, stream)
    if tamano < 4:
        raise SndFormatError(
            "sonido %d: cabecera extra de %d B, sin el par de campos de MS ADPCM"
            % (stream.index, tamano))
    return struct.unpack_from("<H", data, stream.header_offset + extra + 2)[0]


def set_stream_audio(data: bytes, index: int, audio: StreamAudio) -> bytes:
    """Mete `audio` en el stream `index`: datos y cabecera, con los tamanos al dia.

    A diferencia de `replace_stream` (que solo reescribe bytes y, como mucho,
    copia la cabecera de otro sonido del juego), aqui la cabecera describe
    **nuestro** audio: frecuencia, numero de muestras, bucle y -- en MS ADPCM --
    el par muestras-por-bloque/bytes-por-bloque que el codificador ha usado.

    El codec no se cambia nunca: si el destino es KA1A, no hay codificador y se
    rechaza (ver `docs/AUDIO-PROPIO.md`).
    """
    banco = parse(data)
    stream = banco.stream(index)
    if stream.external:
        raise SndStreamError(
            "el stream %d es externo: sus datos no estan en este banco" % index)
    if audio.codec != stream.codec:
        raise SndStreamError(
            "el stream %d es %s y el audio es %s: no se cambia de codec"
            % (index, stream.codec, audio.codec))
    if not audio.payload:
        raise SndStreamError("el audio esta vacio (0 B)")
    if audio.sample_rate <= 0:
        raise SndStreamError("frecuencia fuera de rango: %d" % audio.sample_rate)
    if audio.num_samples < 1:
        raise SndStreamError("sin muestras: %d" % audio.num_samples)
    if stream.codec != "msadpcm":
        raise SndStreamError(
            "no hay codificador para %s; solo MS ADPCM se puede codificar aqui "
            "(ver docs/AUDIO-PROPIO.md)" % stream.codec)

    bloque = audio.block_size
    if bloque <= 7:
        raise SndStreamError("bloque MS ADPCM de %d B: demasiado pequeno" % bloque)
    if len(audio.payload) % bloque:
        raise SndStreamError(
            "el flujo mide %d B y no es multiplo del bloque de %d B"
            % (len(audio.payload), bloque))
    from .audio import msadpcm_block_samples as audio_block_samples  # sin ciclo: audio no importa snd
    por_bloque = audio_block_samples(bloque)
    capacidad = (len(audio.payload) // bloque) * por_bloque
    if audio.num_samples > capacidad:
        raise SndStreamError(
            "%d muestras no caben en %d B de MS ADPCM (%d bloques x %d muestras = %d)"
            % (audio.num_samples, len(audio.payload), len(audio.payload) // bloque,
               por_bloque, capacidad))

    extra, tamano = _audio_extra(data, stream)
    if tamano < 4:
        raise SndFormatError(
            "sonido %d: cabecera extra de %d B, sin sitio para el par de MS ADPCM"
            % (index, tamano))
    parcheado = bytearray(data)
    h = stream.header_offset
    struct.pack_into("<i", parcheado, h + 0x14, audio.sample_rate)
    struct.pack_into("<i", parcheado, h + 0x18, audio.num_samples)
    struct.pack_into("<i", parcheado, h + 0x20, audio.loop_start)
    struct.pack_into("<HH", parcheado, h + extra, por_bloque, bloque)
    return replace_stream(bytes(parcheado), index, audio.payload)


# ---------------------------------------------------------------------------
# Extraccion y escritura en disco
# ---------------------------------------------------------------------------

def extract(path: str, out_dir: str, indexes: list[int] | None = None
            ) -> list[tuple[Stream, str]]:
    """Escribe el flujo crudo de cada stream como `<banco>.<n>.<codec>`.

    Devuelve (stream, ruta). Volver a lanzarlo reescribe los mismos bytes.
    """
    from . import paths as pkp_paths

    pkp_paths.guard_writable(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    banco, data = read_bank(path)
    base = os.path.splitext(os.path.basename(path))[0]
    pedidos = banco.streams if indexes is None else [banco.stream(i) for i in indexes]
    escritos: list[tuple[Stream, str]] = []
    for stream in pedidos:
        if stream.external:
            continue
        destino = os.path.join(
            out_dir, "%s.%03d.%s" % (base, stream.index,
                                     EXTENSION_BY_CODEC.get(stream.codec, "bin")))
        pkp_paths.guard_writable(destino)
        with open(destino, "wb") as salida:
            salida.write(data[stream.data_offset:stream.data_end])
        escritos.append((stream, destino))
    return escritos


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def write_bank(path: str, data: bytes) -> None:
    """Escribe el banco, con copia `<ruta>.orig` la primera vez. Idempotente."""
    from . import paths as pkp_paths

    pkp_paths.guard_writable(path)
    respaldo = path + ".orig"
    if os.path.exists(path) and not os.path.exists(respaldo):
        with open(path, "rb") as origen, open(respaldo, "wb") as destino:
            destino.write(origen.read())
    temporal = path + ".tmp"
    with open(temporal, "wb") as salida:
        salida.write(data)
    os.replace(temporal, path)


__all__ = [
    "ASRS_HEADER_SIZE",
    "ASRS_MAGIC",
    "Bank",
    "CHUNK_ALIGN",
    "CHUNK_CONFIG",
    "CHUNK_SOUND",
    "Chunk",
    "EXTENSION_BY_CODEC",
    "FolderStats",
    "KTSR_CHUNKS_OFFSET",
    "KTSR_MAGIC",
    "Stream",
    "SndError",
    "SndFormatError",
    "SndStreamError",
    "SUBTYPES_EXTERNAL",
    "SUBTYPES_INTERNAL",
    "StreamAudio",
    "assemble",
    "decrypt_name",
    "extract",
    "find_banks",
    "iter_chunks",
    "msadpcm_block_size",
    "parse",
    "payload",
    "read_bank",
    "replace_stream",
    "scan_folder",
    "set_stream_audio",
    "sha256_bytes",
    "swap_streams",
    "write_bank",
]

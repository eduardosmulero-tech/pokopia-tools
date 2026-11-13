"""Streams de audio externos de Koei Tecmo: los ficheros `.srst` (`TSRS`/`KTSR`).

Un `.srst` es el hermano de un banco `.srsa` cuando las pistas **no** viven
dentro del banco. El banco guarda, por cada pista, una subcabecera externa con
la posicion y el tamano de sus datos (ver `docs/AUDIO-KTSR.md` §4); el audio
esta aqui, cifrado con Blowfish ECB con la clave del propio banco.

Formato medido en el build 2.0.1a (detalle y salidas literales en
`docs/AUDIO-SRST.md`):

    +0x00  IDRK0000            cabecera de entrada de `.fdata` (48 B) + 8 B de
                               relleno; el payload empieza en
                               `entry_size - compressed_size` (56 B en el dump)
    --- payload ---
    +0x00  'TSRS'              mini-contenedor (el `ASRS` de los `.srsa`)
    +0x04  u32     0
    +0x08  u64     tamano del payload
    +0x10  'KTSR'              cabecera del stream-KTSR
    +0x14  u32be   0x0294DDFC  id de KTSR de tipo *stream* (0x777B481A es el de
                               memoria de los `.srsa`)
    +0x18  u16     1
    +0x1A  u16     0x05F0
    +0x1B  u8      5           plataforma (la misma que en los `.srsa`)
    +0x1C  u32     audio id
    +0x28  u32 x2  tamano del KTSR (= payload - 0x10), repetido
    +0x30  u8      longitud de la clave Blowfish (7 en este dump)
    +0x31  ...     la clave, igual que la del banco
    +0x50  chunks  uno por pista, concatenados hasta el final

Cada chunk de pista (`0x09D4F415`, big-endian como todos los tipos de chunk):

    +0x00  u32be   0x09D4F415
    +0x04  u32le   tamano del chunk = 0x20 + data_size
    +0x08  u32     **sound id** (el mismo que el `sound id` del chunk del banco
                   y el `cue` de la tabla que lo referencia; 83/83 medidos)
    +0x0C  u32     0x20: donde empiezan los datos, relativo al chunk
    +0x10  u32     data_size (multiplo de 8: es el texto cifrado)
    +0x14  ...     ceros

Los datos de la pista son un bloque Blowfish ECB que empieza por una cabecera
`KA1A` de 40 B (**dentro** del cifrado) y sigue con los frames entrelazados por
canal (`[512 muestras L][512 muestras R]...`). No hay checksum ni hash por
pista: el unico u32 con significado en la cabecera del chunk es el `sound id`
(ver `docs/AUDIO-SRST.md` §5, donde se descartan crc32, adler32, FNV, MD5, SHA-1,
SHA-256 y BLAKE2 sobre el texto claro y el cifrado). Por eso una pista se puede
reescribir **en su sitio** mientras quepa en su `data_size`: no se mueve ni un
desplazamiento del fichero ni del banco.

Todo lo que escribe este modulo pasa por `paths.guard_writable` y deja
`<fichero>.orig` la primera vez; `revert()` vuelve atras en un comando.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Sequence

from . import audio, snd
from .blowfish import BLOQUE, Blowfish

TSRS_MAGIC = b"TSRS"
IDRK_MAGIC = b"IDRK0000"
KTSR_MAGIC = b"KTSR"

#: Id del KTSR de tipo *stream* (leido big-endian, como en `snd.py`).
KTSR_ID_STREAM = 0x0294DDFC

#: Cabecera de una entrada `IDRK` de `.fdata` y su relleno hasta el payload.
IDRK_ENTRY_HEADER = 0x30

#: Tipo de chunk de pista.
CHUNK_STREAM = 0x09D4F415

#: `type_ktid` de una entrada `.srst` en los `.fdata` (nombre `srst`).
TYPE_KTID_SRST = 0x0D34474D

#: El KTSR empieza en 0x10 dentro del payload, igual que en un `.srsa`.
KTSR_OFFSET = 0x10

#: Chunks a partir de aqui (0x40 de cabecera KTSR tras el `TSRS`).
CHUNK_TABLE_OFFSET = KTSR_OFFSET + 0x40

#: Cabecera de cada chunk de pista, antes de sus datos.
TRACK_HEADER_SIZE = 0x20

#: Cabecera `KA1A` que va **dentro** de los datos cifrados de cada pista.
KA1A_MAGIC = b"KA1A"
KA1A_HEADER_SIZE = 0x28


class SrstError(snd.SndError):
    """Problema de formato o de uso con un `.srst`."""


@dataclass(frozen=True)
class Track:
    """Una pista del `.srst`, con lo que declara su cabecera `KA1A`."""

    index: int
    chunk_offset: int      # relativo al payload
    chunk_size: int
    sound_id: int
    data_offset: int       # relativo al KTSR del payload (= chunk_offset + 0x20)
    data_size: int
    cipher_size: int       # bytes cifrados: data_size redondeado a 8
    codec: str
    channels: int
    sample_rate: int
    num_samples: int
    loop_start: int
    loop_region: int
    bitrate_mode: int
    tracks: int = 1

    @property
    def duration(self) -> float:
        return self.num_samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def loop_end(self) -> int:
        """Fin del bucle, o -1 si no tiene."""
        return self.loop_start + self.loop_region if self.loop_region > 0 else -1

    @property
    def audio_size(self) -> int:
        """Bytes de audio (sin la cabecera `KA1A`) que declara la pista."""
        return self.data_size - KA1A_HEADER_SIZE

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "sound_id": self.sound_id,
            "codec": self.codec,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "num_samples": self.num_samples,
            "duration": round(self.duration, 6),
            "loop_start": self.loop_start,
            "loop_end": self.loop_end,
            "bitrate_mode": self.bitrate_mode,
            "data_offset": self.data_offset,
            "data_size": self.data_size,
            "chunk_offset": self.chunk_offset,
            "chunk_size": self.chunk_size,
        }


@dataclass(frozen=True)
class Srst:
    """Un `.srst` analizado: cabecera, clave y pistas. Sin los datos descifrados."""

    size: int
    prefix: int
    payload_size: int
    audio_id: int
    key: bytes
    platform: int
    version: int
    tracks: tuple[Track, ...]

    def track(self, index: int) -> Track:
        if not 1 <= index <= len(self.tracks):
            raise SrstError("pista %d fuera de rango: el `.srst` tiene %d (1..%d)"
                            % (index, len(self.tracks), len(self.tracks)))
        return self.tracks[index - 1]

    def by_data_offset(self, offset: int) -> Track | None:
        """La pista cuyo `data_offset` (relativo al KTSR) es `offset`."""
        for track in self.tracks:
            if track.data_offset == offset:
                return track
        return None

    def as_dict(self) -> dict:
        return {
            "size": self.size,
            "prefix": self.prefix,
            "payload_size": self.payload_size,
            "audio_id": "0x%08x" % self.audio_id,
            "key_bytes": len(self.key),
            "platform": self.platform,
            "version": self.version,
            "tracks": len(self.tracks),
        }


# ---------------------------------------------------------------------------
# Analisis
# ---------------------------------------------------------------------------

def payload_offset(data: bytes) -> int:
    """Donde empieza el payload `TSRS`: 0, o tras la entrada `IDRK` de `.fdata`."""
    if data[:4] == TSRS_MAGIC:
        return 0
    if data[:8] != IDRK_MAGIC:
        raise SrstError(
            "no empieza por TSRS ni por IDRK0000 (empieza por %r): no es un .srst"
            % data[:8])
    if len(data) < IDRK_ENTRY_HEADER:
        raise SrstError("cabecera IDRK truncada (%d B)" % len(data))
    entry_size, compressed = struct.unpack_from("<QQ", data, 8)
    if entry_size != len(data):
        raise SrstError(
            "la entrada declara %d B y el fichero mide %d (volcado mal hecho?)"
            % (entry_size, len(data)))
    prefix = entry_size - compressed
    if not IDRK_ENTRY_HEADER <= prefix < 0x1000:
        raise SrstError("cabecera de entrada de %d B: fuera de lo medido (%d..%d)"
                        % (prefix, IDRK_ENTRY_HEADER, 0xFFF))
    return prefix


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _align8(valor: int) -> int:
    """Bytes cifrados de una pista: su `data_size` redondeado al bloque de 8.

    Medido: 35 de las 83 pistas del `.srst` grande tienen `data_size % 8 == 4`
    (el ultimo frame de 258 B no es multiplo de 8) y el bloque que falta se
    completa con los 4 B de relleno del chunk, que son multiplos de 16.
    """
    return (valor + BLOQUE - 1) // BLOQUE * BLOQUE


def _align16(valor: int) -> int:
    return (valor + 15) // 16 * 16


def _s32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def ka1a_fields(cabecera: bytes) -> dict:
    """Campos de la cabecera `KA1A` de 40 B que va dentro de los datos de la pista.

    `tamano` son los bytes de frames (sin esta cabecera), `region` es la
    **longitud** del bucle (el fin es `bucle + region`) y `modo` el modo de
    bitrate, que fija el tamano del frame.
    """
    if cabecera[:4] != KA1A_MAGIC:
        raise SrstError("la cabecera de la pista no empieza por KA1A (%r)"
                        % cabecera[:4])
    tamano, canales, pistas, hz, muestras, bucle, region, modo = \
        struct.unpack_from("<8i", cabecera, 4)
    return {"tamano": tamano, "canales": canales, "pistas": pistas, "hz": hz,
            "muestras": muestras, "bucle": bucle, "region": region, "modo": modo}


def decode_track(plano: bytes) -> tuple[list[list[int]], dict]:
    """Decodifica una pista descifrada: (muestras por canal, campos del header).

    El entrelazado es por frame (`[512 del canal 0][512 del canal 1]...`), asi
    que cada canal se decodifica con los frames que le tocan.
    """
    campos = ka1a_fields(plano[:KA1A_HEADER_SIZE])
    frame = audio.ka1a_frame_size(campos["modo"])
    datos = plano[KA1A_HEADER_SIZE:KA1A_HEADER_SIZE + campos["tamano"]]
    if len(datos) != campos["tamano"]:
        raise SrstError("la pista declara %d B de audio y trae %d"
                        % (campos["tamano"], len(datos)))
    trozos = [datos[i * frame:(i + 1) * frame]
              for i in range(len(datos) // frame)]
    total = campos["canales"] * campos["pistas"]
    salida = [audio.ka1a_decode_pcm16(b"".join(trozos[c::total]), campos["modo"],
                                      campos["muestras"])
              for c in range(total)]
    return salida, campos


def parse(data: bytes) -> Srst:
    """Analiza el `.srst` entero. Solo descifra 40 B por pista (su cabecera)."""
    prefix = payload_offset(data)
    payload_size = len(data) - prefix
    if data[prefix:prefix + 4] != TSRS_MAGIC:
        raise SrstError("en 0x%x se esperaba TSRS y hay %r"
                        % (prefix, data[prefix:prefix + 4]))
    declarado = struct.unpack_from("<Q", data, prefix + 8)[0]
    if declarado != payload_size:
        raise SrstError("el payload declara %d B y mide %d"
                        % (declarado, payload_size))
    ktsr = prefix + KTSR_OFFSET
    if data[ktsr:ktsr + 4] != KTSR_MAGIC:
        raise SrstError("en 0x%x se esperaba KTSR y hay %r"
                        % (ktsr, data[ktsr:ktsr + 4]))
    tipo = struct.unpack_from(">I", data, ktsr + 4)[0]
    if tipo != KTSR_ID_STREAM:
        raise SrstError(
            "KTSR con id 0x%08x: se esperaba 0x%08x (stream). Un .srsa lleva "
            "0x777b481a (memoria) y no se trata aqui" % (tipo, KTSR_ID_STREAM))
    if data[ktsr + 0x0B] not in (4, 5):
        raise SrstError("plataforma %d: solo se han medido 4 y 5"
                        % data[ktsr + 0x0B])
    tam_ktsr = _u32(data, ktsr + 0x18)
    if tam_ktsr != _u32(data, ktsr + 0x1C) or tam_ktsr != payload_size - KTSR_OFFSET:
        raise SrstError(
            "tamanos del KTSR incoherentes: 0x18=%d 0x1c=%d, payload-0x10=%d"
            % (tam_ktsr, _u32(data, ktsr + 0x1C), payload_size - KTSR_OFFSET))
    largo = data[ktsr + 0x20]
    key = data[ktsr + 0x21:ktsr + 0x21 + largo]
    try:
        cifrador = Blowfish(key)
    except ValueError as exc:
        raise SrstError("clave de %d B en el KTSR: %s" % (largo, exc)) from None

    pistas: list[Track] = []
    pos = prefix + CHUNK_TABLE_OFFSET
    fin = len(data)
    while pos < fin:
        if pos + TRACK_HEADER_SIZE > fin:
            raise SrstError("chunk truncado en 0x%x (quedan %d B)"
                            % (pos, fin - pos))
        chunk_type = struct.unpack_from(">I", data, pos)[0]
        if chunk_type != CHUNK_STREAM:
            raise SrstError(
                "chunk 0x%08x en 0x%x: solo se ha medido 0x%08x"
                % (chunk_type, pos, CHUNK_STREAM))
        tam = _u32(data, pos + 4)
        data_rel = _u32(data, pos + 0x0C)
        data_size = _u32(data, pos + 0x10)
        cifrado = _align8(data_size)
        if tam < TRACK_HEADER_SIZE + cifrado:
            raise SrstError(
                "chunk en 0x%x: declara %d B, su data_size es %d y necesita al "
                "menos %d B para los bloques de %d B"
                % (pos, tam, data_size, TRACK_HEADER_SIZE + cifrado, BLOQUE))
        if tam != _align16(TRACK_HEADER_SIZE + data_size):
            raise SrstError(
                "chunk en 0x%x: declara %d B y 0x20 + data_size alineado a 16 son "
                "%d (la geometria medida en el dump)"
                % (pos, tam, _align16(TRACK_HEADER_SIZE + data_size)))
        if data_rel != TRACK_HEADER_SIZE:
            raise SrstError(
                "chunk en 0x%x: los datos empiezan en +0x%x y solo se ha medido "
                "+0x%x" % (pos, data_rel, TRACK_HEADER_SIZE))
        if pos + tam > fin:
            raise SrstError("chunk en 0x%x se sale del fichero (0x%x > 0x%x)"
                            % (pos, pos + tam, fin))
        inicio = pos + data_rel
        campos = ka1a_fields(cifrador.descifra(data[inicio:inicio + KA1A_HEADER_SIZE]))
        pistas.append(Track(
            index=len(pistas) + 1,
            chunk_offset=pos - prefix,
            chunk_size=tam,
            sound_id=_u32(data, pos + 0x08),
            data_offset=inicio - ktsr,
            data_size=data_size,
            cipher_size=cifrado,
            codec="ka1a",
            channels=campos["canales"],
            sample_rate=campos["hz"],
            num_samples=campos["muestras"],
            loop_start=campos["bucle"],
            loop_region=campos["region"],
            bitrate_mode=campos["modo"],
            tracks=campos["pistas"],
        ))
        pos += tam
    if not pistas:
        raise SrstError("no hay chunks de pista a partir de 0x%x"
                        % (prefix + CHUNK_TABLE_OFFSET))
    return Srst(size=len(data), prefix=prefix, payload_size=payload_size,
                audio_id=_u32(data, ktsr + 0x0C), key=key,
                platform=data[ktsr + 0x0B], version=struct.unpack_from(
                    "<H", data, ktsr + 8)[0], tracks=tuple(pistas))


def read(path: str) -> tuple[Srst, bytes]:
    """Devuelve (fichero analizado, bytes) para no leerlo dos veces."""
    with open(path, "rb") as fh:
        data = fh.read()
    return parse(data), data


# ---------------------------------------------------------------------------
# Audio propio: cabecera KA1A + frames entrelazados
# ---------------------------------------------------------------------------

def ka1a_header(channels: int, tracks: int, sample_rate: int, num_samples: int,
                loop_start: int, loop_region: int, bitrate_mode: int,
                data_bytes: int) -> bytes:
    """Cabecera `KA1A` de 40 B que va dentro de los datos de la pista.

    `data_bytes` son los bytes de frames (sin esta cabecera). `loop_region` es
    la **longitud** del bucle, no su fin: el fin es `loop_start + loop_region`
    (es lo que lee `init_vgmstream_ka1a` en `vgmstream`).
    """
    if not 1 <= channels <= 8:
        raise SrstError("canales fuera de rango: %d" % channels)
    if tracks < 1:
        raise SrstError("pistas fuera de rango: %d" % tracks)
    if sample_rate <= 0 or num_samples < 1:
        raise SrstError("frecuencia/muestras fuera de rango: %d Hz, %d muestras"
                        % (sample_rate, num_samples))
    if loop_start >= 0:
        if loop_start >= num_samples:
            raise SrstError("bucle en %d con %d muestras: no cabe"
                            % (loop_start, num_samples))
        if loop_region <= 0:
            raise SrstError("bucle en %d con longitud %d" % (loop_start, loop_region))
    elif loop_region:
        raise SrstError("sin bucle (inicio %d) pero con longitud %d"
                        % (loop_start, loop_region))
    if data_bytes <= 0:
        raise SrstError("datos de %d B: no hay audio" % data_bytes)
    cabecera = KA1A_MAGIC + struct.pack(
        "<8i", data_bytes, channels, tracks, sample_rate, num_samples,
        loop_start, max(0, loop_region), bitrate_mode)
    return cabecera.ljust(KA1A_HEADER_SIZE, b"\x00")


def interleave(channels: Sequence[bytes], frame_size: int) -> bytes:
    """Entrelaza los frames de cada canal: `[frame 0 del canal 0][frame 0 del 1]...`."""
    if not channels:
        raise SrstError("sin canales que entrelazar")
    if len({len(c) for c in channels}) != 1:
        raise SrstError("los canales no miden lo mismo: %s"
                        % [len(c) for c in channels])
    if len(channels[0]) % frame_size:
        raise SrstError("%d B de canal no son multiplos del frame de %d B"
                        % (len(channels[0]), frame_size))
    if len(channels) == 1:
        return bytes(channels[0])
    salida = bytearray()
    for i in range(0, len(channels[0]), frame_size):
        for canal in channels:
            salida += canal[i:i + frame_size]
    return bytes(salida)


def build_track(track: Track, canales: Sequence[Sequence[int]],
                loop_start: int | None = None) -> bytes:
    """Codifica `canales` (una lista de muestras por canal) como pista `.srst`.

    Usa el **codec, el modo de bitrate y el numero de canales del destino**: no
    se cambia el formato de la pista, solo su audio. `loop_start = None` deja el
    bucle del destino; `-1` lo quita y `>= 0` lo pone (hasta el final).
    """
    if track.codec != "ka1a":
        raise SrstError("la pista %d es %s: este escritor escribe KA1A"
                        % (track.index, track.codec))
    if len(canales) != track.channels:
        raise SrstError(
            "la pista %d es de %d canales y el audio trae %d: no se mezcla solo"
            % (track.index, track.channels, len(canales)))
    muestras = len(canales[0])
    if any(len(canal) != muestras for canal in canales):
        raise SrstError("los canales no tienen las mismas muestras: %s"
                        % [len(canal) for canal in canales])
    if loop_start is None:
        loop_start = track.loop_start
    if loop_start >= 0:
        region = muestras - loop_start
    else:
        region = 0
    frame = audio.ka1a_frame_size(track.bitrate_mode)
    flujos = [audio.ka1a_encode(list(canal), track.bitrate_mode) for canal in canales]
    entrelazado = interleave(flujos, frame)
    cabecera = ka1a_header(track.channels, track.tracks, track.sample_rate,
                           muestras, loop_start, region, track.bitrate_mode,
                           len(entrelazado))
    plano = cabecera + entrelazado
    if len(plano) > track.data_size:
        raise SrstError(
            "el audio propio ocupa %d B (cabecera incluida) y la pista %d declara "
            "%d B: elige menos segundos o un modo de bitrate menor"
            % (len(plano), track.index, track.data_size))
    return plano


# ---------------------------------------------------------------------------
# Escritura: una pista en su sitio, sin mover un solo desplazamiento
# ---------------------------------------------------------------------------

def _cifrado_en_su_sitio(data: bytearray, srst: Srst, track: Track,
                         plano: bytes) -> None:
    """Cifra `plano` y lo escribe en la ranura de la pista, con relleno cifrado."""
    if plano[:4] != KA1A_MAGIC:
        raise SrstError("el flujo no empieza por KA1A (%r)" % plano[:4])
    campos = ka1a_fields(plano[:KA1A_HEADER_SIZE])
    if len(plano) != KA1A_HEADER_SIZE + campos["tamano"]:
        raise SrstError(
            "el flujo mide %d B y su cabecera declara %d B de audio (%d con "
            "cabecera)" % (len(plano), campos["tamano"],
                           KA1A_HEADER_SIZE + campos["tamano"]))
    if campos["canales"] != track.channels:
        raise SrstError("el flujo es de %d canales y la pista de %d"
                        % (campos["canales"], track.channels))
    if len(plano) > track.data_size:
        raise SrstError("el flujo (%d B) no cabe en la pista (%d B)"
                        % (len(plano), track.data_size))
    inicio = srst.prefix + KTSR_OFFSET + track.data_offset
    cifrado = Blowfish(srst.key).cifra_relleno_cero(plano, track.cipher_size)
    data[inicio:inicio + track.cipher_size] = cifrado


def with_track(data: bytes, index: int, plano: bytes) -> bytes:
    """Sustituye la pista `index` por `plano` (KA1A ya codificado, sin cifrar).

    El fichero conserva tamano y desplazamientos: solo cambian los datos de esa
    pista. Lo que sobre de su ranura se rellena con ceros **cifrados**, que es lo
    que ve el decodificador cuando la pista es mas corta.
    """
    srst = parse(data)
    track = srst.track(index)
    salida = bytearray(data)
    _cifrado_en_su_sitio(salida, srst, track, plano)
    return bytes(salida)


def with_audio(data: bytes, index: int, canales: Sequence[Sequence[int]],
               loop_start: int | None = None) -> bytes:
    """Codifica `canales` y los mete en la pista `index`."""
    srst = parse(data)
    track = srst.track(index)
    return with_track(data, index, build_track(track, canales, loop_start))


def swap_tracks(data: bytes, first: int, second: int) -> bytes:
    """Intercambia el audio de dos pistas, si caben la una en la otra.

    Sin mover desplazamientos, intercambiar exige el **mismo `data_size`**. Si
    no coincide se dice, en vez de recortar audio en silencio.
    """
    srst = parse(data)
    a = srst.track(first)
    b = srst.track(second)
    if a.index == b.index:
        raise SrstError("swap: las dos pistas son la misma (%d)" % a.index)
    if a.data_size != b.data_size:
        raise SrstError(
            "no se intercambian: la pista %d mide %d B y la %d mide %d B. Sin "
            "mover desplazamientos solo se puede intercambiar audio del mismo "
            "tamano" % (a.index, a.data_size, b.index, b.data_size))
    cifrador = Blowfish(srst.key)
    pos_a = srst.prefix + KTSR_OFFSET + a.data_offset
    pos_b = srst.prefix + KTSR_OFFSET + b.data_offset
    salida = bytearray(data)
    plano_a = cifrador.descifra(data[pos_a:pos_a + a.cipher_size])
    plano_b = cifrador.descifra(data[pos_b:pos_b + b.cipher_size])
    salida[pos_a:pos_a + a.cipher_size] = cifrador.cifra(plano_b)
    salida[pos_b:pos_b + b.cipher_size] = cifrador.cifra(plano_a)
    return bytes(salida)


def track_plain(data: bytes, index: int) -> bytes:
    """El audio descifrado de la pista (`KA1A` + frames), del tamano que declara."""
    srst = parse(data)
    track = srst.track(index)
    inicio = srst.prefix + KTSR_OFFSET + track.data_offset
    plano = Blowfish(srst.key).descifra(data[inicio:inicio + track.cipher_size])
    campos = ka1a_fields(plano[:KA1A_HEADER_SIZE])
    return plano[:KA1A_HEADER_SIZE + campos["tamano"]]


# ---------------------------------------------------------------------------
# Ficheros: escribir con copia y volver atras
# ---------------------------------------------------------------------------

def write_srst(path: str, data: bytes) -> None:
    """Escribe el `.srst`, con copia `<ruta>.orig` la primera vez. Idempotente."""
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


def revert(path: str) -> tuple[str, str]:
    """Restaura `path` desde `path.orig`. Devuelve (sha restaurado, sha del .orig)."""
    from . import paths as pkp_paths

    respaldo = path + ".orig"
    if not os.path.exists(respaldo):
        raise SrstError("no hay copia de la que volver: falta %s" % respaldo)
    pkp_paths.guard_writable(path)
    with open(respaldo, "rb") as fh:
        original = fh.read()
    temporal = path + ".tmp"
    with open(temporal, "wb") as salida:
        salida.write(original)
    os.replace(temporal, path)
    return (hashlib.sha256(original).hexdigest(),
            pkp_paths.sha256_file(respaldo))


def sha256_payload(data: bytes) -> str:
    """`sha256` del payload (`TSRS` en adelante): lo que ve el decodificador."""
    return hashlib.sha256(data[payload_offset(data):]).hexdigest()


__all__ = [
    "BLOQUE",
    "CHUNK_STREAM",
    "CHUNK_TABLE_OFFSET",
    "IDRK_ENTRY_HEADER",
    "IDRK_MAGIC",
    "KA1A_HEADER_SIZE",
    "KA1A_MAGIC",
    "KTSR_ID_STREAM",
    "KTSR_MAGIC",
    "KTSR_OFFSET",
    "Srst",
    "SrstError",
    "TRACK_HEADER_SIZE",
    "TSRS_MAGIC",
    "TYPE_KTID_SRST",
    "Track",
    "build_track",
    "interleave",
    "ka1a_header",
    "parse",
    "payload_offset",
    "read",
    "revert",
    "sha256_payload",
    "swap_tracks",
    "track_plain",
    "with_audio",
    "with_track",
    "write_srst",
]

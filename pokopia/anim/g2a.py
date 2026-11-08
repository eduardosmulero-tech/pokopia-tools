"""Animaciones `G2A` de KTGL: leer, exportar y reconstruir byte a byte.

Lo que hay en el dump es lo que el contenedor llama `g1a` (`type_ktid`
`0x6fa91671`), pero **el magic real del fichero es `G2A_`**, no `G1A_`: en el
build 2.0.1a, 17.428 de los 17.457 ficheros de ese tipo son `G2A` version `0400`
(los otros 29 son `G1A_` version `2400`, el formato anterior, que no se lee
aqui). Es la misma trampa de fin de letra que `_M1G`/`GT1G`: el `u32` canonico es
`0x4732415F` = `G2A_`, y en disco, little-endian, salen los bytes
`5f 41 32 47` = `_A2G`. Buscar la cadena `G2A_` en el dump da cero.

Formato (medido; contrastado con `fmt_g1m` de Joschuka, GPL-3.0, `processG2A`,
que usa el mismo esquema para `G2A` version `0500`; aqui la version es `0400`):

    0x00  4s   magic           en disco b"_A2G"  (u32 LE 0x4732415F = "G2A_")
    0x04  4s   version         b"0400" en los 17.457 ficheros
    0x08  u32  fileSize        == tamano real del fichero
    0x0c  f32  frameRate       60.0
    0x10  u32  packed          bits 0..17  = longitud en frames
                               bits 18..31 = tamano de la seccion de huesos (B, /4)
    0x14  u32  timingSize      bytes de la seccion de tiempos
    0x18  u32  keyBlockCount   bloques de datos cuantizados de 32 B
    0x1c  u32  reserved        0

    seccion de huesos  (la seccion de tiempos empieza justo despues)
      boneCount = boneSectionSize // 4 entradas de u32:
        bits 0..3    numero de splines del hueso (0..15)
        bits 4..13   boneID (10 bits; si baja respecto al anterior, la vuelta
                     siguiente suma 1024 — ver `_resolver_bone_ids`)
        bits 14..31  offset de sus registros dentro de la seccion de tiempos

    seccion de tiempos
      por cada hueso, `splines` registros consecutivos:
        u16  opcode            0 = rotacion, 1 = traslacion, 2 = escala
        u16  keyFrameCount
        i32  firstDataIndex    indice del primer bloque de 0x20
        u16[keyFrameCount] timings   frame absoluto de cada clave
        relleno hasta multiplo de 4 (absoluto)

    seccion de datos: keyBlockCount bloques de 32 B = 4 x i64
      cada i64 lleva cuatro campos: z (bits 0..19), y (20..39), x (40..59),
      exponente (60..63); los campos son enteros con signo de 20 bits y el
      valor es `campo * 2**(exponente - 15)`.

      El bloque `k` de un spline es el tramo que empieza en `timings[k]`; sus
      cuatro filas son los coeficientes de un polinomio cubico por componente:
      `v(t) = r1 + r2*t + r3*t**2 + r4*t**3`, con `t` en [0,1) dentro del tramo
      y cada fila con su propio exponente. En rotacion el resultado es un vector
      eje-angulo (radianes) que se pasa a cuaternion con la formula de Rodrigues.

La invariante que cierra el formato, comprobada en los 17.457:

    0x20 + boneSectionSize + timingSize + keyBlockCount * 32 == fileSize

y la seccion de tiempos se recorre entera: la suma de los registros (con su
relleno) da exactamente `timingSize`.

Solo stdlib. Este modulo no toca el dump: recibe bytes y devuelve bytes.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

#: `u32` canonico del magic; en disco se lee al reves (b"_A2G").
MAGIC = 0x4732415F
MAGIC_BYTES = b"_A2G"

#: Versiones que este lector entiende. La `0500` cambia el empaquetado de la
#: seccion de huesos (boneID de 8 bits, offset de 20) y mete un `u32` extra.
VERSIONES = (b"0400",)

HEADER_SIZE = 0x20
KEYBLOCK_SIZE = 0x20

#: opcode -> nombre de canal.
CANALES = {0: "rotation", 1: "translation", 2: "scale"}

#: Exponente base de cada fila: `valor = campo * 2**(exp - BIAS_EXP)`.
BIAS_EXP = 15


class AnimError(Exception):
    """El fichero no es una animacion que este lector entienda. `exit_code` CLI."""

    exit_code = 1


class AnimFormatError(AnimError):
    """Los bytes no siguen el formato (magic, version, tamano, seccion)."""


def _signed20(valor: int) -> int:
    """Entero con signo de 20 bits."""
    valor &= 0xFFFFF
    return valor - 0x100000 if valor & 0x80000 else valor


#: Magic del formato anterior (G1A), que este lector no lee.
MAGIC_G1A = 0x4731415F


def _error_magic(magic: int) -> str:
    if magic == MAGIC_G1A:
        return ("es un G1A_ (formato anterior, 29 de las 17.457 animaciones del"
                " dump): su cabecera no es la de G2A y este lector no lo soporta."
                " Ver docs/ANIMACIONES-G2A.md")
    return ("magic 0x%08x, se esperaba 0x%08x (G2A_, en disco %r)"
            % (magic, MAGIC, MAGIC_BYTES))


@dataclass(frozen=True)
class Row:
    """Una de las cuatro filas de un bloque: tres campos de 20 bits y exponente."""

    raw: int
    x: int
    y: int
    z: int
    exp: int

    @classmethod
    def from_int(cls, raw: int) -> "Row":
        sin_signo = raw & 0xFFFFFFFFFFFFFFFF
        return cls(raw, _signed20(sin_signo >> 40), _signed20(sin_signo >> 20),
                   _signed20(sin_signo), (sin_signo >> 60) & 0xF)

    @property
    def scale(self) -> float:
        return 2.0 ** (self.exp - BIAS_EXP)

    @property
    def vector(self) -> tuple[float, float, float]:
        return (self.x * self.scale, self.y * self.scale, self.z * self.scale)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "exp": self.exp}


@dataclass(frozen=True)
class KeyBlock:
    """32 B: los cuatro coeficientes cubicos de un tramo."""

    rows: tuple[Row, Row, Row, Row]

    @classmethod
    def from_bytes(cls, datos: bytes) -> "KeyBlock":
        filas = tuple(Row.from_int(v) for v in struct.unpack("<4q", datos))
        return cls(filas)  # type: ignore[arg-type]

    def to_bytes(self) -> bytes:
        return struct.pack("<4q", *(row.raw for row in self.rows))

    def coefficients(self) -> tuple[tuple[float, float, float], ...]:
        """Los cuatro coeficientes por componente, como ternas `(x, y, z)`."""
        return tuple(row.vector for row in self.rows)

    def as_dict(self) -> dict:
        return {"rows": [row.raw for row in self.rows]}


@dataclass
class Spline:
    """Una pista de un hueso: un canal (rotacion, traslacion o escala)."""

    opcode: int
    timings: tuple[int, ...]
    first_data_index: int
    #: Un bloque por clave; se rellena al parsear y se reescribe en `build`.
    keys: list[KeyBlock] = field(default_factory=list)

    @property
    def channel(self) -> str:
        return CANALES.get(self.opcode, "0x%02x" % self.opcode)

    @property
    def keyframe_count(self) -> int:
        return len(self.timings)

    def value_at(self, tramo: int, t: float) -> tuple[float, float, float]:
        """Evalua el cubico del tramo `tramo` en `t` (0..1) por componente."""
        coefs = self.keys[tramo].coefficients()
        t2 = t * t
        t3 = t2 * t
        return tuple(  # type: ignore[return-value]
            coefs[0][i] + coefs[1][i] * t + coefs[2][i] * t2 + coefs[3][i] * t3
            for i in range(3))

    def sample(self, tramo: int, t: float) -> tuple[float, ...]:
        """Valor del canal: cuaternion `(x, y, z, w)` o vector `(x, y, z)`."""
        valor = self.value_at(tramo, t)
        if self.opcode != 0:
            return valor
        return axis_angle_to_quaternion(valor)


@dataclass
class Bone:
    """Un hueso animado: su id y sus pistas."""

    bone_id_raw: int
    splines: list[Spline]
    bone_id: int = 0          # resuelto con el desbordamiento de 1024 (10 bits)
    timing_offset: int = 0    # tal como se leyo; se recalcula al escribir


@dataclass
class Animation:
    """Una animacion completa, con todo lo necesario para reconstruirla."""

    version: bytes
    frame_rate: float
    length_frames: int
    bones: list[Bone]
    key_blocks: list[KeyBlock]
    reserved: int = 0
    #: Relleno no nulo encontrado en el pad de los registros de tiempos.
    pad_bytes: dict[int, bytes] = field(default_factory=dict)

    @property
    def bone_count(self) -> int:
        return len(self.bones)

    @property
    def spline_count(self) -> int:
        return sum(len(b.splines) for b in self.bones)

    @property
    def keyframe_count(self) -> int:
        return sum(s.keyframe_count for b in self.bones for s in b.splines)

    @property
    def duration_s(self) -> float:
        return self.length_frames / self.frame_rate if self.frame_rate else 0.0

    @property
    def channels(self) -> dict[str, int]:
        cuenta: dict[str, int] = {}
        for bone in self.bones:
            for spline in bone.splines:
                cuenta[spline.channel] = cuenta.get(spline.channel, 0) + 1
        return dict(sorted(cuenta.items()))

    @property
    def opcodes(self) -> dict[int, int]:
        cuenta: dict[int, int] = {}
        for bone in self.bones:
            for spline in bone.splines:
                cuenta[spline.opcode] = cuenta.get(spline.opcode, 0) + 1
        return dict(sorted(cuenta.items()))

    @property
    def used_blocks(self) -> int:
        """Bloques referenciados por algun spline (puede ser < keyBlockCount)."""
        return max((s.first_data_index + s.keyframe_count
                    for b in self.bones for s in b.splines), default=0)

    def bone_by_id(self, bone_id: int) -> Bone:
        for bone in self.bones:
            if bone.bone_id == bone_id:
                return bone
        raise AnimError("no hay hueso con id %d" % bone_id)

    def as_dict(self) -> dict:
        return {
            "format": "G2A",
            "version": self.version.decode("ascii", "replace"),
            "frame_rate": self.frame_rate,
            "length_frames": self.length_frames,
            "duration_s": round(self.duration_s, 6),
            "bones": self.bone_count,
            "splines": self.spline_count,
            "keyframes": self.keyframe_count,
            "key_blocks": len(self.key_blocks),
            "used_blocks": self.used_blocks,
            "channels": self.channels,
            "opcodes": {str(k): v for k, v in self.opcodes.items()},
        }


# ---------------------------------------------------------------------------
# Matematicas del canal de rotacion
# ---------------------------------------------------------------------------

def axis_angle_to_quaternion(v: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """Rodrigues: vector eje-angulo (radianes) -> cuaternion `(x, y, z, w)`.

    Misma formula que `function2` de `fmt_g1m`: `s = sin(a/2)/a` y `w = cos(a/2)`,
    con el caso degenerado `a ~ 0` resuelto a `0.5` para no dividir por cero.
    """
    x, y, z = v
    angulo = math.sqrt(x * x + y * y + z * z)
    s = math.sin(angulo * 0.5)
    c = math.cos(angulo * 0.5)
    k = s / angulo if angulo > 0.000011920929 else 0.5
    return (x * k, y * k, z * k, c)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _resolver_bone_ids(bones: list[Bone]) -> None:
    """Asigna `bone_id` con la regla del 10 bits (cuando baja, +1024)."""
    ultimo = 0
    vuelta = 0
    for bone in bones:
        if bone.bone_id_raw < ultimo:
            vuelta += 1
        ultimo = bone.bone_id_raw
        bone.bone_id = bone.bone_id_raw + vuelta * 1024


@dataclass(frozen=True)
class Header:
    """Los ocho campos de la cabecera, sin tocar el resto del fichero."""

    magic: int
    version: bytes
    file_size: int
    frame_rate: float
    length_frames: int
    bone_section_size: int
    timing_size: int
    key_block_count: int
    reserved: int

    @property
    def bone_count(self) -> int:
        return self.bone_section_size // 4

    @property
    def header_size(self) -> int:
        return HEADER_SIZE + self.bone_section_size

    def as_dict(self) -> dict:
        return {
            "version": self.version.decode("ascii", "replace"),
            "file_size": self.file_size,
            "frame_rate": self.frame_rate,
            "length_frames": self.length_frames,
            "duration_s": round(self.length_frames / self.frame_rate, 6)
            if self.frame_rate else 0.0,
            "bone_section_size": self.bone_section_size,
            "bone_count": self.bone_count,
            "timing_size": self.timing_size,
            "key_block_count": self.key_block_count,
            "reserved": self.reserved,
            "computed_size": (HEADER_SIZE + self.bone_section_size + self.timing_size
                              + self.key_block_count * KEYBLOCK_SIZE),
        }


def peek(datos: bytes) -> Header:
    """Lee solo la cabecera (32 B): es lo que usa `pkp anim list` sin parsear."""
    if len(datos) < HEADER_SIZE:
        raise AnimFormatError(
            "el fichero tiene %d B, no llega a la cabecera de %d B"
            % (len(datos), HEADER_SIZE))
    magic, version, tam, fps = struct.unpack_from("<I4sIf", datos, 0)
    if magic != MAGIC:
        raise AnimFormatError(_error_magic(magic))
    packed, timing_size, key_count, reservado = struct.unpack_from("<4I", datos, 0x10)
    return Header(magic, version, tam, fps, packed & 0x3FFFF,
                  (packed >> 18) & 0x3FFF, timing_size, key_count, reservado)


#: Rango del campo de 20 bits de cada componente.
CAMPO_MAX = 0x7FFFF
CAMPO_MIN = -0x80000


def encode_component(valor: float, exp: int) -> int:
    """Campo de 20 bits que representa `valor` con el exponente `exp`.

    El exponente se comparte con los otros dos componentes del `int64`: para
    tocar un valor sin estropear los demas se reescribe **solo** su campo. Si
    el valor no cabe con ese exponente, se avisa en vez de recortar.
    """
    if not 0 <= exp <= 0xF:
        raise AnimError("exponente %r fuera de 0..15" % exp)
    escala = 2.0 ** (exp - BIAS_EXP)
    campo = int(round(valor / escala))
    if not CAMPO_MIN <= campo <= CAMPO_MAX:
        raise AnimError(
            "el valor %g no cabe en el campo de 20 bits con exponente %d"
            " (rango %.6g .. %.6g); usa otro componente u otro tramo"
            % (valor, exp, CAMPO_MIN * escala, CAMPO_MAX * escala))
    return campo


def replace_component(row: Row, eje: str, valor: float) -> Row:
    """Devuelve la fila con el componente `eje` (`x`/`y`/`z`) cambiado."""
    if eje not in ("x", "y", "z"):
        raise AnimError("eje %r no valido (x, y, z)" % eje)
    campo = encode_component(valor, row.exp)
    sin_signo = row.raw & 0xFFFFFFFFFFFFFFFF
    desplazamiento = {"z": 0, "y": 20, "x": 40}[eje]
    mascara = 0xFFFFF << desplazamiento
    sin_signo = (sin_signo & ~mascara) | ((campo & 0xFFFFF) << desplazamiento)
    return Row.from_int(sin_signo - (1 << 64) if sin_signo >> 63 else sin_signo)


def parse(datos: bytes, *, estricto: bool = True) -> Animation:
    """Lee una animacion `G2A`. `estricto` valida tamano y secciones."""
    if len(datos) < HEADER_SIZE:
        raise AnimFormatError(
            "el fichero tiene %d B, no llega a la cabecera de %d B"
            % (len(datos), HEADER_SIZE))
    magic, version, tam, fps = struct.unpack_from("<I4sIf", datos, 0)
    if magic != MAGIC:
        raise AnimFormatError(_error_magic(magic))
    if version not in VERSIONES:
        raise AnimFormatError(
            "version %r no soportada (solo %s)"
            % (version, ", ".join(v.decode() for v in VERSIONES)))
    if tam != len(datos):
        raise AnimFormatError(
            "la cabecera declara %d B y el fichero tiene %d" % (tam, len(datos)))
    packed, timing_size, key_count, reservado = struct.unpack_from("<4I", datos, 0x10)
    longitud = packed & 0x3FFFF
    bone_size = (packed >> 18) & 0x3FFF
    if bone_size % 4:
        raise AnimFormatError(
            "la seccion de huesos mide %d B, no es multiplo de 4" % bone_size)
    calculado = HEADER_SIZE + bone_size + timing_size + key_count * KEYBLOCK_SIZE
    if calculado != len(datos):
        raise AnimFormatError(
            "la geometria declarada da %d B (0x20 + %d + %d + %d*32) y el fichero"
            " tiene %d: sobran %d"
            % (calculado, bone_size, timing_size, key_count, len(datos),
               len(datos) - calculado))

    huesos: list[Bone] = []
    declarados: list[int] = []
    for i in range(bone_size // 4):
        empaquetado = struct.unpack_from("<I", datos, HEADER_SIZE + i * 4)[0]
        huesos.append(Bone(bone_id_raw=(empaquetado >> 4) & 0x3FF,
                           splines=[],
                           timing_offset=(empaquetado >> 14) & 0x3FFFF))
        declarados.append(empaquetado & 0xF)
    _resolver_bone_ids(huesos)

    inicio_tiempos = HEADER_SIZE + bone_size
    fin_tiempos = inicio_tiempos + timing_size
    if fin_tiempos > len(datos):
        raise AnimFormatError(
            "la seccion de tiempos acaba en 0x%x y el fichero en 0x%x"
            % (fin_tiempos, len(datos)))

    relleno: dict[int, bytes] = {}
    for indice, hueso in enumerate(huesos):
        pos = inicio_tiempos + hueso.timing_offset
        if hueso.timing_offset % 4:
            raise AnimFormatError(
                "hueso %d: offset de tiempos %d no esta alineado a 4"
                % (indice, hueso.timing_offset))
        if pos < inicio_tiempos or pos + 8 > fin_tiempos:
            raise AnimFormatError(
                "hueso %d: offset de tiempos %d se sale de la seccion"
                % (indice, hueso.timing_offset))
        for _ in range(declarados[indice]):
            if pos + 8 > fin_tiempos:
                raise AnimFormatError(
                    "hueso %d: registro de spline en 0x%x fuera de la seccion"
                    % (indice, pos))
            opcode, n_claves, primer_indice = struct.unpack_from("<HHi", datos, pos)
            pos += 8
            if n_claves == 0:
                raise AnimFormatError(
                    "hueso %d: spline con 0 claves en 0x%x" % (indice, pos - 8))
            if pos + 2 * n_claves > fin_tiempos:
                raise AnimFormatError(
                    "hueso %d: %d tiempos en 0x%x se salen de la seccion"
                    % (indice, n_claves, pos))
            timings = struct.unpack_from("<%dH" % n_claves, datos, pos)
            pos += 2 * n_claves
            sobra = (-pos) % 4
            if sobra:
                trozo = datos[pos:pos + sobra]
                if any(trozo):
                    relleno[pos] = trozo
                pos += sobra
            if timings[0] > timings[-1]:
                raise AnimFormatError(
                    "hueso %d: tiempos decrecientes en 0x%x" % (indice, pos))
            hueso.splines.append(Spline(opcode, tuple(timings), primer_indice))

    inicio_datos = fin_tiempos
    bloques = [
        KeyBlock.from_bytes(datos[inicio_datos + i * KEYBLOCK_SIZE:
                                  inicio_datos + (i + 1) * KEYBLOCK_SIZE])
        for i in range(key_count)]

    anim = Animation(version=version, frame_rate=fps, length_frames=longitud,
                     bones=huesos, key_blocks=bloques, reserved=reservado,
                     pad_bytes=relleno)
    _enlazar_bloques(anim)
    return anim


def _enlazar_bloques(anim: Animation) -> None:
    """Reparte los bloques globales a cada spline segun `firstDataIndex`."""
    total = len(anim.key_blocks)
    for hueso in anim.bones:
        for spline in hueso.splines:
            inicio = spline.first_data_index
            fin = inicio + spline.keyframe_count
            if inicio < 0 or fin > total:
                raise AnimFormatError(
                    "hueso %d, canal %s: bloques %d..%d fuera de %d"
                    % (hueso.bone_id, spline.channel, inicio, fin, total))
            spline.keys = anim.key_blocks[inicio:fin]


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def build(anim: Animation) -> bytes:
    """Reconstruye el fichero: offsets, tamanos y cabecera se recalculan.

    Los desplazamientos de la seccion de tiempos se derivan del orden de los
    huesos y del tamano real de cada registro (8 B + 2 por clave, alineado a 4).
    Si el original los tenia de otra forma, el resultado no sera identico: es
    justo lo que la prueba de ida y vuelta detecta.
    """
    cuerpo_tiempos = bytearray()
    huesos_info = bytearray()
    siguiente_bloque = 0
    for hueso in anim.bones:
        if len(hueso.splines) > 0xF:
            raise AnimError("hueso %d: %d splines (maximo 15)"
                            % (hueso.bone_id, len(hueso.splines)))
        if hueso.bone_id_raw > 0x3FF:
            raise AnimError("hueso %d: boneID de mas de 10 bits" % hueso.bone_id)
        if len(cuerpo_tiempos) > 0x3FFFF:
            raise AnimError("seccion de tiempos de mas de 0x3FFFF B")
        offset = len(cuerpo_tiempos)
        for spline in hueso.splines:
            if spline.first_data_index != siguiente_bloque:
                raise AnimError(
                    "hueso %d, canal %s: firstDataIndex %d y el bloque que toca"
                    " es %d; los bloques no van en orden y reescribirlos"
                    " perderia datos"
                    % (hueso.bone_id, spline.channel, spline.first_data_index,
                       siguiente_bloque))
            if len(spline.keys) != spline.keyframe_count:
                raise AnimError(
                    "hueso %d, canal %s: %d claves y %d bloques"
                    % (hueso.bone_id, spline.channel, spline.keyframe_count,
                       len(spline.keys)))
            siguiente_bloque += spline.keyframe_count
            registro = bytearray(struct.pack("<HHi", spline.opcode,
                                             spline.keyframe_count,
                                             spline.first_data_index))
            registro += struct.pack("<%dH" % spline.keyframe_count, *spline.timings)
            relleno = (-(len(cuerpo_tiempos) + len(registro))) % 4
            cuerpo_tiempos += registro
            cuerpo_tiempos += bytes(relleno)
        empaquetado = ((len(hueso.splines) & 0xF)
                       | ((hueso.bone_id_raw & 0x3FF) << 4)
                       | ((offset & 0x3FFFF) << 14))
        huesos_info += struct.pack("<I", empaquetado)

    if siguiente_bloque != len(anim.key_blocks):
        raise AnimError(
            "los splines usan %d bloques y la animacion declara %d: la escritura"
            " perderia datos" % (siguiente_bloque, len(anim.key_blocks)))
    if len(huesos_info) // 4 > 0x3FFF:
        raise AnimError("demasiados huesos: %d" % (len(huesos_info) // 4))
    if len(cuerpo_tiempos) > 0xFFFFFFFF:
        raise AnimError("seccion de tiempos de %d B" % len(cuerpo_tiempos))
    if anim.length_frames > 0x3FFFF:
        raise AnimError("longitud de %d frames (maximo 0x3FFFF)"
                        % anim.length_frames)

    packed = anim.length_frames | (len(huesos_info) << 18)
    datos = bytearray(struct.pack("<I4sIf", MAGIC, anim.version, 0, anim.frame_rate))
    datos += struct.pack("<4I", packed, len(cuerpo_tiempos), len(anim.key_blocks),
                         anim.reserved)
    datos += huesos_info
    datos += cuerpo_tiempos
    for bloque in anim.key_blocks:
        datos += bloque.to_bytes()
    struct.pack_into("<I", datos, 0x08, len(datos))
    return bytes(datos)


def roundtrip(datos: bytes) -> tuple[Animation, bytes]:
    """`parse` + `build` de una vez; devuelve `(animacion, bytes reescritos)`."""
    anim = parse(datos)
    return anim, build(anim)


def set_keyframe_value(anim: Animation, *, bone_id: int, channel: str, frame: int,
                       axis: str, value: float) -> dict:
    """Cambia **un** componente del valor de una clave y devuelve el parte.

    Reescribe solo el campo de 20 bits de ese componente en la fila constante
    (`c0`) del bloque de esa clave, asi que los otros dos componentes y el resto
    del fichero no se tocan. El valor leido de vuelta puede no ser exactamente
    `value`: el campo es entero y su exponente se comparte con el resto de la
    fila. El parte incluye los dos, que es lo que hay que ensenar.
    """
    if channel not in CANALES.values():
        raise AnimError("canal %r no valido (%s)"
                        % (channel, ", ".join(sorted(CANALES.values()))))
    opcode = next(k for k, v in CANALES.items() if v == channel)
    hueso = anim.bone_by_id(bone_id)
    spline = next((s for s in hueso.splines if s.opcode == opcode), None)
    if spline is None:
        raise AnimError("el hueso %d no tiene canal %s" % (bone_id, channel))
    if frame not in spline.timings:
        raise AnimError(
            "el hueso %d, canal %s no tiene clave en el frame %d (claves: %s)"
            % (bone_id, channel, frame, list(spline.timings[:12])))
    k = spline.timings.index(frame)
    indice = spline.first_data_index + k
    bloque = anim.key_blocks[indice]
    fila = bloque.rows[0]
    antes = {"x": fila.vector[0], "y": fila.vector[1], "z": fila.vector[2]}[axis]
    nueva = replace_component(fila, axis, value)
    bloque_nuevo = KeyBlock((nueva, *bloque.rows[1:]))
    anim.key_blocks[indice] = bloque_nuevo
    spline.keys[k] = bloque_nuevo
    despues = {"x": nueva.vector[0], "y": nueva.vector[1],
               "z": nueva.vector[2]}[axis]
    return {
        "bone_id": bone_id,
        "channel": channel,
        "frame": frame,
        "key_index": k,
        "key_block_index": indice,
        "axis": axis,
        "requested": value,
        "before": antes,
        "after": despues,
        "row_before": fila.raw,
        "row_after": nueva.raw,
    }


__all__ = [
    "BIAS_EXP",
    "CAMPO_MAX",
    "CAMPO_MIN",
    "CANALES",
    "HEADER_SIZE",
    "KEYBLOCK_SIZE",
    "MAGIC",
    "MAGIC_BYTES",
    "VERSIONES",
    "AnimError",
    "AnimFormatError",
    "Animation",
    "Bone",
    "Header",
    "KeyBlock",
    "Row",
    "Spline",
    "axis_angle_to_quaternion",
    "build",
    "encode_component",
    "parse",
    "peek",
    "replace_component",
    "roundtrip",
    "set_keyframe_value",
]

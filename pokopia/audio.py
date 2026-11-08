"""Audio para los bancos `.srsa`: WAV PCM, MS ADPCM (codificar y decodificar) y tonos.

Este modulo es el que permite meter un sonido **nuestro** (un seno, una nota
grabada, un WAV cualquiera) en un banco del juego: MS ADPCM tiene
especificacion publica (Microsoft ADPCM, el mismo que decodifican `vgmstream`
y `ffmpeg`) y un cuantizador adaptativo que se implementa en cien lineas.

El otro codec de los bancos, `KA1A` (18.558 de los 18.835 streams con datos
dentro), **no es un ADPCM**: es un codec de transformada (frame de 512
muestras, 21 bandas, FFT con solapamiento) y aqui no hay codificador. El
analisis y el esfuerzo que costaria estan en `docs/AUDIO-PROPIO.md`.

Convenios, medidos contra los bancos reales y contra `vgmstream` r2168
(`src/coding/msadpcm_decoder.c` y `src/coding/libs/ka1a_dec.*`, licencia
vgmstream):

- MS ADPCM se guarda en **bloques** de `bloque` bytes. En este dump todos los
  streams MS ADPCM usan **262 B**, que dan 512 muestras por bloque
  (`(262 - 7) * 2 + 2`), pero el tamano no es fijo: se lee de la cabecera del
  banco y aqui se respeta.
- Cabecera de bloque (7 B): indice de coeficiente (u8), delta (s16),
  `samp1` (s16, la **segunda** muestra), `samp2` (s16, la **primera**).
- Detras van las muestras en nibbles 4+4 con el **nibble alto primero**, y cada
  muestra se reconstruye con `((h1*c1 + h2*c2) >> 8) + codigo*delta`, con el
  factor de desviacion estandar de la tabla de Microsoft (los mismos valores
  fijos que usa `vgmstream`, porque los coeficientes del contenedor son
  siempre los de fabrica).
"""

from __future__ import annotations

import math
import struct
import wave

__all__ = [
    "AudioError",
    "MSADPCM_COEFS",
    "MSADPCM_STEPS",
    "msadpcm_block_samples",
    "msadpcm_decode",
    "msadpcm_encode",
    "msadpcm_snr_db",
    "read_wav",
    "tone_amplitude",
    "write_wav",
]


class AudioError(Exception):
    """El audio de entrada no se puede leer o no cabe en el destino."""

    exit_code = 1


#: Coeficientes de fabrica de MS ADPCM (`aCoeff`, 7 pares, punto fijo 8.8).
MSADPCM_COEFS: tuple[tuple[int, int], ...] = (
    (256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232),
)

#: Tabla de adaptacion del delta (`AdaptionTable`, cuenta 8.8).
MSADPCM_STEPS: tuple[int, ...] = (
    230, 230, 230, 230, 307, 409, 512, 614,
    768, 614, 512, 409, 307, 230, 230, 230,
)

#: Cabecera de bloque de MS ADPCM: 1 B de coeficiente + 3 s16.
BLOCK_HEADER = 7

#: Delta minimo del algoritmo (16, como en la especificacion y en vgmstream).
DELTA_MINIMO = 16


def _clamp16(value: int) -> int:
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return value


def msadpcm_block_samples(block_size: int) -> int:
    """Muestras que caben en un bloque de `block_size` bytes (2 por byte + 2)."""
    return (block_size - BLOCK_HEADER) * 2 + 2


# ---------------------------------------------------------------------------
# Decodificador (el inverso exacto de lo que lee vgmstream)
# ---------------------------------------------------------------------------

def msadpcm_decode(payload: bytes, block_size: int,
                   num_samples: int | None = None) -> list[int]:
    """Muestras PCM de un flujo MS ADPCM crudo, tal cual lo decodifica vgmstream.

    `block_size` es el tamano de bloque declarado en la cabecera del banco (en
    este dump, 262 B). Sin `num_samples` devuelve todos los bloques enteros.
    """
    if block_size <= BLOCK_HEADER:
        raise AudioError("bloque MS ADPCM de %d B: minimo %d"
                         % (block_size, BLOCK_HEADER + 1))
    if len(payload) % block_size:
        raise AudioError("flujo de %d B no es multiplo del bloque de %d B"
                         % (len(payload), block_size))
    por_bloque = msadpcm_block_samples(block_size)
    salida: list[int] = []
    for inicio in range(0, len(payload), block_size):
        bloque = payload[inicio:inicio + block_size]
        indice = bloque[0]
        if indice >= len(MSADPCM_COEFS):
            indice = 0
        coef1, coef2 = MSADPCM_COEFS[indice]
        delta, samp1, samp2 = struct.unpack_from("<hhh", bloque, 1)
        salida.append(samp2)
        salida.append(samp1)
        hist1, hist2 = samp1, samp2
        for byte in bloque[BLOCK_HEADER:]:
            for nibble in ((byte >> 4) & 0x0F, byte & 0x0F):
                codigo = nibble - 16 if nibble >= 8 else nibble
                predicho = (hist1 * coef1 + hist2 * coef2) >> 8
                muestra = _clamp16(predicho + codigo * delta)
                hist2, hist1 = hist1, muestra
                delta = (MSADPCM_STEPS[codigo & 0x0F] * delta) >> 8
                if delta < DELTA_MINIMO:
                    delta = DELTA_MINIMO
                salida.append(muestra)
    if len(salida) % por_bloque:
        raise AudioError("decodificados %d muestras, que no es multiplo de %d"
                         % (len(salida), por_bloque))
    return salida if num_samples is None else salida[:num_samples]


# ---------------------------------------------------------------------------
# Codificador
# ---------------------------------------------------------------------------

def _cuantiza(diferencia: int, delta: int) -> int:
    """Codigo de 4 bits mas cercano, redondeando medio fuera del cero."""
    if not delta:
        return 0
    x = diferencia / delta
    codigo = math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)
    if codigo > 7:
        return 7
    if codigo < -8:
        return -8
    return int(codigo)


def _delta_inicial(trozo: list[int]) -> int:
    """Delta de arranque del bloque: media de las primeras diferencias."""
    limite = min(32, len(trozo) - 1)
    if limite <= 0:
        return DELTA_MINIMO
    suma = 0
    for i in range(1, limite + 1):
        suma += abs(trozo[i] - trozo[i - 1])
    return max(DELTA_MINIMO, suma // limite)


def _recorre(trozo: list[int], coef: int, delta: int) -> tuple[int, list[int]]:
    """Cuantiza el bloque entero con un coeficiente y devuelve (error, codigos)."""
    coef1, coef2 = MSADPCM_COEFS[coef]
    hist1, hist2 = trozo[1], trozo[0]
    error = 0
    codigos: list[int] = []
    for objetivo in trozo[2:]:
        predicho = (hist1 * coef1 + hist2 * coef2) >> 8
        codigo = _cuantiza(objetivo - predicho, delta)
        muestra = _clamp16(predicho + codigo * delta)
        diferencia = objetivo - muestra
        error += diferencia * diferencia
        hist2, hist1 = hist1, muestra
        delta = (MSADPCM_STEPS[codigo & 0x0F] * delta) >> 8
        if delta < DELTA_MINIMO:
            delta = DELTA_MINIMO
        codigos.append(codigo)
    return error, codigos


def msadpcm_encode(samples: list[int], block_size: int) -> bytes:
    """Codifica muestras PCM a MS ADPCM con bloques de `block_size` bytes.

    Elige, por bloque, el coeficiente de los siete de fabrica que menos error
    cuadratico deja (el mismo criterio que el codificador de `ffmpeg`), y
    reajusta el estado de prediccion al principio de cada bloque con las dos
    primeras muestras reales, que es lo que el decodificador vuelve a leer de
    la cabecera del bloque.

    El ultimo bloque se rellena con ceros hasta completar el tamano del bloque;
    quien llama decide cuantas muestras son de verdad (`num_samples`), que es
    lo que declara la cabecera del banco.
    """
    if block_size <= BLOCK_HEADER:
        raise AudioError("bloque MS ADPCM de %d B: minimo %d"
                         % (block_size, BLOCK_HEADER + 1))
    por_bloque = msadpcm_block_samples(block_size)
    if por_bloque < 2:
        raise AudioError("bloque de %d B: no caben dos muestras" % block_size)
    if not samples:
        raise AudioError("no hay muestras que codificar")
    for muestra in samples:
        if not -32768 <= muestra <= 32767:
            raise AudioError("muestra fuera de rango PCM16: %d" % muestra)

    salida = bytearray()
    for inicio in range(0, len(samples), por_bloque):
        trozo = list(samples[inicio:inicio + por_bloque])
        if len(trozo) < 2:
            trozo.append(trozo[-1])
        if len(trozo) < por_bloque:
            trozo += [0] * (por_bloque - len(trozo))

        delta0 = _delta_inicial(trozo)
        mejor_coef, mejor_error, mejores_codigos = 0, None, []
        for coef in range(len(MSADPCM_COEFS)):
            error, codigos = _recorre(trozo, coef, delta0)
            if mejor_error is None or error < mejor_error:
                mejor_coef, mejor_error, mejores_codigos = coef, error, codigos

        bloque = bytearray(block_size)
        bloque[0] = mejor_coef
        struct.pack_into("<hhh", bloque, 1, delta0, trozo[1], trozo[0])
        for i, codigo in enumerate(mejores_codigos):
            nibble = codigo & 0x0F
            pos = BLOCK_HEADER + i // 2
            if i % 2 == 0:
                bloque[pos] = nibble << 4
            else:
                bloque[pos] |= nibble
        salida += bloque
    return bytes(salida)


def msadpcm_snr_db(original: list[int], decodificado: list[int]) -> float:
    """Relacion senal/ruido (dB) entre la fuente PCM y lo que devuelve el codec."""
    n = min(len(original), len(decodificado))
    if not n:
        raise AudioError("sin muestras que comparar")
    senal = 0
    ruido = 0
    for i in range(n):
        senal += original[i] * original[i]
        diferencia = original[i] - decodificado[i]
        ruido += diferencia * diferencia
    if not ruido:
        return float("inf")
    if not senal:
        return float("-inf")
    return 10.0 * math.log10(senal / ruido)


# ---------------------------------------------------------------------------
# WAV (RIFF PCM 16 bits) y tonos
# ---------------------------------------------------------------------------

def read_wav(path: str) -> tuple[list[int], int, int]:
    """Lee un WAV PCM de 16 bits y devuelve (muestras del canal 0, Hz, canales)."""
    try:
        with wave.open(path, "rb") as w:
            canales = w.getnchannels()
            ancho = w.getsampwidth()
            rate = w.getframerate()
            crudo = w.readframes(w.getnframes())
    except wave.Error as exc:
        raise AudioError("%s no es un WAV que se pueda leer: %s" % (path, exc)) from None
    if ancho != 2:
        raise AudioError("%s: hace falta PCM de 16 bits (tiene %d B por muestra); "
                         "convierte con `ffmpeg -c:a pcm_s16le`" % (path, ancho))
    if canales < 1:
        raise AudioError("%s: sin canales" % path)
    total = len(crudo) // 2
    muestras = list(struct.unpack("<%dh" % total, crudo))
    if canales > 1:
        muestras = muestras[::canales]
    if not muestras:
        raise AudioError("%s: 0 muestras" % path)
    return muestras, rate, canales


def write_wav(path: str, samples: list[int], rate: int, channels: int = 1) -> None:
    """Escribe PCM 16 bits (para las pruebas y para inspeccionar un flujo)."""
    if not 1 <= channels <= 2:
        raise AudioError("canales fuera de rango: %d" % channels)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        if channels == 1:
            w.writeframes(struct.pack("<%dh" % len(samples), *samples))
        else:
            entrelazado = []
            for muestra in samples:
                entrelazado.extend([muestra] * channels)
            w.writeframes(struct.pack("<%dh" % len(entrelazado), *entrelazado))


def tone_amplitude(samples: list[int], rate: int, hz: float) -> float:
    """Amplitud de una frecuencia concreta (Goertzel), sin dependencias.

    Sirve para comprobar que lo que devuelve el banco es **nuestro** tono y no
    otro audio: se compara la energia en 440 Hz con la de sus vecinas.
    """
    n = len(samples)
    if not n or rate <= 0:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * hz / rate)
    s1 = s2 = 0.0
    for muestra in samples:
        s0 = muestra + k * s1 - s2
        s2, s1 = s1, s0
    potencia = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(0.0, potencia)) * 2.0 / n

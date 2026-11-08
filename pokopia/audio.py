"""Audio para los bancos `.srsa`: WAV PCM, MS ADPCM y KA1A (codificar y decodificar).

Este modulo es el que permite meter un sonido **nuestro** (un seno, una nota
grabada, un WAV cualquiera) en un banco del juego. Los bancos usan dos codecs:

- `MS ADPCM` (277 de los 18.835 streams con datos dentro): especificacion
  publica (Microsoft ADPCM, el mismo que decodifican `vgmstream` y `ffmpeg`) y
  un cuantizador adaptativo que se implementa en cien lineas.
- `KA1A` (18.558 streams): codec de **transformada** de Koei Tecmo — ventana de
  solapamiento, MDCT de 512 coeficientes, 21 bandas y codigos logaritmicos de
  8 bits. Aqui estan el decodificador y el **codificador**, invertidos del
  decodificador de `vgmstream` r2168 (`src/coding/libs/ka1a_dec.c`, licencia
  ISC). La especificacion byte a byte esta en `docs/AUDIO-KA1A.md`.

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
- KA1A trabaja por **frames de 512 muestras**: el primero es retardo de
  encoder (solo prepara el solapamiento), y cada frame son 4 B de factor de
  escala + los bytes de subposiciones + los bytes de codigos. El tamano de
  frame lo fija el modo de bitrate (-5..+5).
"""

from __future__ import annotations

import math
import struct
import wave

from .ka1a_tablas import (
    BAND_CODES,
    BAND_STEP_BITS,
    BAND_STEPS,
    BITRATE_INDEX_MODIFIER,
    BITRATE_SUBMODE,
    COS_TABLE,
    FFT_POINTS,
    FRAME_SAMPLES,
    MAX_BANDS,
    MAX_BITRATES,
    OVERLAP_WINDOW,
    SIN_TABLE,
    TWIDDLES_IMAG,
    TWIDDLES_REAL,
)

__all__ = [
    "AudioError",
    "KA1A_FRAME_SAMPLES",
    "KA1A_MODES",
    "MSADPCM_COEFS",
    "MSADPCM_STEPS",
    "ka1a_decode",
    "ka1a_decode_pcm16",
    "ka1a_encode",
    "ka1a_frame_count",
    "ka1a_frame_info",
    "ka1a_frame_size",
    "ka1a_snr_db",
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
# KA1A: codec de transformada (decodificador y codificador)
# ---------------------------------------------------------------------------
#
# Estructura de un frame (todo little-endian), 4 + pasos + codigos bytes:
#
#   +0x00  f32   factor de escala del frame (si es negativo, cambia el reparto
#                de codigos por banda: sub-modo; nosotros siempre escribimos >= 0)
#   +0x04  ...   subposiciones: LSB-primero, 4-7 bits por codigo de las bandas 8..20
#   ...    ...   codigos: 40 de las bandas 0..7 (posiciones implicitas 0..39),
#                13 principales de las bandas 8..20 y el resto detras:
#                  - modos -5..+1: subcodigos de 4 bits, dos por byte, nibble bajo
#                    primero, relativos al principal de su banda (+-100 % de el)
#                  - modos +2..+5: codigos absolutos de 8 bits
#
# Codigo de 8 bits -> coeficiente: `exp((m - 127) * 0.086643398) * escala`, con
# `m` = codigo (0..127, positivo) o `256 - codigo` (128..255, negativo). El
# codigo 0 es el cero exacto.

#: Muestras por frame (constante del formato).
KA1A_FRAME_SAMPLES = FRAME_SAMPLES

#: Paso del codigo logaritmico de 8 bits: `exp(0.086643398)` = 1,0905 (~0,75 dB).
KA1A_LOG_STEP = 0.086643398

#: Paso del subcodigo de 4 bits, 1/7 con el valor exacto que usa vgmstream.
KA1A_SUB_STEP = 0.14285715

#: Modos de bitrate (el s32 de la cabecera extra del stream del banco).
KA1A_MODES = tuple(range(-5, 6))

#: Ventana de analisis/sintesis de 1024 muestras: sube en la primera mitad y
#: baja en la segunda (la misma que aplica el decodificador).
_VENTANA = tuple(OVERLAP_WINDOW) + tuple(reversed(OVERLAP_WINDOW))

_PLEGADOS: dict[int, tuple[tuple[int, int], ...]] = {}
_TWIDDLES_FFT: dict[tuple[int, int], tuple[complex, ...]] = {}


def ka1a_index(mode: int) -> int:
    """Indice de tabla (0..10) del modo de bitrate (-5..+5)."""
    indice = mode + BITRATE_INDEX_MODIFIER
    if not 0 <= indice < MAX_BITRATES:
        raise AudioError("modo de bitrate KA1A fuera de -5..+5: %d" % mode)
    return indice


def _info_indice(indice: int) -> tuple[int, int, int]:
    """(bytes de subposiciones, bytes de codigos, bytes de frame) de un indice."""
    bits_codigos = 8 * sum(BAND_CODES[indice][:8])
    bits_pasos = 0
    if indice <= 5:
        # un codigo absoluto por banda y el resto de 4 bits, relativo a el
        bits_codigos += (MAX_BANDS - 8) * 8
        for banda in range(8, MAX_BANDS):
            n = BAND_CODES[indice][banda]
            bits_pasos += BAND_STEP_BITS[banda] * n
            bits_codigos += 4 * (n - 1)
    else:
        # todos los codigos absolutos de 8 bits
        for banda in range(8, MAX_BANDS):
            n = BAND_CODES[indice][banda]
            bits_pasos += BAND_STEP_BITS[banda] * n
            bits_codigos += 8 * n
    pasos = (bits_pasos + 7) >> 3
    codigos = (bits_codigos + 7) >> 3
    return pasos, codigos, 4 + pasos + codigos


def ka1a_frame_info(mode: int) -> tuple[int, int, int]:
    """(bytes de subposiciones, bytes de codigos, bytes de frame) del modo."""
    return _info_indice(ka1a_index(mode))


def ka1a_frame_size(mode: int) -> int:
    """Bytes que ocupa un frame en el modo dado (la cabecera del banco lo fija)."""
    return ka1a_frame_info(mode)[2]


def ka1a_frame_count(num_samples: int) -> int:
    """Frames que ocupan `num_samples` muestras, con el de retardo incluido."""
    if num_samples < 1:
        raise AudioError("sin muestras: %d" % num_samples)
    return (num_samples + KA1A_FRAME_SAMPLES - 1) // KA1A_FRAME_SAMPLES + 1


# --- transformada -----------------------------------------------------------

def _twiddles_fft(n: int, signo: int) -> tuple[complex, ...]:
    clave = (n, signo)
    tabla = _TWIDDLES_FFT.get(clave)
    if tabla is None:
        pasos: list[complex] = []
        largo = 2
        while largo <= n:
            angulo = signo * 2.0 * math.pi / largo
            pasos.append(complex(math.cos(angulo), math.sin(angulo)))
            largo <<= 1
        tabla = tuple(pasos)
        _TWIDDLES_FFT[clave] = tabla
    return tabla


def _fft(datos: list, signo: int = 1) -> list:
    """FFT radix-2 iterativa; `signo=+1` da el nucleo del DCT-IV."""
    n = len(datos)
    if n < 2 or n & (n - 1):
        raise AudioError("FFT de %d puntos: no es potencia de 2" % n)
    a = list(datos)
    twiddles = _twiddles_fft(n, signo)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    largo = 2
    nivel = 0
    while largo <= n:
        w_paso = twiddles[nivel]
        nivel += 1
        mitad = largo >> 1
        for inicio in range(0, n, largo):
            w = 1 + 0j
            for k in range(inicio, inicio + mitad):
                u = a[k]
                v = a[k + mitad] * w
                a[k] = u + v
                a[k + mitad] = u - v
                w *= w_paso
        largo <<= 1
    return a


def _dct4(x: list) -> list[float]:
    """DCT-IV de `x` (la matriz es simetrica: sirve para ida y vuelta)."""
    n = len(x)
    a = [0j] * (2 * n)
    paso = math.pi / (2.0 * n)
    for k, valor in enumerate(x):
        angulo = paso * k
        a[k] = complex(valor * math.cos(angulo), valor * math.sin(angulo))
    b = _fft(a, signo=1)
    salida = [0.0] * n
    for m in range(n):
        angulo = math.pi * (m / 2.0 + 0.25) / n
        salida[m] = (b[m] * complex(math.cos(angulo), math.sin(angulo))).real
    return salida


def _plegado(n: int) -> tuple[tuple[int, int], ...]:
    """Para cada una de las 2n muestras: (indice de coeficiente, signo).

    Es el plegado del IMDCT: `y[m] = signo * c[pos]`, con `pos` en [0, n).
    """
    mapa = _PLEGADOS.get(n)
    if mapa is None:
        lista = []
        for m in range(2 * n):
            t = m + n // 2
            signo = 1
            if t >= 2 * n:
                t -= 2 * n
                signo = -signo
            elif t >= n:
                t = 2 * n - 1 - t
                signo = -signo
            lista.append((t, signo))
        mapa = tuple(lista)
        _PLEGADOS[n] = mapa
    return mapa


def _ka1a_imdct(coefs: list) -> list[float]:
    """Sintesis: 512 coeficientes -> 1024 muestras (escala 1/N, la de vgmstream)."""
    if len(coefs) != KA1A_FRAME_SAMPLES:
        raise AudioError("%d coeficientes: se esperaban %d"
                         % (len(coefs), KA1A_FRAME_SAMPLES))
    espectro = _dct4(coefs)
    escala = 1.0 / KA1A_FRAME_SAMPLES
    return [signo * espectro[pos] * escala
            for pos, signo in _plegado(KA1A_FRAME_SAMPLES)]


def _ka1a_analiza(bloque: list) -> list[float]:
    """Analisis: 1024 muestras crudas -> 512 coeficientes (enventanadas y dobladas)."""
    if len(bloque) != 2 * KA1A_FRAME_SAMPLES:
        raise AudioError("%d muestras: se esperaban %d"
                         % (len(bloque), 2 * KA1A_FRAME_SAMPLES))
    n = KA1A_FRAME_SAMPLES
    espectro = [0.0] * n
    for m, (pos, signo) in enumerate(_plegado(n)):
        espectro[pos] += signo * bloque[m] * _VENTANA[m]
    return [2.0 * valor for valor in _dct4(espectro)]


# --- codigos ----------------------------------------------------------------

def _codigo_a_coef(code: int, escalar: float) -> float:
    """Coeficiente que produce un codigo absoluto de 8 bits."""
    if not code:
        return 0.0
    code_f = code - 256 if code >= 128 else code
    if code & 0x80:
        code_f = -code_f
        escalar = -escalar
    return math.exp((code_f - 127.0) * KA1A_LOG_STEP) * escalar


def _subcodigo_a_coef(code: int, principal: float) -> float:
    """Coeficiente relativo al principal de su banda (subcodigo de 4 bits)."""
    return ((code * KA1A_SUB_STEP) - 1.0) * principal


def _coef_a_codigo(valor: float, escalar: float) -> int:
    """Codigo absoluto de 8 bits mas cercano (redondeo en el dominio logaritmico)."""
    if not valor or not escalar:
        return 0
    m = 127 + math.log(abs(valor) / escalar) / KA1A_LOG_STEP
    m = int(math.floor(m + 0.5))
    if valor > 0.0:
        return max(1, min(127, m))
    return 256 - max(1, min(128, m))


class _Lector:
    """Lector de bits LSB-primero, como el de `ka1a_dec.c`."""

    __slots__ = ("datos", "byte", "bit")

    def __init__(self, datos, byte: int):
        self.datos = datos
        self.byte = byte
        self.bit = 0

    def bits(self, n: int) -> int:
        valor = 0
        for j in range(n):
            if (self.datos[self.byte] >> self.bit) & 1:
                valor |= 1 << j
            self.bit += 1
            if self.bit == 8:
                self.bit = 0
                self.byte += 1
        return valor


class _Escritor:
    """Escritor de bits LSB-primero, el inverso exacto de `_Lector`."""

    __slots__ = ("datos", "bit")

    def __init__(self):
        self.datos = bytearray()
        self.bit = 0

    def bits(self, valor: int, n: int) -> None:
        for j in range(n):
            if self.bit == 0:
                self.datos.append(0)
            if (valor >> j) & 1:
                self.datos[-1] |= 1 << self.bit
            self.bit = (self.bit + 1) & 7


# --- decodificador ----------------------------------------------------------

def _ka1a_desempaqueta_frame(datos, offset: int, indice: int) -> list[float]:
    """512 coeficientes de un frame (los que usa la transformada)."""
    escalar = struct.unpack_from("<f", datos, offset)[0]
    pasos, codigos, _ = _info_indice(indice)
    base_pasos = offset + 4
    base_codigos = base_pasos + pasos
    band_codes = list(BAND_CODES[indice])
    if escalar < 0.0:
        # sub-modo: el signo del factor de escala mueve codigos entre bandas
        escalar = -escalar
        mod = BITRATE_SUBMODE[indice]
        for banda in range(8, 12):
            band_codes[banda] += mod
        for banda in range(17, 21):
            band_codes[banda] -= mod

    coefs = [0.0] * KA1A_FRAME_SAMPLES
    pos = 0
    for banda in range(8):
        for _ in range(band_codes[banda]):
            coefs[pos] = _codigo_a_coef(datos[base_codigos + pos], escalar)
            pos += 1

    lector = _Lector(datos, base_pasos)
    sub_pos = pos + (MAX_BANDS - 8)
    nibble_alto = False
    for banda in range(8, MAX_BANDS):
        n_codes = band_codes[banda]
        base = BAND_STEPS[banda]
        nbits = BAND_STEP_BITS[banda]
        sub = lector.bits(nbits)
        coef = _codigo_a_coef(datos[base_codigos + pos], escalar)
        pos += 1
        if base + sub < KA1A_FRAME_SAMPLES:
            coefs[base + sub] = coef
        for _ in range(1, n_codes):
            sub = lector.bits(nbits)
            if indice <= 5:
                code = datos[base_codigos + sub_pos]
                if nibble_alto:
                    sub_pos += 1
                nibble = ((code >> 4) & 0x0F) if nibble_alto else (code & 0x0F)
                nibble_alto = not nibble_alto
                valor = _subcodigo_a_coef(nibble, coef)
            else:
                valor = _codigo_a_coef(datos[base_codigos + sub_pos], escalar)
                sub_pos += 1
            if base + sub < KA1A_FRAME_SAMPLES:
                coefs[base + sub] = valor
    return coefs


def ka1a_decode(payload: bytes, mode: int,
                num_samples: int | None = None) -> list[float]:
    """Muestras en punto flotante (-1..1) de un flujo KA1A crudo.

    Es el decodificador de `vgmstream` sin el redondeo final a PCM16: el primer
    frame no devuelve muestras (es el retardo de encoder) y cada frame siguiente
    da 512, solapadas con la cola del anterior.
    """
    indice = ka1a_index(mode)
    _, _, frame = _info_indice(indice)
    if len(payload) % frame:
        raise AudioError("flujo KA1A de %d B y frames de %d B: no cuadra"
                         % (len(payload), frame))
    frames = len(payload) // frame
    if frames < 2:
        raise AudioError("flujo KA1A de %d frame(s): hacen falta 2 (el primero "
                         "es retardo de encoder)" % frames)
    previo: list[float] | None = None
    salida: list[float] = []
    ultimo = KA1A_FRAME_SAMPLES - 1
    for f in range(frames):
        y = _ka1a_imdct(_ka1a_desempaqueta_frame(payload, f * frame, indice))
        if previo is None:
            previo = [OVERLAP_WINDOW[ultimo - i] * y[KA1A_FRAME_SAMPLES + i]
                      for i in range(KA1A_FRAME_SAMPLES)]
            continue
        for i in range(KA1A_FRAME_SAMPLES):
            salida.append(OVERLAP_WINDOW[i] * y[i] + previo[i])
        previo = [OVERLAP_WINDOW[ultimo - i] * y[KA1A_FRAME_SAMPLES + i]
                  for i in range(KA1A_FRAME_SAMPLES)]
    if num_samples is not None:
        if num_samples > len(salida):
            raise AudioError("%d muestras pedidas y el flujo solo da %d"
                             % (num_samples, len(salida)))
        return salida[:num_samples]
    return salida


def _a_pcm16(valor: float) -> int:
    """Redondeo de vgmstream: trunca hacia cero y satura (no redondea al mas cercano)."""
    entero = int(valor * 32767.0)
    if entero > 32767:
        return 32767
    if entero < -32768:
        return -32768
    return entero


def ka1a_decode_pcm16(payload: bytes, mode: int,
                      num_samples: int | None = None) -> list[int]:
    """Las mismas muestras que escribe `vgmstream` en el WAV (PCM16)."""
    return [_a_pcm16(v) for v in ka1a_decode(payload, mode, num_samples)]


# --- codificador ------------------------------------------------------------

def _ka1a_planifica(coefs: list[float], indice: int
                    ) -> tuple[float, list[tuple[int, int, float, bool]]]:
    """Elige que posiciones se codifican por banda y el factor de escala.

    Devuelve (factor de escala, [(banda, subposicion, valor, es_principal)]).
    Las bandas 0..7 tienen posiciones fijas (5 por banda); en las 8..20 se
    quedan las `n` posiciones de mayor magnitud y la mayor va primera, porque
    es la que se codifica en absoluto y a la que se refieren las demas en los
    modos de subcodigos de 4 bits.
    """
    band_codes = BAND_CODES[indice]
    seleccion: list[tuple[int, int, float, bool]] = []
    usados: set[int] = set(range(40))  # las bandas 0..7 ocupan 0..39 fijas
    for banda in range(8):
        for j in range(band_codes[banda]):
            seleccion.append((banda, j, coefs[5 * banda + j], True))
    for banda in range(8, MAX_BANDS):
        base = BAND_STEPS[banda]
        n = band_codes[banda]
        ranuras = min(1 << BAND_STEP_BITS[banda], KA1A_FRAME_SAMPLES - base)
        # las bandas altas se solapan: no se repite una posicion ya codificada
        candidatos = [(abs(coefs[base + s]), s) for s in range(ranuras)
                      if coefs[base + s] and base + s not in usados]
        candidatos.sort(reverse=True)
        elegidos = sorted(s for _, s in candidatos[:n])
        while len(elegidos) < n:
            libre = 0
            while libre in elegidos or base + libre in usados:
                libre += 1
            elegidos.append(libre)
            elegidos.sort()
        usados.update(base + s for s in elegidos)
        if elegidos:
            mayor = max(elegidos, key=lambda s: abs(coefs[base + s]))
            elegidos.remove(mayor)
            elegidos.insert(0, mayor)
        for k, s in enumerate(elegidos):
            seleccion.append((banda, s, coefs[base + s], k == 0))
    maximo = max((abs(valor) for _, _, valor, _ in seleccion), default=0.0)
    return (maximo if maximo > 0.0 else 0.0), seleccion


def _ka1a_empaqueta_frame(coefs: list[float], indice: int) -> bytes:
    """Un frame completo: factor de escala, subposiciones y codigos."""
    pasos, codigos, _ = _info_indice(indice)
    escalar, seleccion = _ka1a_planifica(coefs, indice)
    buffer_codigos = bytearray(codigos)
    escritor = _Escritor()
    pos_bajo = 0
    pos_principal = 40
    pos_sub = 40 + (MAX_BANDS - 8)
    nibble_alto = False
    principal = 0
    for banda, subpos, valor, es_principal in seleccion:
        if banda >= 8:
            escritor.bits(subpos, BAND_STEP_BITS[banda])
        if banda < 8:
            buffer_codigos[pos_bajo] = _coef_a_codigo(valor, escalar)
            pos_bajo += 1
            continue
        if es_principal:
            principal = _coef_a_codigo(valor, escalar)
            buffer_codigos[pos_principal] = principal
            pos_principal += 1
            continue
        if indice <= 5:
            decodificado = _codigo_a_coef(principal, escalar)
            if not decodificado:
                code = 7
            else:
                code = int(math.floor((valor / decodificado + 1.0) / KA1A_SUB_STEP + 0.5))
                code = max(0, min(14, code))
            if nibble_alto:
                buffer_codigos[pos_sub] |= (code & 0x0F) << 4
                pos_sub += 1
            else:
                buffer_codigos[pos_sub] = code & 0x0F
            nibble_alto = not nibble_alto
        else:
            buffer_codigos[pos_sub] = _coef_a_codigo(valor, escalar)
            pos_sub += 1
    if len(escritor.datos) > pasos:
        raise AudioError("subposiciones: %d B y el frame declara %d"
                         % (len(escritor.datos), pasos))
    buffer_pasos = bytes(escritor.datos) + b"\x00" * (pasos - len(escritor.datos))
    return struct.pack("<f", escalar) + buffer_pasos + bytes(buffer_codigos)


def ka1a_encode(samples: list[int], mode: int) -> bytes:
    """Codifica muestras PCM16 a KA1A en el modo de bitrate dado.

    El tamano del flujo es `ka1a_frame_count(len(samples)) * ka1a_frame_size(mode)`;
    la cabecera del banco tiene que declarar `len(samples)` muestras, no frames.
    El ultimo frame se rellena con ceros.

    Es un codificador con perdida: elige, por banda y frame, las posiciones de
    mayor magnitud, cuantiza el factor de escala comun y cada coeficiente en su
    codigo logaritmico. La calidad medida esta en `docs/AUDIO-KA1A.md`.
    """
    indice = ka1a_index(mode)
    pasos, codigos, frame = _info_indice(indice)
    if not samples:
        raise AudioError("no hay muestras que codificar")
    for muestra in samples:
        if not -32768 <= muestra <= 32767:
            raise AudioError("muestra fuera de rango PCM16: %d" % muestra)
    # el decodificador escribe PCM16 como `int(f * 32767)`: la ida y vuelta usa
    # la misma escala para no atenuar la senal
    x = [muestra / 32767.0 for muestra in samples]
    total = ka1a_frame_count(len(x))
    bloques = 2 * KA1A_FRAME_SAMPLES
    salida = bytearray()
    for f in range(total):
        inicio = (f - 1) * KA1A_FRAME_SAMPLES
        bloque = [0.0] * bloques
        desde = max(0, -inicio)
        hasta = min(bloques, len(x) - inicio)
        for k in range(desde, hasta):
            bloque[k] = x[inicio + k]
        coeficientes = _ka1a_analiza(bloque)
        if not any(coeficientes):
            # frame mudo: escala 0, posiciones 0 y codigos 0. Es el frame mas
            # barato y el decodificador lo entiende (todos los coeficientes 0).
            salida += bytes(frame)
            continue
        salida += _ka1a_empaqueta_frame(coeficientes, indice)
    if len(salida) != total * frame:
        raise AudioError("codificados %d B y el modo declara %d frames de %d B"
                         % (len(salida), total, frame))
    return bytes(salida)


def ka1a_snr_db(original: list[int], decodificado: list[float]) -> float:
    """Relacion senal/ruido (dB) entre el PCM16 de entrada y lo que da el codec.

    `original` va en PCM16 y `decodificado` en la escala de `ka1a_decode`
    (-1..1); si a `decodificado` le llega PCM16 se rechaza en vez de devolver un
    numero sin sentido.
    """
    n = min(len(original), len(decodificado))
    if not n:
        raise AudioError("sin muestras que comparar")
    if any(abs(valor) > 1.5 for valor in decodificado):
        raise AudioError("ka1a_snr_db espera muestras en -1..1 (ka1a_decode) "
                         "y esto parece PCM16: %r" % (decodificado[:4],))
    senal = 0.0
    ruido = 0.0
    for i in range(n):
        valor = original[i] / 32767.0
        senal += valor * valor
        diferencia = valor - decodificado[i]
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

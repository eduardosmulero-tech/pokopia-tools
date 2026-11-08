"""Codec KA1A: codificador propio y verificacion contra el formato.

Nada del juego: las muestras se generan aqui (senos) y los bancos se construyen
byte a byte con la misma geometria que el dump. Lo que cubren estas pruebas:

* la geometria del frame de los 11 modos de bitrate (**96..258 B**), con el
  reparto medido en el dump: modo -2 = 4 B + 42 B de subposiciones + 79 B de
  codigos = 125 B;
* la transformada es exactamente invertible: analisis -> sintesis -> solape
  reconstruye la senal con mas de 100 dB de SNR (sin cuantizar);
* el codificador respeta el tamano de frame del modo, la ida y vuelta conserva
  el tono y declara `ceil(muestras/512) + 1` frames (el primero es el retardo
  de encoder);
* el lector y el escritor de bits son inversos exactos, y los codigos
  logaritmicos de 8 bits cubren el rango con el 4,35 % de error teorico;
* `set_stream_audio` escribe el modo de bitrate en la cabecera extra, describe
  **nuestro** audio y no toca ni el codec ni los demas streams;
* `pkp snd import` funciona en KA1A igual que en MS ADPCM, con `.orig` y
  reversion exacta;
* si hay `VGMSTREAM_CLI`, el juez externo abre el banco que escribimos y su PCM
  coincide con el nuestro (tolerancia 1 LSB: el suma en float32).

La comparacion muestra a muestra contra `vgmstream` sobre los bancos reales va
en `tools/snd/verifica_audio_propio.py`, que necesita el dump.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import wave

import pytest

from pokopia import audio, paths, snd
from pokopia.cli import main
from tests.test_snd import (AUDIO_1, banco_sintetico, chunk_config, chunk_sonido,
                            escribir)

#: Bytes de frame por modo, medidos en el dump y en `ka1a_dec.c`.
TAMANOS = {-5: 96, -4: 104, -3: 115, -2: 125, -1: 140,
           0: 155, 1: 173, 2: 194, 3: 215, 4: 237, 5: 258}


def seno(hz: float = 440.0, muestras: int = 4096, rate: int = 40000,
         amplitud: float = 0.5) -> list[int]:
    return [int(round(32767 * amplitud * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(muestras)]


def banco_con_ka1a(modo: int = -2, muestras: int = 4096, rate: int = 40000) -> bytes:
    """Banco de tres: config, un KA1A con nuestro audio y un KA1A ajeno."""
    flujo = audio.ka1a_encode(seno(440.0, muestras, rate), modo)
    return banco_sintetico([
        chunk_config(),
        chunk_sonido(1, flujo, codec="ka1a", rate=rate, muestras=muestras,
                     modo=modo, nombre="SE_UNO"),
        chunk_sonido(2, AUDIO_1, codec="ka1a", rate=48000, muestras=2000,
                     modo=-1, nombre="SE_DOS"),
    ])


def lee_wav(path: str) -> list[int]:
    with wave.open(path, "rb") as w:
        canales = w.getnchannels()
        datos = w.readframes(w.getnframes())
    muestras = list(struct.unpack("<%dh" % (len(datos) // 2), datos))
    return muestras[::canales]


def ida_y_vuelta_sin_cuantizar(muestras: list[int]) -> list[float]:
    """Analiza y sintetiza con los flotantes intactos: la transformada, a secas."""
    x = [m / 32767.0 for m in muestras]
    total = audio.ka1a_frame_count(len(x))
    n = audio.KA1A_FRAME_SAMPLES
    ventana = audio.OVERLAP_WINDOW
    previo = None
    salida: list[float] = []
    for f in range(total):
        inicio = (f - 1) * n
        bloque = [0.0] * (2 * n)
        for k in range(2 * n):
            t = inicio + k
            if 0 <= t < len(x):
                bloque[k] = x[t]
        y = audio._ka1a_imdct(audio._ka1a_analiza(bloque))
        if previo is None:
            previo = [ventana[n - 1 - i] * y[n + i] for i in range(n)]
            continue
        salida.extend(ventana[i] * y[i] + previo[i] for i in range(n))
        previo = [ventana[n - 1 - i] * y[n + i] for i in range(n)]
    return salida


# ---------------------------------------------------------------------------
# Geometria del formato
# ---------------------------------------------------------------------------

def test_tamano_de_frame_de_los_once_modos():
    for modo, esperado in TAMANOS.items():
        assert audio.ka1a_frame_size(modo) == esperado


def test_el_reparto_del_frame_del_dump_cuadra():
    # el modo mas usado (12.311 streams): 4 + 42 subposiciones + 79 codigos
    pasos, codigos, frame = audio.ka1a_frame_info(-2)
    assert (pasos, codigos, frame) == (42, 79, 125)
    # y el segundo (4.507 streams): 4 + 76 + 157
    assert audio.ka1a_frame_info(4) == (76, 157, 237)


def test_los_frames_llevan_el_de_retardo():
    assert audio.ka1a_frame_count(1) == 2
    assert audio.ka1a_frame_count(512) == 2
    assert audio.ka1a_frame_count(513) == 3
    assert audio.ka1a_frame_count(48000) == 95
    with pytest.raises(audio.AudioError):
        audio.ka1a_frame_count(0)


def test_modo_fuera_de_rango_se_rechaza():
    for modo in (-6, 6, 100):
        with pytest.raises(audio.AudioError):
            audio.ka1a_frame_size(modo)


# ---------------------------------------------------------------------------
# Transformada
# ---------------------------------------------------------------------------

def test_la_transformada_es_exactamente_invertible():
    fuente = seno(1000.0, 4096, 40000, 0.4)
    # una segunda componente para que no sea un tono puro
    fuente = [f + int(3000 * math.sin(2 * math.pi * 2500.0 * i / 40000))
              for i, f in enumerate(fuente)]
    vuelta = ida_y_vuelta_sin_cuantizar(fuente)
    n = min(len(vuelta), len(fuente))
    original = [m / 32767.0 for m in fuente[:n]]
    error = max(abs(vuelta[i] - original[i]) for i in range(n))
    assert error < 1e-5, "la transformada no reconstruye: error %.3e" % error


def test_lector_y_escritor_de_bits_son_inversos():
    valores = [(7, 3), (0, 4), (127, 7), (5, 5), (1, 4), (63, 6), (14, 4), (0, 7)]
    escritor = audio._Escritor()
    for valor, bits in valores:
        escritor.bits(valor, bits)
    lector = audio._Lector(bytes(escritor.datos) + b"\x00" * 8, 0)
    for valor, bits in valores:
        assert lector.bits(bits) == valor


def test_los_codigos_logaritmicos_cubren_el_rango():
    for valor in (1.0, 0.5, 0.1, -0.1, -0.5, -1.0, 1e-4, -1e-4):
        code = audio._coef_a_codigo(valor, 1.0)
        vuelta = audio._codigo_a_coef(code, 1.0)
        assert abs(vuelta - valor) <= abs(valor) * 0.045, (valor, code, vuelta)
    assert audio._codigo_a_coef(0, 1.0) == 0.0
    assert audio._coef_a_codigo(0.0, 1.0) == 0
    # el cero de la escala no puede codificar nada: todo queda a cero
    assert audio._coef_a_codigo(0.5, 0.0) == 0


# ---------------------------------------------------------------------------
# Codificador y decodificador
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("modo", sorted(TAMANOS))
def test_ida_y_vuelta_conserva_el_tono(modo):
    fuente = seno(440.0, 8000, 40000, 0.5)
    flujo = audio.ka1a_encode(fuente, modo)
    assert len(flujo) == audio.ka1a_frame_count(len(fuente)) * audio.ka1a_frame_size(modo)
    vuelta = audio.ka1a_decode(flujo, modo, len(fuente))
    assert len(vuelta) == len(fuente)
    assert audio.ka1a_snr_db(fuente, vuelta) > 30.0
    pcm = audio.ka1a_decode_pcm16(flujo, modo, len(fuente))
    assert audio.tone_amplitude(pcm, 40000, 440.0) > 15000


def test_la_amplitud_se_conserva():
    fuente = seno(440.0, 4096, 40000, 0.5)
    pcm = audio.ka1a_decode_pcm16(audio.ka1a_encode(fuente, -2), -2, len(fuente))
    pico_entrada = max(abs(v) for v in fuente)
    pico_salida = max(abs(v) for v in pcm[512:-512])
    assert abs(pico_salida - pico_entrada) < pico_entrada * 0.05


def test_un_tono_agudo_pierde_mas_y_se_declara():
    # con 3 codigos por banda (modo -2) un tono de 3 kHz no se reproduce igual
    fuente = seno(3000.0, 8000, 40000, 0.5)
    snr = audio.ka1a_snr_db(fuente, audio.ka1a_decode(
        audio.ka1a_encode(fuente, -2), -2, len(fuente)))
    assert 18.0 < snr < 35.0
    snr_alto = audio.ka1a_snr_db(fuente, audio.ka1a_decode(
        audio.ka1a_encode(fuente, 4), 4, len(fuente)))
    assert snr_alto > snr + 5.0


def test_el_silencio_se_codifica_en_cero():
    flujo = audio.ka1a_encode([0] * 1024, -2)
    assert len(flujo) == 3 * audio.ka1a_frame_size(-2)
    assert set(flujo) == {0}
    assert audio.ka1a_decode(flujo, -2, 1024) == [0.0] * 1024


def test_el_codificador_rechaza_lo_que_no_puede():
    with pytest.raises(audio.AudioError):
        audio.ka1a_encode([], -2)
    with pytest.raises(audio.AudioError):
        audio.ka1a_encode([40000], -2)
    with pytest.raises(audio.AudioError):
        audio.ka1a_encode([1, 2, 3], 6)


def test_el_decodificador_rechaza_flujos_incoherentes():
    flujo = audio.ka1a_encode(seno(muestras=1024), -2)
    frame = audio.ka1a_frame_size(-2)
    with pytest.raises(audio.AudioError):
        audio.ka1a_decode(flujo[:-1], -2)
    with pytest.raises(audio.AudioError):
        audio.ka1a_decode(flujo[:frame], -2)          # un solo frame: es el retardo
    with pytest.raises(audio.AudioError):
        audio.ka1a_decode(flujo, 0)                   # modo equivocado
    with pytest.raises(audio.AudioError):
        audio.ka1a_decode(flujo, -2, 10 ** 6)


# ---------------------------------------------------------------------------
# El banco
# ---------------------------------------------------------------------------

def test_set_stream_audio_escribe_el_modo_y_no_toca_lo_demas():
    datos = banco_con_ka1a()
    fuente = seno(1000.0, 3000, 48000)
    flujo = audio.ka1a_encode(fuente, 0)
    nuevo = snd.StreamAudio(codec="ka1a", sample_rate=48000,
                            num_samples=len(fuente), payload=flujo, bitrate_mode=0)
    modificado = snd.set_stream_audio(datos, 1, nuevo)
    leido = snd.parse(modificado)
    tocado = leido.stream(1)

    assert len(leido.streams) == 2
    assert tocado.codec == "ka1a"
    assert tocado.sample_rate == 48000
    assert tocado.num_samples == 3000
    assert snd.ka1a_bitrate_mode(modificado, tocado) == 0
    assert snd.payload(modificado, tocado) == flujo
    assert snd.payload(modificado, leido.stream(2)) == snd.payload(
        datos, snd.parse(datos).stream(2))
    assert leido.size == len(modificado)
    assert leido.declared_size == len(modificado)
    assert leido.ktsr_size == len(modificado) - snd.ASRS_HEADER_SIZE


def test_set_stream_audio_es_idempotente_en_ka1a():
    datos = banco_con_ka1a()
    flujo = audio.ka1a_encode(seno(440.0, 1500), -2)
    nuevo = snd.StreamAudio(codec="ka1a", sample_rate=40000, num_samples=1500,
                            payload=flujo, bitrate_mode=-2)
    una = snd.set_stream_audio(datos, 1, nuevo)
    assert snd.set_stream_audio(una, 1, nuevo) == una


def test_set_stream_audio_rechaza_flujo_que_no_cuadra_con_el_modo():
    datos = banco_con_ka1a()
    flujo = audio.ka1a_encode(seno(muestras=1000), -2)
    with pytest.raises(snd.SndStreamError):
        # declara 5000 muestras pero el flujo trae 1000
        snd.set_stream_audio(datos, 1, snd.StreamAudio(
            codec="ka1a", sample_rate=40000, num_samples=5000, payload=flujo,
            bitrate_mode=-2))
    with pytest.raises(snd.SndStreamError):
        # sin modo de bitrate no se puede describir el frame
        snd.set_stream_audio(datos, 1, snd.StreamAudio(
            codec="ka1a", sample_rate=40000, num_samples=1000, payload=flujo))


def test_ka1a_bitrate_mode_solo_en_ka1a():
    datos = banco_con_ka1a()
    banco = snd.parse(datos)
    assert snd.ka1a_bitrate_mode(datos, banco.stream(1)) == -2
    ms = banco_sintetico([chunk_config(),
                          chunk_sonido(1, b"\x00" * 262, codec="msadpcm",
                                       muestras=512, bloque=262)])
    with pytest.raises(snd.SndStreamError):
        snd.ka1a_bitrate_mode(ms, snd.parse(ms).stream(1))


# ---------------------------------------------------------------------------
# El comando: pkp snd import
# ---------------------------------------------------------------------------

def test_cli_import_en_ka1a(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_ka1a())
    wav = str(tmp_path / "tono.wav")
    fuente = seno(440.0, 2000, 40000)
    audio.write_wav(wav, fuente, 40000)
    antes = paths.sha256_file(ruta)

    assert main(["snd", "import", ruta, "--stream", "1", "--wav", wav,
                 "--in-place"]) == 0
    salida = capsys.readouterr().out
    assert "ka1a" in salida.lower()
    assert "SNR" in salida
    assert paths.sha256_file(ruta + ".orig") == antes
    assert paths.sha256_file(ruta) != antes

    with open(ruta, "rb") as fh:
        modificado = fh.read()
    leido = snd.parse(modificado)
    assert leido.stream(1).num_samples == 2000
    assert leido.stream(1).sample_rate == 40000
    assert snd.ka1a_bitrate_mode(modificado, leido.stream(1)) == -2
    vuelta = audio.ka1a_decode_pcm16(snd.payload(modificado, leido.stream(1)), -2, 2000)
    assert audio.tone_amplitude(vuelta, 40000, 440.0) > 15000

    # revertir con el .orig devuelve el sha256 de partida
    shutil.copyfile(ruta + ".orig", ruta)
    assert paths.sha256_file(ruta) == antes


def test_cli_import_en_ka1a_en_json(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_ka1a())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(660.0, 1024), 40000)
    salida = str(tmp_path / "mod.srsa")
    assert main(["snd", "import", ruta, "--stream", "1", "--wav", wav,
                 "-o", salida, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["streams_before"] == doc["streams_after"] == 2
    assert doc["audio"]["codec"] == "ka1a"
    assert doc["audio"]["bitrate_mode"] == -2
    assert doc["audio"]["num_samples"] == 1024
    assert "ka1a" in doc["encoder"]
    assert doc["snr_db"] > 30
    assert doc["sha256_before"] != doc["sha256_after"]


# ---------------------------------------------------------------------------
# Juez externo (opcional: solo si hay vgmstream)
# ---------------------------------------------------------------------------

VGMSTREAM_CLI = os.environ.get("VGMSTREAM_CLI", "")


@pytest.mark.skipif(not VGMSTREAM_CLI or not os.path.exists(VGMSTREAM_CLI),
                    reason="sin VGMSTREAM_CLI: no hay juez externo")
def test_vgmstream_abre_el_banco_que_escribimos(tmp_path):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_ka1a(modo=0))
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(1000.0, 2000, 48000), 48000)
    assert main(["snd", "import", ruta, "--stream", "1", "--wav", wav,
                 "--in-place"]) == 0

    decodificado = str(tmp_path / "dec.wav")
    proceso = subprocess.run([VGMSTREAM_CLI, "-s", "1", "-o", decodificado, ruta],
                             capture_output=True)
    assert proceso.returncode == 0, proceso.stderr.decode("cp1252", "replace")
    referencia = lee_wav(decodificado)

    with open(ruta, "rb") as fh:
        datos = fh.read()
    stream = snd.parse(datos).stream(1)
    nuestro = audio.ka1a_decode_pcm16(snd.payload(datos, stream), 0,
                                      stream.num_samples)
    assert len(referencia) == len(nuestro) == 2000
    diferencias = [abs(referencia[i] - nuestro[i]) for i in range(len(nuestro))]
    assert max(diferencias) <= 1, "vgmstream y nosotros no coinciden"


@pytest.mark.skipif(not VGMSTREAM_CLI or not os.path.exists(VGMSTREAM_CLI),
                    reason="sin VGMSTREAM_CLI: no hay juez externo")
def test_vgmstream_decodifica_el_frame_mudo(tmp_path):
    # el frame mudo es todo ceros; si vgmstream lo rechazara, no serviria
    ruta = escribir(tmp_path, "banco.srsa", banco_con_ka1a(modo=-2))
    wav = str(tmp_path / "silencio.wav")
    audio.write_wav(wav, [0] * 1500, 40000)
    assert main(["snd", "import", ruta, "--stream", "1", "--wav", wav,
                 "--in-place"]) == 0
    decodificado = str(tmp_path / "dec.wav")
    proceso = subprocess.run([VGMSTREAM_CLI, "-s", "1", "-o", decodificado, ruta],
                             capture_output=True)
    assert proceso.returncode == 0, proceso.stderr.decode("cp1252", "replace")
    referencia = lee_wav(decodificado)
    assert len(referencia) == 1500
    assert set(referencia) == {0}

"""Audio propio en los bancos `.srsa`: codec MS ADPCM y `pkp snd import`.

Nada del juego: las muestras se generan aqui (senos) y los bancos se construyen
byte a byte con la misma geometria que el dump. Lo que cubren estas pruebas:

* el codificador MS ADPCM respeta el bloque del destino y la ida y vuelta deja
  el tono intacto (SNR alto, amplitud y longitud conservadas);
* el decodificador es el inverso exacto del codificador (misma regla que
  vgmstream: prediccion con `>> 8`);
* `set_stream_audio` describe **nuestro** audio en la cabecera (frecuencia,
  muestras, bucle y el par de MS ADPCM) y no toca ni el codec ni los demas
  streams;
* se rechaza lo que no se puede hacer sin encoder: KA1A, cambio de codec,
  muestras que no caben, WAV estereo o de 8 bits;
* `pkp snd import` deja `<banco>.orig`, es idempotente en lo que respeta y no
  escribe nunca dentro del romfs.

El contraste contra `vgmstream` (que es el juez del fichero) necesita el dump y
herramienta externa, y va en `tools/snd/verifica_audio_propio.py`, no aqui.
"""

from __future__ import annotations

import json
import math
import os
import struct

import pytest

from pokopia import audio, paths, snd
from pokopia.cli import main
from tests.test_snd import (AUDIO_1, banco_sintetico, chunk_config, chunk_sonido,
                            escribir)


def seno(hz: float = 440.0, muestras: int = 4000, rate: int = 40000,
         amplitud: float = 0.5) -> list[int]:
    return [int(round(32767 * amplitud * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(muestras)]


def flujo_msadpcm(muestras: int = 4000, rate: int = 40000, hz: float = 440.0,
                  bloque: int = 262) -> tuple[list[int], bytes]:
    fuente = seno(hz, muestras, rate)
    return fuente, audio.msadpcm_encode(fuente, bloque)


def banco_con_msadpcm() -> bytes:
    """Banco de tres: config, un KA1A y un MS ADPCM con bloque de 262 B."""
    _, flujo = flujo_msadpcm(1024)
    return banco_sintetico([
        chunk_config(),
        chunk_sonido(1, AUDIO_1, muestras=2000, nombre="SE_UNO"),
        chunk_sonido(2, flujo, codec="msadpcm", rate=40000, muestras=1024,
                     nombre="SE_DOS", bloque=262),
    ])


# ---------------------------------------------------------------------------
# Geometria del codec
# ---------------------------------------------------------------------------

def test_muestras_por_bloque():
    assert audio.msadpcm_block_samples(262) == 512
    assert audio.msadpcm_block_samples(256) == 500
    assert audio.msadpcm_block_samples(8) == 4


def test_el_bloque_de_262_es_el_del_dump():
    # 512 muestras = 2 de cabecera + 255 bytes x 2 nibbles; 7 + 255 = 262
    assert audio.msadpcm_block_samples(262) == 2 + (262 - 7) * 2


# ---------------------------------------------------------------------------
# Codificador y decodificador
# ---------------------------------------------------------------------------

def test_ida_y_vuelta_conserva_el_tono():
    fuente, flujo = flujo_msadpcm(40000)
    vuelta = audio.msadpcm_decode(flujo, 262, len(fuente))
    assert len(vuelta) == len(fuente)
    assert audio.msadpcm_snr_db(fuente, vuelta) > 40.0
    original = audio.tone_amplitude(fuente, 40000, 440.0)
    copia = audio.tone_amplitude(vuelta, 40000, 440.0)
    assert copia == pytest.approx(original, rel=0.02)


def test_el_flujo_es_multiplo_del_bloque_y_la_cabecera_cuadra():
    fuente, flujo = flujo_msadpcm(1000)
    assert len(flujo) == 2 * 262                       # 2 bloques para 1000 muestras
    assert len(flujo) % 262 == 0
    for inicio in range(0, len(flujo), 262):
        assert flujo[inicio] < len(audio.MSADPCM_COEFS)
        delta, samp1, samp2 = struct.unpack_from("<hhh", flujo, inicio + 1)
        assert 16 <= delta <= 32767
        assert -32768 <= samp1 <= 32767
        assert -32768 <= samp2 <= 32767
    # las dos primeras muestras del bloque son las del PCM, tal cual
    assert struct.unpack_from("<hhh", flujo, 1)[1:] == (fuente[1], fuente[0])


def test_el_ultimo_bloque_se_rellena_y_num_samples_manda():
    fuente, flujo = flujo_msadpcm(700)
    assert len(flujo) == 2 * 262
    assert len(audio.msadpcm_decode(flujo, 262, 700)) == 700
    assert len(audio.msadpcm_decode(flujo, 262)) == 1024


def test_bloque_de_256_tambien_sirve():
    fuente, flujo = flujo_msadpcm(1000, bloque=256)
    assert len(flujo) % 256 == 0
    vuelta = audio.msadpcm_decode(flujo, 256, 1000)
    assert audio.msadpcm_snr_db(fuente, vuelta) > 30.0


def test_el_codificador_rechaza_lo_que_no_cabe():
    with pytest.raises(audio.AudioError):
        audio.msadpcm_encode([], 262)
    with pytest.raises(audio.AudioError):
        audio.msadpcm_encode([0, 40000], 262)          # fuera de PCM16
    with pytest.raises(audio.AudioError):
        audio.msadpcm_encode([1, 2, 3], 7)             # bloque sin nibbles


def test_el_decodificador_rechaza_flujos_incoherentes():
    with pytest.raises(audio.AudioError):
        audio.msadpcm_decode(b"\x00" * 300, 262)       # no es multiplo
    with pytest.raises(audio.AudioError):
        audio.msadpcm_decode(b"\x00" * 7, 7)           # bloque sin nibbles


def test_snr_de_silencio_no_revienta():
    silencio = [0] * 100
    flujo = audio.msadpcm_encode(silencio, 262)
    vuelta = audio.msadpcm_decode(flujo, 262, 100)
    assert vuelta == silencio
    assert audio.msadpcm_snr_db(silencio, vuelta) == float("inf")


# ---------------------------------------------------------------------------
# WAV y tonos
# ---------------------------------------------------------------------------

def test_wav_ida_y_vuelta(tmp_path):
    fuente = seno(440.0, 1000)
    ruta = str(tmp_path / "tono.wav")
    audio.write_wav(ruta, fuente, 40000)
    leidas, rate, canales = audio.read_wav(ruta)
    assert (rate, canales) == (40000, 1)
    assert leidas == fuente


def test_wav_estereo_se_lee_el_primer_canal(tmp_path):
    ruta = str(tmp_path / "estereo.wav")
    audio.write_wav(ruta, seno(440.0, 100), 44100, channels=2)
    leidas, rate, canales = audio.read_wav(ruta)
    assert canales == 2
    assert leidas == seno(440.0, 100)


def test_wav_de_8_bits_se_rechaza_con_motivo(tmp_path):
    import wave

    ruta = str(tmp_path / "ocho.wav")
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * 16)
    with pytest.raises(audio.AudioError) as excinfo:
        audio.read_wav(ruta)
    assert "16 bits" in str(excinfo.value)


def test_tone_amplitude_distingue_frecuencias():
    muestras = seno(440.0, 4000)
    assert audio.tone_amplitude(muestras, 40000, 440.0) > 16000
    assert audio.tone_amplitude(muestras, 40000, 1000.0) < 100


# ---------------------------------------------------------------------------
# Meter el audio en el banco
# ---------------------------------------------------------------------------

def test_set_stream_audio_cambia_datos_y_cabecera_y_nada_mas():
    datos = banco_con_msadpcm()
    banco = snd.parse(datos)
    fuente, flujo = flujo_msadpcm(2000, rate=32000)
    nuevo = snd.StreamAudio(codec="msadpcm", sample_rate=32000,
                            num_samples=len(fuente), payload=flujo,
                            block_size=262, loop_start=100)
    modificado = snd.set_stream_audio(datos, 2, nuevo)
    leido = snd.parse(modificado)
    tocado = leido.stream(2)

    assert len(leido.streams) == len(banco.streams)
    assert leido.stream(2).codec == "msadpcm"
    assert tocado.sample_rate == 32000
    assert tocado.num_samples == len(fuente)
    assert tocado.loop_start == 100
    assert snd.payload(modificado, tocado) == flujo
    # el KA1A y el chunk de configuracion, byte a byte como estaban
    assert snd.payload(modificado, leido.stream(1)) == snd.payload(datos, banco.stream(1))
    assert snd.msadpcm_block_size(modificado, tocado) == 262
    crudo = struct.unpack_from("<HH", modificado, tocado.header_offset + 0x48)
    assert crudo == (512, 262)
    # los tres tamanos cuadran
    assert leido.size == len(modificado)
    assert leido.declared_size == len(modificado)
    assert leido.ktsr_size == len(modificado) - snd.ASRS_HEADER_SIZE


def test_set_stream_audio_es_idempotente():
    datos = banco_con_msadpcm()
    fuente, flujo = flujo_msadpcm(1500)
    nuevo = snd.StreamAudio(codec="msadpcm", sample_rate=40000,
                            num_samples=len(fuente), payload=flujo, block_size=262)
    una = snd.set_stream_audio(datos, 2, nuevo)
    dos = snd.set_stream_audio(una, 2, nuevo)
    assert una == dos


def test_set_stream_audio_rechaza_ka1a_porque_no_hay_encoder():
    datos = banco_con_msadpcm()
    fuente, flujo = flujo_msadpcm(1000)
    nuevo = snd.StreamAudio(codec="ka1a", sample_rate=40000,
                            num_samples=len(fuente), payload=flujo)
    with pytest.raises(snd.SndStreamError) as excinfo:
        snd.set_stream_audio(datos, 1, nuevo)
    assert "KA1A" in str(excinfo.value) or "ka1a" in str(excinfo.value)


def test_set_stream_audio_rechaza_cambio_de_codec_y_excesos():
    datos = banco_con_msadpcm()
    fuente, flujo = flujo_msadpcm(1000)
    with pytest.raises(snd.SndStreamError):
        snd.set_stream_audio(datos, 2, snd.StreamAudio(
            codec="ka1a", sample_rate=40000, num_samples=100, payload=flujo,
            block_size=262))
    with pytest.raises(snd.SndStreamError):
        snd.set_stream_audio(datos, 2, snd.StreamAudio(
            codec="msadpcm", sample_rate=40000, num_samples=10 ** 6, payload=flujo,
            block_size=262))
    with pytest.raises(snd.SndStreamError):
        snd.set_stream_audio(datos, 2, snd.StreamAudio(
            codec="msadpcm", sample_rate=40000, num_samples=100, payload=flujo[:-3],
            block_size=262))
    with pytest.raises(snd.SndStreamError):
        snd.set_stream_audio(datos, 2, snd.StreamAudio(
            codec="msadpcm", sample_rate=40000, num_samples=100, payload=b"",
            block_size=262))
    with pytest.raises(snd.SndStreamError):
        snd.set_stream_audio(datos, 2, snd.StreamAudio(
            codec="msadpcm", sample_rate=40000, num_samples=100, payload=flujo,
            block_size=0))


# ---------------------------------------------------------------------------
# El comando: pkp snd import
# ---------------------------------------------------------------------------

def test_cli_import_escribe_el_banco_y_deja_original(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    fuente, _ = flujo_msadpcm(2000)
    audio.write_wav(wav, fuente, 40000)
    antes = paths.sha256_file(ruta)

    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav, "--in-place"]) == 0
    salida = capsys.readouterr().out
    assert "SNR" in salida
    assert paths.sha256_file(ruta + ".orig") == antes
    assert paths.sha256_file(ruta) != antes

    leido = snd.parse(open(ruta, "rb").read())
    assert leido.stream(2).num_samples == 2000
    assert leido.stream(2).sample_rate == 40000
    with open(ruta, "rb") as fh:
        modificado = fh.read()
    vuelta = audio.msadpcm_decode(snd.payload(modificado, leido.stream(2)), 262, 2000)
    assert audio.tone_amplitude(vuelta, 40000, 440.0) > 16000

    # revertir con el .orig devuelve el sha256 de partida
    with open(ruta + ".orig", "rb") as origen, open(ruta, "wb") as destino:
        destino.write(origen.read())
    assert paths.sha256_file(ruta) == antes


def test_cli_import_en_json(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(660.0, 1024), 40000)      # distinto del que lleva el banco
    salida = str(tmp_path / "mod.srsa")
    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav,
                 "-o", salida, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["streams_before"] == doc["streams_after"] == 2
    assert doc["audio"]["sample_rate"] == 40000
    assert doc["audio"]["num_samples"] == 1024
    assert doc["audio"]["block_size"] == 262
    assert doc["snr_db"] > 30
    assert doc["sha256_before"] != doc["sha256_after"]


def test_cli_import_exige_in_place_o_salida(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(440.0, 512), 40000)
    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav]) == 2
    assert "--in-place" in capsys.readouterr().err


def test_cli_import_rechaza_ka1a_con_el_motivo(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(440.0, 512), 40000)
    assert main(["snd", "import", ruta, "--stream", "1", "--wav", wav,
                 "--in-place"]) != 0
    assert "KA1A" in capsys.readouterr().err


def test_cli_import_rechaza_wav_estereo(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "estereo.wav")
    audio.write_wav(wav, seno(440.0, 512), 40000, channels=2)
    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav,
                 "--in-place"]) == 2
    assert "mono" in capsys.readouterr().err


def test_cli_import_en_el_romfs_esta_prohibido(tmp_path, monkeypatch, capsys):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    ruta = escribir(romfs, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(440.0, 512), 40000)
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav,
                 "--in-place"]) == 2
    assert "destino protegido" in capsys.readouterr().err


def test_cli_import_no_deja_temporales(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_con_msadpcm())
    wav = str(tmp_path / "tono.wav")
    audio.write_wav(wav, seno(440.0, 512), 40000)
    assert main(["snd", "import", ruta, "--stream", "2", "--wav", wav,
                 "--in-place"]) == 0
    assert not any(n.endswith(".tmp") for n in os.listdir(str(tmp_path)))

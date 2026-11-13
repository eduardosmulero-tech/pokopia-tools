"""Streams externos `.srst` (`TSRS`/`KTSR` + Blowfish): leer, escribir y volver.

Ningun byte del juego: cada `.srst` de estas pruebas se construye aqui con la
geometria medida en el dump (cabecera `IDRK` de 56 B, payload `TSRS`, KTSR de
tipo stream, chunks `0x09D4F415` con sus datos cifrados). Los casos que
importan:

* el analisis saca las pistas con su `sound id`, offsets y cabecera `KA1A`;
* una pista cuya `data_size` no es multiplo de 8 (35 de las 83 del dump) se lee
  y se reescribe igual: el ultimo bloque se completa con el relleno del chunk;
* sustituir audio propio conserva tamano, offsets y las demas pistas;
* intercambiar dos pistas exige el mismo `data_size` y lo dice si no;
* `.orig` + `revert` devuelven el fichero byte a byte;
* el kit no escribe dentro del romfs.
"""

from __future__ import annotations

import math
import os
import struct

import pytest

from pokopia import audio, paths, snd, srst
from pokopia.blowfish import Blowfish
from pokopia.cli import main

CLAVE = bytes.fromhex("b83b9a3ad48a0b")
AUDIO_ID = 0x3CDC3E84


# ---------------------------------------------------------------------------
# Construccion de un `.srst` sintetico
# ---------------------------------------------------------------------------

def tono(muestras: int, hz: float, rate: int = 48000, amplitud: float = 0.4) -> list[int]:
    return [int(round(32767 * amplitud * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(muestras)]


def pista(sound_id: int, muestras: int = 1500, *, canales: int = 2,
          rate: int = 48000, modo: int = -5, bucle: int = 0,
          frecuencias: tuple[float, ...] = (440.0, 660.0)) -> tuple[int, bytes]:
    """(sound id, pista descifrada) con audio de tono propio."""
    frame = audio.ka1a_frame_size(modo)
    flujos = [audio.ka1a_encode(tono(muestras, frecuencias[c], rate), modo)
              for c in range(canales)]
    entrelazado = srst.interleave(flujos, frame)
    region = (muestras - bucle) if bucle >= 0 else 0
    cabecera = srst.ka1a_header(canales, 1, rate, muestras, bucle, region, modo,
                                len(entrelazado))
    return sound_id, cabecera + entrelazado


def build_srst(pistas: list[tuple[int, bytes]], *, clave: bytes = CLAVE,
               audio_id: int = AUDIO_ID, prefijo: bool = True,
               name_hash: int = 0x0B5DB05B) -> bytes:
    """Un `.srst` completo: entrada `IDRK` opcional + payload `TSRS`/`KTSR`."""
    chunks = bytearray()
    for sound_id, plano in pistas:
        cifrado = (len(plano) + 7) // 8 * 8
        tam = (0x20 + len(plano) + 15) // 16 * 16
        cuerpo = bytearray()
        cuerpo += struct.pack(">I", srst.CHUNK_STREAM)
        cuerpo += struct.pack("<I", tam)
        cuerpo += struct.pack("<I", sound_id)
        cuerpo += struct.pack("<I", 0x20)
        cuerpo += struct.pack("<I", len(plano))
        cuerpo += bytes(12)
        cuerpo += Blowfish(clave).cifra_relleno_cero(plano, cifrado)
        cuerpo += bytes(tam - len(cuerpo))
        chunks += cuerpo

    ktsr = bytearray(0x40)
    ktsr[0:4] = b"KTSR"
    struct.pack_into(">I", ktsr, 0x04, srst.KTSR_ID_STREAM)
    struct.pack_into("<H", ktsr, 0x08, 1)
    struct.pack_into("<H", ktsr, 0x0A, 0x05F0)
    ktsr[0x0B] = 5
    struct.pack_into("<I", ktsr, 0x0C, audio_id)
    struct.pack_into("<I", ktsr, 0x18, 0x40 + len(chunks))
    struct.pack_into("<I", ktsr, 0x1C, 0x40 + len(chunks))
    ktsr[0x20] = len(clave)
    ktsr[0x21:0x21 + len(clave)] = clave

    payload = bytearray()
    payload += b"TSRS" + struct.pack("<I", 0)
    payload += struct.pack("<Q", 0x10 + len(ktsr) + len(chunks))
    payload += ktsr + chunks

    if not prefijo:
        return bytes(payload)
    entrada = bytearray(56)
    entrada[0:8] = b"IDRK0000"
    struct.pack_into("<Q", entrada, 8, 56 + len(payload))
    struct.pack_into("<Q", entrada, 16, len(payload))
    struct.pack_into("<Q", entrada, 24, len(payload))
    struct.pack_into("<I", entrada, 36, name_hash)
    struct.pack_into("<I", entrada, 40, srst.TYPE_KTID_SRST)
    return bytes(entrada) + bytes(payload)


@pytest.fixture()
def srst_falso(tmp_path):
    """Un `.srst` con cuatro pistas: una de tamano 4 mod 8 y dos gemelas."""
    pistas = [
        pista(0x11110001, 1500, modo=-5),                 # data_size multiplo de 8
        pista(0x11110002, 1000, modo=5),                  # 3 frames: data_size % 8 == 4
        pista(0x11110003, 2000, modo=-5, canales=1,
              frecuencias=(500.0,)),                      # mono
        pista(0x11110004, 1500, modo=-5,
              frecuencias=(523.25, 783.99)),              # mismo tamano que la 1
    ]
    ruta = tmp_path / "0x0b5db05b.file"
    datos = build_srst(pistas)
    ruta.write_bytes(datos)
    return str(ruta), datos, pistas


# ---------------------------------------------------------------------------
# Analisis
# ---------------------------------------------------------------------------

def test_analiza_cabecera_y_pistas(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    s, leido = srst.read(ruta)
    assert leido == datos
    assert s.size == len(datos)
    assert s.prefix == 56                       # entrada IDRK + 8 B de relleno
    assert s.payload_size == len(datos) - 56
    assert s.audio_id == AUDIO_ID
    assert s.key == CLAVE
    assert s.platform == 5 and s.version == 1
    assert len(s.tracks) == len(pistas)
    for track, (sound_id, plano) in zip(s.tracks, pistas):
        assert track.sound_id == sound_id
        assert track.data_size == len(plano)
        assert track.cipher_size % 8 == 0
        assert track.cipher_size >= track.data_size
        assert track.chunk_size == (0x20 + track.data_size + 15) // 16 * 16
        campos = srst.ka1a_fields(plano[:srst.KA1A_HEADER_SIZE])
        assert track.num_samples == campos["muestras"]
        assert track.bitrate_mode == campos["modo"]


def test_una_pista_con_data_size_4_mod_8_se_lee_entera(srst_falso) -> None:
    """El ultimo bloque de 8 B se completa con el relleno del chunk."""
    ruta, datos, pistas = srst_falso
    s, _ = srst.read(ruta)
    track = s.track(2)
    assert track.data_size % 8 == 4
    assert track.cipher_size == track.data_size + 4
    assert srst.track_plain(datos, 2) == pistas[1][1]


def test_sin_prefijo_idrk_tambien_vale() -> None:
    datos = build_srst([pista(1, 800)], prefijo=False)
    s = srst.parse(datos)
    assert s.prefix == 0
    assert s.payload_size == len(datos)
    assert len(s.tracks) == 1


def test_rechaza_lo_que_no_es_un_srst() -> None:
    with pytest.raises(srst.SrstError):
        srst.parse(b"ASRS" + bytes(100))
    datos = build_srst([pista(1, 800)])
    with pytest.raises(srst.SrstError):
        srst.parse(datos[:40])                   # truncado
    with pytest.raises(srst.SrstError):
        srst.parse(bytes(datos[:-8]))            # entrada que no cuadra con el tamano


def test_el_emparejamiento_con_el_banco_es_por_offset_y_sound_id(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    s = srst.parse(datos)
    for track in s.tracks:
        assert s.by_data_offset(track.data_offset) is track
    assert s.by_data_offset(0xDEAD) is None


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def test_sustituye_audio_propio_y_conserva_lo_demas(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    nuevo = [tono(900, 523.25), tono(900, 783.99)]
    salida = srst.with_audio(datos, 1, nuevo, loop_start=0)

    assert len(salida) == len(datos)
    s = srst.parse(salida)
    track = s.track(1)
    assert track.num_samples == 900
    assert track.loop_start == 0 and track.loop_end == 900
    assert track.sound_id == pistas[0][0]
    # las otras pistas, byte a byte como estaban
    for otra in (2, 3, 4):
        assert srst.track_plain(salida, otra) == pistas[otra - 1][1]
    # y lo escrito es nuestro tono, medido
    decodificado, campos = srst.decode_track(srst.track_plain(salida, 1))
    assert campos["muestras"] == 900
    assert audio.tone_amplitude(decodificado[0], 48000, 523.25) > 10000
    assert audio.tone_amplitude(decodificado[0], 48000, 783.99) < 500
    assert audio.tone_amplitude(decodificado[1], 48000, 783.99) > 10000


def test_no_se_puede_cambiar_de_canales_ni_pasarse_de_tamano(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    s = srst.parse(datos)
    with pytest.raises(srst.SrstError):
        srst.build_track(s.track(1), [tono(500, 440)], 0)          # la pista es estereo
    with pytest.raises(srst.SrstError):
        srst.build_track(s.track(1), [tono(20000, 440), tono(20000, 660)], 0)


def test_sustituye_un_flujo_extraido_tal_cual(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    flujo = srst.track_plain(datos, 1)
    salida = srst.with_track(datos, 1, flujo)
    assert salida == datos                       # reescribir lo mismo no cambia nada


def test_intercambia_dos_pistas_del_mismo_tamano(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    salida = srst.swap_tracks(datos, 1, 4)       # 1 y 4: mismo data_size
    s = srst.parse(salida)
    assert len(salida) == len(datos)
    assert srst.track_plain(salida, 1) == pistas[3][1]
    assert srst.track_plain(salida, 4) == pistas[0][1]


def test_swap_con_tamanos_distintos_se_niega(srst_falso) -> None:
    ruta, datos, pistas = srst_falso
    with pytest.raises(srst.SrstError):
        srst.swap_tracks(datos, 1, 2)


def test_fichero_con_copia_y_reversion(srst_falso) -> None:
    ruta, datos, _ = srst_falso
    antes = paths.sha256_file(ruta)
    modificado = srst.with_audio(datos, 1, [tono(700, 440), tono(700, 660)], 0)
    srst.write_srst(ruta, modificado)
    assert paths.sha256_file(ruta) != antes
    assert paths.sha256_file(ruta + ".orig") == antes
    # idempotente: una segunda escritura no pisa el .orig
    srst.write_srst(ruta, modificado)
    assert paths.sha256_file(ruta + ".orig") == antes
    restaurado, original = srst.revert(ruta)
    assert restaurado == original == antes
    assert paths.sha256_file(ruta) == antes


def test_no_escribe_dentro_del_romfs(srst_falso, monkeypatch, tmp_path) -> None:
    ruta, datos, _ = srst_falso
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    dentro = romfs / "0x0b5db05b.file"
    dentro.write_bytes(datos)
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    with pytest.raises(PermissionError):
        srst.write_srst(str(dentro), datos)
    assert dentro.read_bytes() == datos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_list_con_srst_completa_los_externos(srst_falso, tmp_path) -> None:
    ruta, datos, pistas = srst_falso
    banco = tmp_path / "1e474a88.srsa"
    banco.write_bytes(banco_externo(pistas))
    assert main(["snd", "list", str(banco), "--srst", ruta]) == 0


def test_cli_extract_import_y_revert(srst_falso, tmp_path, capsys) -> None:
    ruta, datos, pistas = srst_falso
    banco = tmp_path / "1e474a88.srsa"
    banco.write_bytes(banco_externo(pistas))
    salida = tmp_path / "flujos"

    assert main(["snd", "extract", str(banco), "--out", str(salida),
                 "--stream", "1", "--srst", ruta]) == 0
    flujo = salida / "1e474a88.001.ka1a"
    assert flujo.exists()
    assert flujo.read_bytes() == srst.track_plain(datos, 1)

    wav = tmp_path / "senal.wav"
    audio.write_wav(str(wav), tono(900, 523.25), 48000, channels=2)
    assert main(["snd", "import", str(banco), "--stream", "1", "--wav", str(wav),
                 "--srst", ruta, "--loop", "0", "--in-place"]) == 0
    salida_texto = capsys.readouterr().out
    assert "ka1a propio" in salida_texto
    assert "reversion" not in salida_texto
    assert srst.parse(open(ruta, "rb").read()).track(1).num_samples == 900

    assert main(["snd", "revert", ruta]) == 0
    assert open(ruta, "rb").read() == datos


def test_cli_import_exige_los_mismos_canales(srst_falso, tmp_path) -> None:
    ruta, datos, pistas = srst_falso
    banco = tmp_path / "1e474a88.srsa"
    banco.write_bytes(banco_externo(pistas))
    wav = tmp_path / "mono.wav"
    audio.write_wav(str(wav), tono(900, 440), 48000, channels=1)
    assert main(["snd", "import", str(banco), "--stream", "1", "--wav", str(wav),
                 "--srst", ruta, "--in-place"]) == 2
    assert open(ruta, "rb").read() == datos


def test_cli_replace_con_srst_y_fichero(srst_falso, tmp_path) -> None:
    ruta, datos, pistas = srst_falso
    banco = tmp_path / "1e474a88.srsa"
    banco.write_bytes(banco_externo(pistas))
    plano = srst.build_track(srst.parse(datos).track(2),
                             [tono(600, 300), tono(600, 900)], 0)
    flujo = tmp_path / "flujo.ka1a"
    flujo.write_bytes(plano)
    assert main(["snd", "replace", str(banco), "--srst", ruta, "--stream", "2",
                 "--file", str(flujo), "--in-place"]) == 0
    s = srst.parse(open(ruta, "rb").read())
    assert s.track(2).num_samples == 600


def test_cli_replace_sin_in_place_se_niega(srst_falso, tmp_path) -> None:
    ruta, datos, pistas = srst_falso
    banco = tmp_path / "1e474a88.srsa"
    banco.write_bytes(banco_externo(pistas))
    assert main(["snd", "replace", str(banco), "--srst", ruta, "--swap", "1", "3"]) == 2
    assert open(ruta, "rb").read() == datos


# ---------------------------------------------------------------------------
# Banco sintetico con streams externos (para la CLI)
# ---------------------------------------------------------------------------

def chunk_externo(sound_id: int, data_offset: int, data_size: int, *,
                  canales: int = 2, rate: int = 48000, muestras: int = 0,
                  loop: int = 0) -> bytes:
    """Un chunk de sonido **externo** del banco, con la geometria medida.

    La subcabecera es la `0x793A1FD7` (externa): `formato` en `+0x14`,
    `data_offset` en `+0x34` y `data_size` en `+0x38`, los dos ultimos relativos
    al KTSR del `.srst`.
    """
    cuerpo = bytearray(bytes(0x20 + 0x50))
    struct.pack_into(">I", cuerpo, 0x00, snd.CHUNK_SOUND)
    struct.pack_into("<I", cuerpo, 0x04, len(cuerpo))
    struct.pack_into("<I", cuerpo, 0x08, sound_id)
    struct.pack_into("<I", cuerpo, 0x0C, 0x10000)      # externo
    struct.pack_into("<I", cuerpo, 0x10, 1)
    struct.pack_into("<I", cuerpo, 0x14, 0x1C)         # delta al delta de la cabecera
    struct.pack_into("<I", cuerpo, 0x18, 0)            # sin nombre
    struct.pack_into("<I", cuerpo, 0x1C, 0x20)         # delta de la subcabecera
    hoff = 0x20
    struct.pack_into(">I", cuerpo, hoff + 0x00, 0x793A1FD7)
    struct.pack_into("<I", cuerpo, hoff + 0x04, len(cuerpo) - hoff)
    struct.pack_into("<I", cuerpo, hoff + 0x0C, canales)
    struct.pack_into("<I", cuerpo, hoff + 0x14, 0x1001)     # KA1A externo
    struct.pack_into("<i", cuerpo, hoff + 0x18, rate)
    struct.pack_into("<i", cuerpo, hoff + 0x1C, muestras)
    struct.pack_into("<i", cuerpo, hoff + 0x24, loop)
    struct.pack_into("<I", cuerpo, hoff + 0x28, 3)
    struct.pack_into("<I", cuerpo, hoff + 0x34, data_offset)
    struct.pack_into("<I", cuerpo, hoff + 0x38, data_size)
    struct.pack_into("<I", cuerpo, hoff + 0x3C, 0x200)
    struct.pack_into("<f", cuerpo, hoff + 0x40, 1.0)
    struct.pack_into("<I", cuerpo, hoff + 0x44, 1)
    return bytes(cuerpo)


def banco_externo(pistas: list[tuple[int, bytes]]) -> bytes:
    """Un `.srsa` con un chunk externo por pista, apuntando a su offset del `.srst`.

    No es un banco completo del juego: lleva solo lo que el kit lee para
    emparejar stream -> pista (`sound id`, `data_offset` y `data_size`).
    """
    cuerpos = []
    offset = 0x60            # el primer chunk del `.srst` empieza en 0x50: 0x10 + 0x60
    for i, (sound_id, plano) in enumerate(pistas, start=1):
        campos = srst.ka1a_fields(plano[:srst.KA1A_HEADER_SIZE])
        cuerpos.append(chunk_externo(sound_id, offset, len(plano),
                                     canales=campos["canales"], rate=campos["hz"],
                                     muestras=campos["muestras"], loop=campos["bucle"]))
        offset += (0x20 + len(plano) + 15) // 16 * 16
    return _banco(cuerpos)


def _banco(cuerpos: list[bytes]) -> bytes:
    total = 0x50 + sum(len(c) for c in cuerpos)
    cabeza = bytearray(0x50)
    cabeza[0:4] = b"ASRS"
    struct.pack_into("<Q", cabeza, 8, total)
    cabeza[0x10:0x14] = b"KTSR"
    struct.pack_into("<I", cabeza, 0x14, snd.KTSR_ID_SOUND)
    struct.pack_into("<H", cabeza, 0x18, 1)
    struct.pack_into("<H", cabeza, 0x1A, 0x05F0)
    cabeza[0x1B] = 5
    struct.pack_into("<I", cabeza, 0x1C, AUDIO_ID)
    struct.pack_into("<I", cabeza, 0x28, total - 0x10)
    struct.pack_into("<I", cabeza, 0x2C, total - 0x10)
    cabeza[0x30] = len(CLAVE)
    cabeza[0x31:0x31 + len(CLAVE)] = CLAVE
    return bytes(cabeza) + b"".join(cuerpos)


# ---------------------------------------------------------------------------
# Contra el dump real (se salta con motivo si no esta)
# ---------------------------------------------------------------------------

ROMFS = os.environ.get("PKP_ROMFS", "")
necesita_dump = pytest.mark.skipif(
    not os.path.isdir(ROMFS), reason="sin dump del juego (exporta PKP_ROMFS)")


@necesita_dump
def test_el_srst_del_dump_es_el_del_banco_de_83_pistas() -> None:
    """El `.srst` grande y el banco `0x1e474a88`: 83 pistas, emparejadas y cifradas."""
    from pokopia import fdata

    ruta_srst = None
    for dirpath, _, ficheros in os.walk(ROMFS):
        if os.path.basename(dirpath) == "data" and "0x0b5db05b.file" in ficheros:
            ruta_srst = os.path.join(dirpath, "0x0b5db05b.file")
    if ruta_srst is None:
        pytest.skip("este dump no trae el .srst del banco 0x1e474a88")
    s, datos = srst.read(ruta_srst)
    assert s.prefix == 56
    assert len(s.tracks) == 83
    assert len(s.key) == 7
    # el payload es el que ya censo t_f3d346ee
    assert srst.sha256_payload(datos).startswith("1dc7188157261aeb")

    banco_datos = None
    ktid = fdata.parse_type("srsa")
    for ruta in fdata.find_fdata(ROMFS):
        with open(ruta, "rb") as fh:
            for entry in fdata.iter_entries(ruta):
                if entry.type_ktid == ktid and entry.name_hash == 0x1E474A88:
                    banco_datos = fdata.read_entry(fh, entry)
                    break
        if banco_datos:
            break
    if banco_datos is None:
        pytest.skip("este dump no trae el banco 0x1e474a88")
    banco = snd.parse(banco_datos)
    assert len(banco.streams) == 83
    for stream in banco.streams:
        track = s.by_data_offset(stream.data_offset)
        assert track is not None
        assert track.sound_id == stream.sound_id
        assert track.data_size == stream.data_size
    # la pista 70 es la que usa el disco nuevo: cabecera KA1A dentro del cifrado
    track = s.track(70)
    assert track.channels == 2 and track.sample_rate == 48000
    assert track.bitrate_mode == 5
    plano = srst.track_plain(datos, 70)
    assert plano[:4] == srst.KA1A_MAGIC
    assert len(plano) == srst.KA1A_HEADER_SIZE + srst.ka1a_fields(
        plano[:srst.KA1A_HEADER_SIZE])["tamano"]

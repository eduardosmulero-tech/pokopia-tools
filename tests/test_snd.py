"""Bancos de sonido `.srsa` (ASRS/KTSR): leer, extraer e intercambiar audio.

Ningun fixture del juego: cada banco de estas pruebas se construye aqui byte a
byte con la geometria medida en el dump, para que la suite corra sin el dump y
sin material de terceros. Los casos que importan:

* el indice del banco se lee entero (codec, frecuencia, muestras, bucle, nombre);
* intercambiar dos sonidos mueve chunks y **no toca ni un byte de audio**;
* sustituir un flujo de otro tamano reescribe los tres tamanos y deja el resto
  igual, y el resultado se vuelve a analizar sin errores;
* nada se escribe dentro del romfs.

Y una prueba contra el dump real, que se salta con motivo si no esta.
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from pokopia import paths, snd
from pokopia.cli import main

AUDIO_ID = 0x3CDC3E84
SUBTIPO = 0x6FCAB62E
HASH = 0x1CDE6AF2


# ---------------------------------------------------------------------------
# Construccion de un banco sintetico
# ---------------------------------------------------------------------------

def nombre_cifrado(nombre: str, semilla: int = AUDIO_ID) -> bytes:
    """Cifra `nombre` como lo hace el juego: LCG + XOR, byte a byte."""
    salida = bytearray()
    for letra in nombre.encode("ascii"):
        semilla = (0x343FD * semilla + 0x269EC3) & 0xFFFFFFFF
        salida.append(letra ^ ((semilla >> 16) & 0xFF))
    return bytes(salida)


def chunk_sonido(index: int, payload: bytes, *, codec: str = "ka1a",
                 rate: int = 48000, muestras: int = 1000, loop: int = -1,
                 nombre: str = "", cifrado: bool = True,
                 sound_id: int | None = None,
                 bloque: int | None = None,
                 modo: int = -1) -> bytes:
    """Un chunk de sonido completo con la geometria medida (cabecera en +0x20).

    En KA1A la cabecera extra lleva el modo de bitrate (`modo`, por defecto -1);
    en MS ADPCM lleva dos `u16`: muestras por bloque y bytes por bloque, que se
    piden con `bloque`.
    """
    formato = snd.FORMAT_BY_CODEC[codec]
    id_sonido = sound_id if sound_id is not None else 0x1000 + index
    sufijo = nombre_cifrado(nombre) if (nombre and cifrado) else nombre.encode("ascii")
    # cabecera del chunk (0x20) + cabecera de sonido (0x54) = 0x74; luego el nombre
    cuerpo = bytearray(b"\x00" * 0x74)
    inicio_nombre = 0
    if sufijo:
        inicio_nombre = 0x74
        cuerpo += sufijo + b"\x00"
        while len(cuerpo) % 16:
            cuerpo += b"\x00"
    inicio_datos = len(cuerpo)
    cuerpo += payload
    while len(cuerpo) % snd.CHUNK_ALIGN:
        cuerpo += b"\x00"

    struct.pack_into(">I", cuerpo, 0x00, snd.CHUNK_SOUND)
    struct.pack_into("<I", cuerpo, 0x04, len(cuerpo))
    struct.pack_into("<I", cuerpo, 0x08, id_sonido)
    struct.pack_into("<I", cuerpo, 0x0C, snd.FLAG_ENCRYPTED_NAME if cifrado else 0)
    struct.pack_into("<I", cuerpo, 0x10, 1)          # un flujo
    struct.pack_into("<I", cuerpo, 0x14, 0x1C)       # delta al delta de la cabecera
    struct.pack_into("<I", cuerpo, 0x18, inicio_nombre)
    struct.pack_into("<I", cuerpo, 0x1C, 0x20)       # delta de la cabecera de sonido

    hoff = 0x20
    struct.pack_into(">I", cuerpo, hoff + 0x00, SUBTIPO)
    struct.pack_into("<I", cuerpo, hoff + 0x04, len(cuerpo) - hoff)
    struct.pack_into("<I", cuerpo, hoff + 0x08, HASH)
    struct.pack_into("<I", cuerpo, hoff + 0x0C, 1)              # canales
    cuerpo[hoff + 0x10] = formato
    struct.pack_into("<i", cuerpo, hoff + 0x14, rate)
    struct.pack_into("<i", cuerpo, hoff + 0x18, muestras)
    struct.pack_into("<I", cuerpo, hoff + 0x1C, 0)
    struct.pack_into("<i", cuerpo, hoff + 0x20, loop)
    struct.pack_into("<I", cuerpo, hoff + 0x24, 0)
    struct.pack_into("<I", cuerpo, hoff + 0x28, 0x48)           # cabecera extra
    struct.pack_into("<I", cuerpo, hoff + 0x2C, 4)
    struct.pack_into("<I", cuerpo, hoff + 0x30, 0x4C)           # tabla de inicios
    struct.pack_into("<I", cuerpo, hoff + 0x34, 0x50)           # tabla de tamanos
    struct.pack_into("<I", cuerpo, hoff + 0x38, 0x3B1F04A1)
    struct.pack_into("<I", cuerpo, hoff + 0x40, 0x58)
    struct.pack_into("<I", cuerpo, hoff + 0x44, 0x3BFD88C9)
    if bloque is not None:
        struct.pack_into("<HH", cuerpo, hoff + 0x48,
                         (bloque - 7) * 2 + 2, bloque)            # MS ADPCM
    else:
        struct.pack_into("<i", cuerpo, hoff + 0x48, modo)          # modo de bitrate
    struct.pack_into("<I", cuerpo, hoff + 0x4C, inicio_datos - hoff)   # relativo a la cabecera
    struct.pack_into("<I", cuerpo, hoff + 0x50, len(payload))
    return bytes(cuerpo)


def chunk_config(nombre: str = "config") -> bytes:
    """Chunk de configuracion: no lleva desplazamientos, solo el id del sonido."""
    cuerpo = bytearray(b"\x00" * 0x20)
    struct.pack_into(">I", cuerpo, 0x00, snd.CHUNK_CONFIG)
    struct.pack_into("<I", cuerpo, 0x04, 0x20)
    struct.pack_into("<I", cuerpo, 0x08, 0x1001)
    cuerpo[0x10:0x10 + len(nombre)] = nombre.encode("ascii")
    return bytes(cuerpo)


def banco_sintetico(chunks: list[bytes], *, audio_id: int = AUDIO_ID,
                    platform: int = 5) -> bytes:
    """Cabecera ASRS + KTSR + chunks, con los tres tamanos ya calculados."""
    cabecera = bytearray(b"\x00" * snd.KTSR_CHUNKS_OFFSET)
    cabecera[0x00:0x04] = snd.ASRS_MAGIC
    cabecera[0x10:0x14] = snd.KTSR_MAGIC
    struct.pack_into("<I", cabecera, 0x14, snd.KTSR_ID_SOUND)
    struct.pack_into("<H", cabecera, 0x18, 1)
    struct.pack_into("<H", cabecera, 0x1A, 0x05F0)
    cabecera[0x1B] = platform
    struct.pack_into("<I", cabecera, 0x1C, audio_id)
    total = snd.KTSR_CHUNKS_OFFSET + sum(len(c) for c in chunks)
    struct.pack_into("<Q", cabecera, 0x08, total)
    struct.pack_into("<I", cabecera, 0x28, total - snd.ASRS_HEADER_SIZE)
    struct.pack_into("<I", cabecera, 0x2C, total - snd.ASRS_HEADER_SIZE)
    return bytes(cabecera) + b"".join(chunks)


AUDIO_1 = bytes(range(200))
AUDIO_2 = bytes((i * 3 + 7) % 251 for i in range(300))
AUDIO_3 = bytes((i * 7) % 251 for i in range(150))


def banco_de_tres() -> bytes:
    return banco_sintetico([
        chunk_config(),
        chunk_sonido(1, AUDIO_1, muestras=2000, loop=500, nombre="SE_UNO"),
        chunk_sonido(2, AUDIO_2, muestras=3000, nombre="SE_DOS"),
        chunk_sonido(3, AUDIO_3, codec="msadpcm",
                     rate=32000, muestras=700, nombre="SE_TRES", cifrado=False),
    ])


def escribir(tmp_path, nombre: str, datos: bytes) -> str:
    ruta = tmp_path / nombre
    ruta.write_bytes(datos)
    return str(ruta)


# ---------------------------------------------------------------------------
# Indice del banco
# ---------------------------------------------------------------------------

def test_lee_cabecera_y_los_tres_streams():
    banco = snd.parse(banco_de_tres())
    assert banco.size == len(banco_de_tres())
    assert banco.declared_size == banco.size
    assert banco.ktsr_size == banco.size - snd.ASRS_HEADER_SIZE
    assert banco.audio_id == AUDIO_ID
    assert banco.platform == 5
    assert len(banco.chunks) == 4
    assert [c.type for c in banco.chunks].count(snd.CHUNK_SOUND) == 3
    assert banco.codecs == {"ka1a": 2, "msadpcm": 1}
    assert [s.index for s in banco.streams] == [1, 2, 3]
    assert [s.num_samples for s in banco.streams] == [2000, 3000, 700]
    assert [s.sample_rate for s in banco.streams] == [48000, 48000, 32000]
    assert banco.streams[0].loop_start == 500
    assert banco.streams[1].loop_start == -1
    assert banco.streams[2].codec == "msadpcm"
    assert banco.streams[0].duration == pytest.approx(2000 / 48000)


def test_payload_es_solo_el_audio():
    datos = banco_de_tres()
    banco = snd.parse(datos)
    assert snd.payload(datos, banco.streams[0]) == AUDIO_1
    assert snd.payload(datos, banco.streams[1]) == AUDIO_2
    with pytest.raises(snd.SndStreamError):
        banco.stream(9)


def test_nombre_cifrado_y_nombre_en_claro():
    banco = snd.parse(banco_de_tres())
    assert banco.streams[0].name == "SE_UNO"          # cifrado con el LCG
    assert banco.streams[1].name == "SE_DOS"
    assert banco.streams[2].name == "SE_TRES"         # sin cifrar (flag apagado)


def test_decrypt_name_corta_en_el_cero():
    crudo = nombre_cifrado("AB") + b"\x00" + nombre_cifrado("CD")
    assert snd.decrypt_name(crudo, AUDIO_ID) == "AB"


def test_firma_y_tamanos_malos():
    datos = bytearray(banco_de_tres())
    malo = bytes(b"NOPE") + bytes(datos[4:])
    with pytest.raises(snd.SndFormatError):
        snd.parse(malo)
    truncado = bytes(datos[:-16])
    with pytest.raises(snd.SndFormatError):
        snd.parse(truncado)


def test_subcabecera_desconocida_se_rechaza():
    datos = bytearray(banco_de_tres())
    # el primer chunk de sonido empieza tras el de configuracion (0x50 + 0x20)
    hoff = 0x50 + 0x20 + 0x20
    struct.pack_into(">I", datos, hoff, 0xDEADBEEF)
    with pytest.raises(snd.SndFormatError):
        snd.parse(bytes(datos))


# ---------------------------------------------------------------------------
# Intercambio de dos sonidos
# ---------------------------------------------------------------------------

def test_swap_cambia_de_sitio_los_dos_chunks_y_nada_mas():
    datos = banco_de_tres()
    banco = snd.parse(datos)
    modificado = snd.swap_streams(datos, 1, 2)
    nuevo = snd.parse(modificado)

    assert nuevo.size == banco.size                     # el tamano no cambia
    assert len(nuevo.streams) == 3
    assert [c.type for c in nuevo.chunks] == [c.type for c in banco.chunks]
    # el audio de cada indice se ha cruzado
    assert snd.payload(modificado, nuevo.streams[0]) == AUDIO_2
    assert snd.payload(modificado, nuevo.streams[1]) == AUDIO_1
    # y el tercero sigue donde estaba, byte a byte
    original = snd.payload(datos, banco.streams[2])
    assert snd.payload(modificado, nuevo.streams[2]) == original
    # los ids viajan con el chunk: el indice 1 declara ahora el sonido del 2
    assert nuevo.streams[0].sound_id == banco.streams[1].sound_id
    assert nuevo.streams[0].num_samples == banco.streams[1].num_samples
    assert nuevo.streams[0].name == "SE_DOS"


def test_swap_dos_veces_devuelve_el_banco_original():
    datos = banco_de_tres()
    ida = snd.swap_streams(datos, 1, 3)
    vuelta = snd.swap_streams(ida, 1, 3)
    assert vuelta == datos


def test_swap_de_un_stream_consigo_mismo_es_un_error():
    with pytest.raises(snd.SndStreamError):
        snd.swap_streams(banco_de_tres(), 2, 2)


def test_swap_orden_invertido_da_lo_mismo():
    datos = banco_de_tres()
    assert snd.swap_streams(datos, 1, 2) == snd.swap_streams(datos, 2, 1)


# ---------------------------------------------------------------------------
# Sustitucion de los datos de un stream
# ---------------------------------------------------------------------------

def test_replace_mismo_tamano_cambia_solo_el_audio():
    datos = banco_de_tres()
    banco = snd.parse(datos)
    nuevo_audio = bytes((i * 3) % 251 for i in range(300))
    modificado = snd.replace_stream(datos, 2, nuevo_audio)
    nuevo = snd.parse(modificado)

    assert len(modificado) == len(datos)
    assert snd.payload(modificado, nuevo.streams[1]) == nuevo_audio
    assert snd.payload(modificado, nuevo.streams[0]) == snd.payload(datos, banco.streams[0])
    assert snd.payload(modificado, nuevo.streams[2]) == snd.payload(datos, banco.streams[2])
    # la cabecera del sonido 2 no cambia: solo el audio
    assert nuevo.streams[1].num_samples == banco.streams[1].num_samples
    assert nuevo.streams[1].name == "SE_DOS"


def test_replace_de_otro_tamano_reescribe_los_tres_tamanos():
    datos = banco_de_tres()
    corto = b"\xaa" * 40
    modificado = snd.replace_stream(datos, 2, corto)
    nuevo = snd.parse(modificado)

    assert len(modificado) < len(datos)
    assert nuevo.size == len(modificado)
    assert nuevo.declared_size == len(modificado)
    assert nuevo.ktsr_size == len(modificado) - snd.ASRS_HEADER_SIZE
    assert snd.payload(modificado, nuevo.streams[1]) == corto
    chunk = next(c for c in nuevo.chunks if c.is_sound and c.offset == nuevo.streams[1].chunk_offset)
    assert chunk.size == chunk.size // snd.CHUNK_ALIGN * snd.CHUNK_ALIGN
    # el campo de la cabecera de sonido declara lo que va del chunk a su fin
    assert struct.unpack_from("<I", modificado, nuevo.streams[1].header_offset + 0x04)[0] == (
        chunk.size - (nuevo.streams[1].header_offset - chunk.offset))
    # los otros dos, intactos
    assert snd.payload(modificado, nuevo.streams[0]) == snd.payload(datos, snd.parse(datos).streams[0])
    assert snd.payload(modificado, nuevo.streams[2]) == snd.payload(datos, snd.parse(datos).streams[2])


def test_replace_mas_largo_que_el_original_tambien_cuadra():
    datos = banco_de_tres()
    largo = bytes((i * 11) % 251 for i in range(1234))
    modificado = snd.replace_stream(datos, 3, largo)
    nuevo = snd.parse(modificado)
    assert len(modificado) > len(datos)
    assert snd.payload(modificado, nuevo.streams[2]) == largo


def test_replace_con_donor_copia_la_cabecera_de_audio_y_no_el_id():
    destino = banco_de_tres()
    origen = banco_sintetico([
        chunk_sonido(1, bytes(range(50)), rate=44100, muestras=999, loop=123,
                     nombre="SE_ORIGEN"),
    ])
    donor_banco = snd.parse(origen)
    modificado = snd.replace_stream(destino, 1,
                                    snd.payload(origen, donor_banco.streams[0]),
                                    (origen, donor_banco.streams[0]))
    nuevo = snd.parse(modificado)
    assert nuevo.streams[0].sample_rate == 44100
    assert nuevo.streams[0].num_samples == 999
    assert nuevo.streams[0].loop_start == 123
    assert nuevo.streams[0].name == "SE_UNO"              # el nombre es del destino
    assert nuevo.streams[0].sound_id == snd.parse(destino).streams[0].sound_id


def test_replace_rechaza_codec_distinto_y_vacio():
    destino = banco_de_tres()
    origen = banco_sintetico([
        chunk_sonido(1, bytes(range(50)), codec="msadpcm", rate=32000, muestras=10),
    ])
    donor = snd.parse(origen)
    with pytest.raises(snd.SndStreamError):
        snd.replace_stream(destino, 1, b"\x00" * 8, (origen, donor.streams[0]))
    with pytest.raises(snd.SndStreamError):
        snd.replace_stream(destino, 1, b"")


# ---------------------------------------------------------------------------
# Disco: extraer y escribir sin tocar el dump
# ---------------------------------------------------------------------------

def test_extract_nombra_indice_y_codec(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    assert main(["snd", "extract", ruta, "--out", str(tmp_path / "out")]) == 0
    ficheros = sorted(os.listdir(str(tmp_path / "out")))
    assert ficheros == ["banco.001.ka1a", "banco.002.ka1a", "banco.003.adpcm"]
    with open(str(tmp_path / "out" / "banco.001.ka1a"), "rb") as fh:
        assert fh.read() == AUDIO_1
    # idempotente: la segunda pasada escribe los mismos bytes
    assert main(["snd", "extract", ruta, "--out", str(tmp_path / "out")]) == 0
    with open(str(tmp_path / "out" / "banco.001.ka1a"), "rb") as fh:
        assert fh.read() == AUDIO_1


def test_extract_en_el_romfs_esta_prohibido(tmp_path, monkeypatch, capsys):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    assert main(["snd", "extract", ruta, "--out", str(romfs / "salida")]) == 2
    assert "destino protegido" in capsys.readouterr().err
    assert not (romfs / "salida").exists()


def test_escribir_en_el_romfs_esta_prohibido(tmp_path, monkeypatch, capsys):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    ruta = escribir(romfs, "banco.srsa", banco_de_tres())
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    assert main(["snd", "replace", ruta, "--swap", "1", "2", "--in-place"]) == 2
    assert "destino protegido" in capsys.readouterr().err


def test_replace_en_sitio_deja_copia_original_una_vez(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    antes = paths.sha256_file(ruta)
    assert main(["snd", "replace", ruta, "--swap", "1", "2", "--in-place"]) == 0
    despues = paths.sha256_file(ruta)
    assert despues != antes
    assert paths.sha256_file(ruta + ".orig") == antes
    # segunda pasada: la copia no se pisa (sigue siendo el original)
    assert main(["snd", "replace", ruta, "--swap", "1", "3", "--in-place"]) == 0
    assert paths.sha256_file(ruta + ".orig") == antes
    # no quedan temporales
    assert not any(n.endswith(".tmp") for n in os.listdir(str(tmp_path)))


def test_replace_exige_in_place_o_salida(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    assert main(["snd", "replace", ruta, "--swap", "1", "2"]) == 2
    assert "--in-place" in capsys.readouterr().err


def test_replace_a_fichero_nuevo_no_toca_el_origen(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    antes = paths.sha256_file(ruta)
    salida = str(tmp_path / "mod.srsa")
    assert main(["snd", "replace", ruta, "--swap", "1", "2", "-o", salida]) == 0
    assert paths.sha256_file(ruta) == antes
    assert not os.path.exists(ruta + ".orig")
    assert paths.sha256_file(salida) != antes
    assert snd.parse(open(salida, "rb").read()).size == os.path.getsize(salida)


def test_cli_list_en_json(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    assert main(["snd", "list", ruta, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["stream_count"] == 3
    assert doc["codecs"] == {"ka1a": 2, "msadpcm": 1}
    assert [s["name"] for s in doc["streams"]] == ["SE_UNO", "SE_DOS", "SE_TRES"]


def test_cli_swap_incompatible_con_stream_y_file(tmp_path, capsys):
    ruta = escribir(tmp_path, "banco.srsa", banco_de_tres())
    assert main(["snd", "replace", ruta, "--swap", "1", "2",
                 "--stream", "1", "--file", ruta]) == 2
    assert "--swap" in capsys.readouterr().err


def test_cli_replace_con_donor_desde_otro_banco(tmp_path, capsys):
    destino = escribir(tmp_path, "destino.srsa", banco_de_tres())
    origen = escribir(tmp_path, "origen.srsa", banco_sintetico([
        chunk_sonido(1, bytes(range(50)), rate=44100, muestras=999),
    ]))
    flujo = tmp_path / "flujo.ka1a"
    flujo.write_bytes(snd.payload(open(origen, "rb").read(),
                                  snd.parse(open(origen, "rb").read()).streams[0]))
    assert main(["snd", "replace", destino, "--stream", "1", "--file", str(flujo),
                 "--from-banco", origen, "--from-stream", "1",
                 "-o", str(tmp_path / "mod.srsa")]) == 0
    banco = snd.parse(open(str(tmp_path / "mod.srsa"), "rb").read())
    assert banco.streams[0].sample_rate == 44100
    assert banco.streams[0].num_samples == 999


def test_stat_cuenta_codecs_y_pares(tmp_path, capsys):
    escribir(tmp_path, "uno.srsa", banco_de_tres())
    escribir(tmp_path, "dos.srsa", banco_sintetico([chunk_sonido(1, b"\x01" * 64)]))
    assert main(["snd", "stat", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["banks"] == 2
    assert doc["streams"] == 4
    assert doc["codecs"] == {"ka1a": 3, "msadpcm": 1}
    assert doc["swappable"] == 3          # solo el banco de tres
    assert doc["problems"] == []


def test_stat_sin_bancos_es_un_error(tmp_path, capsys):
    assert main(["snd", "stat", str(tmp_path)]) == 1
    assert "no hay ningun .srsa" in capsys.readouterr().err


def test_list_de_firma_mala(tmp_path, capsys):
    ruta = escribir(tmp_path, "malo.srsa", b"NOTA" + b"\x00" * 100)
    assert main(["snd", "list", ruta]) == 1
    assert "ASRS" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# El dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
necesita_dump = pytest.mark.skipif(
    not os.path.isdir(ROMFS), reason="sin dump del juego (exporta PKP_ROMFS)")


@necesita_dump
def test_lee_un_banco_del_dump_real():
    """El `.fdata` de sonidos: primera entrada `srsa`, analizada en memoria."""
    from pokopia import fdata

    objetivo = None
    for ruta in fdata.find_fdata(ROMFS):
        for entry in fdata.iter_entries(ruta):
            if entry.type_ktid == fdata.parse_type("srsa"):
                objetivo = (ruta, entry)
                break
        if objetivo:
            break
    if not objetivo:
        pytest.skip("este dump no tiene entradas srsa")

    ruta, entry = objetivo
    datos = fdata.read_entry_from(ruta, entry)
    banco = snd.parse(datos)
    assert banco.streams, "el banco no declara streams"
    assert banco.declared_size == len(datos)
    for stream in banco.streams:
        if not stream.external:
            assert snd.payload(datos, stream), "stream %d sin datos" % stream.index
            assert stream.codec in ("ka1a", "msadpcm")

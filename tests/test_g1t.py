"""`G1T`: lectura, reescritura y round-trip. Todo con ficheros sinteticos.

Ningun fixture del juego: cada `.g1t` de estas pruebas se construye aqui byte a byte
con el mismo formato que el dump, para que la suite corra sin el dump y sin material
de terceros. Los casos que importan son los que costaron horas en la medicion:

* la tabla de offsets va en `header_size` y sus valores son relativos a el;
* la seccion `data[]` (12/16/20 B) va tras la cabecera de 8 B de la textura y **no**
  la anuncia el flag `EXTENDED_DATA` en este build: se detecta por aritmetica;
* los 5 bytes de flags van con los nibbles cambiados;
* la reconstruccion desde los campos tiene que ser identica al original.

Y un par de pruebas contra el dump real, que se saltan con motivo si no esta.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct

import pytest

from pokopia import fdata, g1t, paths
from pokopia.cli import main

# ---------------------------------------------------------------------------
# Construccion de un .g1t sintetico
# ---------------------------------------------------------------------------


def _cuerpo(mip_sys: int, fmt: int, dxdy: int, flags: bytes, extra: bytes,
            pixeles: bytes) -> bytes:
    return bytes((mip_sys, fmt, dxdy)) + flags + extra + pixeles


def make_g1t(cuerpos: list[bytes], *, version: bytes = b"0600", platform: int = 0x18,
             pre_tabla: bytes = b"", extra_global: bytes = b"") -> bytes:
    """Un `.g1t` completo con la tabla y los cuerpos dados."""
    count = len(cuerpos)
    tabla = bytearray()
    cola = 4 * count + len(extra_global)
    for cuerpo in cuerpos:
        tabla += struct.pack("<I", cola)
        cola += len(cuerpo)
    total = 0x1C + len(pre_tabla) + len(tabla) + len(extra_global) + sum(map(len, cuerpos))
    cabecera = b"GT1G" + version + struct.pack(
        "<5I", total, 0x1C + len(pre_tabla), count, platform, len(extra_global))
    return bytes(cabecera) + pre_tabla + bytes(tabla) + extra_global + b"".join(cuerpos)


FLAGS_VISTOS = bytes((0x00, 0x11, 0x10, 0x21, 0x10))     # 0x0112011100 al deshacer
SECCION12 = struct.pack("<I", 12) + struct.pack("<f", 0.0) + struct.pack(">I", 1)


def un_g1t_simple() -> bytes:
    """rgba8 1x1, sin seccion extra, con 4 B de pixel."""
    return make_g1t([_cuerpo(0x10, 0x01, 0x00, b"\x00" * 5, b"", b"\x01\x02\x03\x04")])


# ---------------------------------------------------------------------------
# Cabecera: campos y geometria
# ---------------------------------------------------------------------------


def test_parse_de_la_cabecera_fija():
    doc = g1t.parse(un_g1t_simple(), source_name="simple")
    assert doc.version == b"0600"
    assert doc.platform == 0x18
    assert doc.platform_name == "switch2"
    assert doc.header_size == 0x1C
    assert len(doc.textures) == 1
    tex = doc.textures[0]
    assert (tex.mip_sys, tex.format_code, tex.dxdy) == (0x10, 0x01, 0x00)
    assert (tex.mip_count, tex.tile_system) == (1, 0)
    assert (tex.width, tex.height) == (1, 1)
    assert tex.data_offset == 0x1C + 4 + 8
    assert tex.data_size == 4
    assert tex.frames_size == 4
    assert tex.extra == b""


def test_flags_con_los_nibbles_cambiados():
    """Los 5 bytes del fichero son los flags de `gust_g1t.c`, con orden y nibbles al reves."""
    doc = g1t.parse(make_g1t([_cuerpo(0x10, 0x66, 0xab, FLAGS_VISTOS, SECCION12, b"\x00")]))
    tex = doc.textures[0]
    assert tex.flags == 0x0011011201
    assert tex.has_flag(g1t.FLAG_EXTENDED_DATA)
    assert tex.has_flag(g1t.FLAG_STANDARD_FLAGS)
    assert not tex.has_flag(g1t.FLAG_SRGB)


def test_seccion_extra_la_anuncia_el_flag_y_cuadra_aritmeticamente():
    """Medido: `EXTENDED_DATA` viene puesto en las 14.168 texturas que llevan seccion."""
    doc = g1t.parse(make_g1t([_cuerpo(0x10, 0x66, 0xab, FLAGS_VISTOS, SECCION12, b"\x00")]))
    tex = doc.textures[0]
    assert tex.extended
    assert tex.extra == SECCION12
    assert tex.extra_size_field == 12
    assert tex.header_size == 8 + 12
    assert tex.data_offset == 0x1C + 4 + 20


def test_dimensiones_de_la_seccion_mandan_sobre_dxdy():
    """Con seccion de 16 B, `data[3]` es el ancho real (texturas que no son potencia de 2)."""
    ancho, alto = 24, 8
    seccion = struct.pack("<I", 16) + struct.pack("<f", 0.0) + struct.pack(">I", 1) \
        + struct.pack("<I", ancho)
    pixeles = bytes(ancho * alto * 4)
    doc = g1t.parse(make_g1t([_cuerpo(0x10, 0x01, 0x33, FLAGS_VISTOS, seccion, pixeles)]))
    tex = doc.textures[0]
    assert tex.width == ancho
    assert tex.height == 8
    assert tex.data_size == len(pixeles)
    assert tex.frames_size == len(pixeles)


def test_dos_texturas_y_offsets_relativos():
    uno = _cuerpo(0x10, 0x01, 0x00, b"\x00" * 5, b"", b"\x01\x02\x03\x04")
    otro = _cuerpo(0x10, 0x01, 0x11, b"\x00" * 5, b"", b"\xff" * 8)
    doc = g1t.parse(make_g1t([uno, otro]))
    assert len(doc.textures) == 2
    assert doc.textures[0].data_offset == 0x1C + 8 + 8
    assert doc.textures[1].data_offset == 0x1C + 8 + len(uno) + 8
    assert doc.textures[1].width == 2 and doc.textures[1].height == 2


def test_ancho_y_alto_declarados_en_zona_alta_del_dxdy():
    doc = g1t.parse(make_g1t([_cuerpo(0x10, 0x01, 0xab, b"\x00" * 5, b"", b"\x00" * 8)]))
    tex = doc.textures[0]
    assert tex.width == 2048
    assert tex.height == 1024


# ---------------------------------------------------------------------------
# Reconstruccion byte a byte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pre", [b"", b"\x00\x00\x00\x00", b"\x00" * 8])
@pytest.mark.parametrize("global_extra", [b"", b"\xa5" * 16])
def test_rebuild_identico_con_pre_tabla_y_extra_global(pre, global_extra):
    """Las versiones 0500/1600 meten flags por textura delante de la tabla y datos extra."""
    cuerpo = _cuerpo(0x10, 0x01, 0x00, FLAGS_VISTOS, SECCION12, b"\x01\x02\x03\x04")
    datos = make_g1t([cuerpo], version=b"1600", pre_tabla=pre, extra_global=global_extra)
    doc = g1t.parse(datos, source_name="variantes")
    assert doc.pre_table == pre
    assert doc.global_extra == global_extra
    assert doc.rebuild() == datos


def test_with_payload_no_cambia_tamanos():
    datos = make_g1t([_cuerpo(0x10, 0x01, 0x00, b"\x00" * 5, b"", b"\x01\x02\x03\x04")])
    doc = g1t.parse(datos)
    nuevo = doc.with_payload(0, b"\x09\x09\x09\x09")
    assert len(nuevo) == len(datos)
    assert nuevo[-4:] == b"\x09\x09\x09\x09"
    with pytest.raises(g1t.G1TError):
        doc.with_payload(0, b"\x00\x00")


# ---------------------------------------------------------------------------
# Errores de cabecera
# ---------------------------------------------------------------------------


def test_magic_y_tamano_se_validan():
    with pytest.raises(g1t.G1TError, match="no empieza por GT1G"):
        g1t.parse(b"XXXX" + b"\x00" * 40)
    with pytest.raises(g1t.G1TError, match="big endian"):
        g1t.parse(b"G1TG" + b"\x00" * 40)
    datos = bytearray(un_g1t_simple())
    vacio = bytearray()
    doc = g1t.parse(bytes(datos))
    vacio = bytearray(doc.source)
    vacio[8:12] = struct.pack("<I", len(datos) + 4)
    with pytest.raises(g1t.G1TError, match="declara"):
        g1t.parse(bytes(vacio))


# ---------------------------------------------------------------------------
# Swizzle: el mapa de tiles es una biyeccion y se deshace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height,code", [
    (256, 256, 0x60), (512, 256, 0x62), (16, 64, 0x62), (8, 64, 0x66), (4, 4, 0x64),
])
def test_tile_map_es_biyectivo(width, height, code):
    fmt = g1t.format_of(code)
    mapa = g1t.tile_map(width, height, fmt)
    assert sorted(mapa) == list(range(len(mapa)))


@pytest.mark.parametrize("width,height,code", [(256, 128, 0x60), (64, 64, 0x66), (16, 64, 0x62)])
def test_untile_y_retile_son_inversas(width, height, code):
    fmt = g1t.format_of(code)
    bw = max(1, (width + 3) // 4)
    bh = max(1, (height + 3) // 4)
    filas = bytes(range(256)) * ((bw * bh * fmt.block) // 256 + 1)
    filas = filas[:bw * bh * fmt.block]
    assert g1t.retile(g1t.untile(filas, width, height, fmt), width, height, fmt) == filas


def test_el_tile_se_recorta_en_texturas_pequenas():
    """Un tile de 8 no cabe en 4x16 bloques: baja a 4 y el mapa sigue siendo valido."""
    fmt = g1t.format_of(0x62)
    mapa = g1t.tile_map(16, 64, fmt)
    assert sorted(mapa) == list(range(64))


# ---------------------------------------------------------------------------
# CLI: list, extract e inject
# ---------------------------------------------------------------------------


def _escribir(tmp_path, datos: bytes) -> str:
    ruta = tmp_path / "ejemplo.g1t"
    ruta.write_bytes(datos)
    return str(ruta)


def test_cli_list(tmp_path, capsys):
    ruta = _escribir(tmp_path, un_g1t_simple())
    assert main(["tex", "list", ruta]) == 0
    salida = capsys.readouterr().out
    assert "rgba8" in salida and "1 textura" in salida

    assert main(["tex", "list", ruta, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["files"][0]["textures"][0]["format"] == "rgba8"
    assert doc["files"][0]["platform"] == "switch2"


def test_cli_inject_same_es_identico(tmp_path, capsys):
    datos = make_g1t([_cuerpo(0x10, 0x66, 0xab, FLAGS_VISTOS, SECCION12, bytes(64))])
    ruta = _escribir(tmp_path, datos)
    salida = str(tmp_path / "copia.g1t")
    assert main(["tex", "inject", ruta, "--same", "--out", salida]) == 0
    assert hashlib.sha256(open(salida, "rb").read()).hexdigest() == \
        hashlib.sha256(datos).hexdigest()
    assert "IDENTICO byte a byte" in capsys.readouterr().out


def test_cli_inject_exige_decir_que_hace(tmp_path, capsys):
    ruta = _escribir(tmp_path, un_g1t_simple())
    with pytest.raises(SystemExit) as exc:
        main(["tex", "inject", ruta, "--out", str(tmp_path / "x.g1t")])
    assert exc.value.code == 2
    assert "--same" in capsys.readouterr().err


def test_cli_no_escribe_dentro_del_romfs(tmp_path, monkeypatch, capsys):
    ruta = _escribir(tmp_path, un_g1t_simple())
    protegido = tmp_path / "romfs"
    protegido.mkdir()
    monkeypatch.setenv(paths.PROTECTED_ENV, str(protegido))
    destino = str(protegido / "fuera.g1t")
    assert main(["tex", "inject", ruta, "--same", "--out", destino]) == 2
    assert "destino protegido" in capsys.readouterr().err


def test_cli_extract_y_reinyectar_un_pixel(tmp_path, capsys):
    """Con backend: PNG de ida, un pixel pintado, vuelta al .g1t y relectura."""
    pytest.importorskip("numpy")
    pytest.importorskip("imagecodecs")
    pytest.importorskip("etcpak")
    from pokopia import textures

    ancho = alto = 32
    pixeles = bytes([0, 0, 0, 255]) * (ancho * alto)
    datos = make_g1t([_cuerpo(0x10, 0x60, 0x55, FLAGS_VISTOS, SECCION12, pixeles)])
    ruta = _escribir(tmp_path, datos)
    png = str(tmp_path / "tex.png")
    assert main(["tex", "extract", ruta, "--out", png]) == 0
    img = textures.png_decode(open(png, "rb").read())
    assert img.shape == (alto, ancho, 4)

    img[:4, :4] = (255, 0, 0, 255)
    modificado = str(tmp_path / "tex-rojo.png")
    with open(modificado, "wb") as fh:
        fh.write(textures.png_encode(img))
    salida = str(tmp_path / "repintado.g1t")
    assert main(["tex", "inject", ruta, "--png", modificado, "--out", salida]) == 0
    assert os.path.getsize(salida) == len(datos)

    releido = str(tmp_path / "releido.png")
    assert main(["tex", "extract", salida, "--out", releido]) == 0
    vuelta = textures.png_decode(open(releido, "rb").read())
    assert vuelta[0, 0].tolist() == [255, 0, 0, 255]


# ---------------------------------------------------------------------------
# El dump real (se salta si no esta)
# ---------------------------------------------------------------------------

ROMFS = paths.configured_romfs()
HAY_DUMP = os.path.isdir(ROMFS) and any(
    nombre.endswith(".fdata")
    for _, _, ficheros in os.walk(ROMFS) for nombre in ficheros)
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego (exporta PKP_ROMFS)")


@necesita_dump
def test_rebuild_identico_sobre_un_fdata_real():
    """C2 sobre datos reales: parse -> rebuild tiene que dar el mismo sha256."""
    from pokopia import fdata as mod

    ruta = ""
    for candidato in mod.find_fdata(ROMFS):
        if os.path.getsize(candidato) < 40 * 1024 * 1024:
            with open(candidato, "rb") as fh:
                if any(e.type_ktid == 0xAFBEC60C for e in mod.iter_entries(candidato)):
                    ruta = candidato
                    break
    if not ruta:
        pytest.skip("ningun .fdata pequeno con g1t en este dump")

    vistos = identicos = 0
    with open(ruta, "rb") as fh:
        for entry in mod.iter_entries(ruta):
            if entry.type_ktid != 0xAFBEC60C:
                continue
            datos = mod.read_entry(fh, entry)
            doc = g1t.parse(datos, source_name="0x%08x" % entry.name_hash)
            vistos += 1
            identicos += doc.rebuild() == datos
            if vistos >= 300:
                break
    assert vistos > 0
    assert identicos == vistos

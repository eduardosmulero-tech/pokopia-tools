"""Animaciones `G2A`: leer, exportar, reescribir y tocar un valor.

Ningun fixture del juego: el `.g1a` de estas pruebas se construye aqui byte a
byte con `construir()`, que es una **segunda implementacion** del formato escrita
al reves que el modulo (escribe, no lee). Asi la identidad de ida y vuelta mide
algo: si `build` y `construir` coinciden, las dos lecturas del formato cuadran.

Lo que se fija aqui, y por que:

* el empaquetado de la cabecera (`length_frames` en 18 bits + tamano de la
  seccion de huesos en 14) — leerlo mal desplaza todo el fichero;
* la fila de 64 bits de un bloque: `z` en 0..19, `y` en 20..39, `x` en 40..59 y
  el exponente en 60..63, con valor `campo * 2**(exp-15)`;
* el relleno a 4 B de los registros de tiempos (un registro de 1 clave mide 12 B,
  no 10) — sin el, la seccion de tiempos no cuadra;
* que el magic en disco es `_A2G` y que un `G1A_` se rechaza con un mensaje que
  lo dice, porque los dos empiezan por `G` y se confunden.

Y dos pruebas contra el dump real (se saltan con motivo si no esta).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib

import pytest

from pokopia import anim, fdata
from pokopia.anim import g2a
from pokopia.cli import main

ROMFS = os.environ.get("PKP_ROMFS") or "romfs"
G1A = 0x6FA91671


# ---------------------------------------------------------------------------
# Constructor independiente del formato
# ---------------------------------------------------------------------------

def fila(x: int = 0, y: int = 0, z: int = 0, exp: int = 15) -> int:
    """Un `int64` con los tres campos de 20 bits y el exponente."""
    valor = ((z & 0xFFFFF) | ((y & 0xFFFFF) << 20) | ((x & 0xFFFFF) << 40)
             | ((exp & 0xF) << 60))
    return valor - (1 << 64) if valor >> 63 else valor


def bloque(*filas: int) -> bytes:
    """Un bloque de 32 B: los coeficientes `c0..c3`; los que falten son cero."""
    assert 1 <= len(filas) <= 4
    valores = list(filas) + [0] * (4 - len(filas))
    return struct.pack("<4q", *valores)


def construir(bones, *, fps: float = 60.0, seconds_frames: int = 10,
              version: bytes = b"0400", reserved: int = 0,
              pad_byte: int = 0) -> bytes:
    """Escribe un `G2A` desde una descripcion de huesos.

    `bones` es una lista de `(bone_id, [(opcode, [frames], [bloque, ...])])`.
    Devuelve los bytes, con los offsets de tiempos calculados como el juego:
    registros consecutivos alineados a 4 B.
    """
    info = bytearray()
    tiempos = bytearray()
    datos = bytearray()
    siguiente = 0
    for bone_id, splines in bones:
        offset = len(tiempos)
        for opcode, frames, bloques in splines:
            assert len(frames) == len(bloques)
            registro = struct.pack("<HHi", opcode, len(frames), siguiente)
            registro += struct.pack("<%dH" % len(frames), *frames)
            relleno = (-(len(tiempos) + len(registro))) % 4
            registro += bytes([pad_byte]) * relleno
            tiempos += registro
            datos += b"".join(bloques)
            siguiente += len(frames)
        empaquetado = ((len(splines) & 0xF) | ((bone_id & 0x3FF) << 4)
                       | ((offset & 0x3FFFF) << 14))
        info += struct.pack("<I", empaquetado)
    cabecera = struct.pack("<I4sIf", g2a.MAGIC, version, 0, fps)
    cabecera += struct.pack("<4I", seconds_frames | (len(info) << 18), len(tiempos),
                            siguiente, reserved)
    cuerpo = cabecera + info + tiempos + datos
    return cuerpo[:8] + struct.pack("<I", len(cuerpo)) + cuerpo[12:]


def animacion_de_prueba() -> bytes:
    """Tres huesos con 1, 2 y 3 claves: cubre los tres rellenos (12/12/16 B)."""
    bones = [
        (1, [(0, [0], [bloque(fila(z=1))]),
             (1, [0], [bloque(fila(y=7))]),
             (2, [0], [bloque(fila(x=1, y=1, z=1))])]),
        (2, [(0, [0, 5], [bloque(fila(z=2)), bloque(fila(z=-2))]),
             (1, [0, 4], [bloque(fila(x=3)), bloque(fila(x=-3))]),
             (2, [0, 2, 4], [bloque(fila(x=1)), bloque(fila(x=2)),
                             bloque(fila(x=1))])]),
        (300, [(0, [0], [bloque(fila(y=-1))]),
               (1, [0], [bloque(fila(z=4))]),
               (2, [0], [bloque(fila(x=1, y=1, z=1))])]),
    ]
    return construir(bones, seconds_frames=12)


# ---------------------------------------------------------------------------
# Cabecera y estructura
# ---------------------------------------------------------------------------

def test_magic_en_disco_es_a2g():
    datos = animacion_de_prueba()
    assert datos[:4] == b"_A2G"
    assert struct.unpack_from("<I", datos, 0)[0] == 0x4732415F
    # la cadena canonica NO esta en el fichero: la trampa de fin de letra
    assert b"G2A_" not in datos


def test_cabecera_campo_a_campo():
    datos = animacion_de_prueba()
    cab = anim.peek(datos)
    assert cab.version == b"0400"
    assert cab.file_size == len(datos)
    assert cab.frame_rate == pytest.approx(60.0)
    assert cab.length_frames == 12
    assert cab.bone_count == 3
    assert cab.reserved == 0
    # la geometria que cierra el formato
    assert (0x20 + cab.bone_section_size + cab.timing_size
            + cab.key_block_count * 32) == len(datos)


def test_parse_estructura():
    a = anim.parse(animacion_de_prueba())
    assert a.bone_count == 3
    assert [b.bone_id for b in a.bones] == [1, 2, 300]
    assert a.spline_count == 9
    assert a.channels == {"rotation": 3, "scale": 3, "translation": 3}
    rot = a.bones[1].splines[0]
    assert rot.opcode == 0 and rot.channel == "rotation"
    assert rot.timings == (0, 5)
    assert rot.keyframe_count == 2
    assert a.keyframe_count == 13   # 3 + 7 + 3 claves
    assert a.pad_bytes == {}


def test_bone_ids_dan_la_vuelta_a_los_1024():
    """Cuando el boneID baja, es la vuelta siguiente: 5 -> 1030, no 5 otra vez."""
    bones = [(5, [(0, [0], [bloque(fila())])]),
             (4, [(0, [0], [bloque(fila())])]),
             (300, [(0, [0], [bloque(fila())])])]
    a = anim.parse(construir(bones))
    assert [b.bone_id for b in a.bones] == [5, 1028, 1324]
    assert [b.bone_id_raw for b in a.bones] == [5, 4, 300]


# ---------------------------------------------------------------------------
# La fila de 64 bits
# ---------------------------------------------------------------------------

def test_fila_decimal_a_campos():
    row = g2a.Row.from_int(fila(x=1, y=-2, z=3, exp=14))
    assert (row.x, row.y, row.z, row.exp) == (1, -2, 3, 14)
    assert row.scale == pytest.approx(0.5)          # 2**(14-15)
    assert row.vector == pytest.approx((0.5, -1.0, 1.5))


def test_fila_admite_el_fondo_del_rango():
    row = g2a.Row.from_int(fila(x=-0x80000, y=0x7FFFF, z=-1, exp=0))
    assert row.x == -0x80000 and row.y == 0x7FFFF and row.z == -1


def test_encode_component_ida_y_vuelta():
    """El campo es entero: el error nunca pasa de medio paso de su escala."""
    for exp in (0, 5, 10, 15):
        escala = 2.0 ** (exp - 15)
        for valor in (0.0, 1.0, -1.0, 0.25):
            campo = g2a.encode_component(valor, exp)
            assert abs(campo - valor / escala) <= 0.5


def test_encode_component_avisa_si_no_cabe():
    with pytest.raises(anim.AnimError):
        g2a.encode_component(1e9, 0)


def test_cuaternion_normalizado():
    for vector in ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.3, -2.1, 0.7)):
        x, y, z, w = anim.axis_angle_to_quaternion(vector)
        assert (x * x + y * y + z * z + w * w) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Ida y vuelta
# ---------------------------------------------------------------------------

def test_roundtrip_byte_a_byte():
    datos = animacion_de_prueba()
    a, reescrito = anim.roundtrip(datos)
    assert reescrito == datos
    assert hashlib.sha256(reescrito).hexdigest() == hashlib.sha256(datos).hexdigest()


def test_roundtrip_con_relleno_no_cero():
    """El relleno de los registros se reescribe a cero: el parser lo delata."""
    bones = [(1, [(0, [0], [bloque(fila())]), (1, [0], [bloque(fila())])])]
    datos = construir(bones, pad_byte=0xAA)
    a = anim.parse(datos)
    assert a.pad_bytes and all(v == b"\xaa" * len(v) for v in a.pad_bytes.values())
    assert anim.build(a) != datos


def test_json_ida_y_vuelta():
    datos = animacion_de_prueba()
    doc = anim.to_json(anim.parse(datos), name="0xprueba", size=len(datos),
                       sha256=hashlib.sha256(datos).hexdigest())
    assert doc["format"] == "G2A" and doc["version"] == "0400"
    reescrito = anim.build(anim.from_json(doc))
    assert reescrito == datos


def test_json_conserva_el_frame_rate_exacto():
    datos = construir([(1, [(0, [0], [bloque(fila())])])], fps=29.97)
    a = anim.parse(datos)
    doc = json.loads(json.dumps(anim.to_json(a)))
    assert anim.build(anim.from_json(doc)) == datos


# ---------------------------------------------------------------------------
# Exportacion legible
# ---------------------------------------------------------------------------

def test_csv_horneado():
    a = anim.parse(animacion_de_prueba())
    filas = list(anim.csv_rows(a))
    assert len(filas) == sum(len(list(anim.serial.timeline(s, a.length_frames)))
                             and sum(fin - ini for ini, fin, _ in
                                     anim.serial.timeline(s, a.length_frames))
                             for b in a.bones for s in b.splines)
    canales = {f[1] for f in filas}
    assert canales == {"rotation", "translation", "scale"}
    # la rotacion sale como cuaternion y los otros como vector
    rotacion = next(f for f in filas if f[1] == "rotation")
    traslacion = next(f for f in filas if f[1] == "translation")
    assert rotacion[7] is not None and traslacion[7] is None


def test_csv_escribe_cabecera(tmp_path):
    ruta = tmp_path / "anim.csv"
    filas = anim.write_csv(anim.parse(animacion_de_prueba()), str(ruta))
    texto = ruta.read_text(encoding="utf-8").splitlines()
    assert texto[0] == ",".join(anim.CSV_HEADER)
    assert len(texto) == filas + 1


# ---------------------------------------------------------------------------
# Modificar un valor
# ---------------------------------------------------------------------------

def test_cambiar_un_valor_solo_toca_su_campo():
    datos = animacion_de_prueba()
    a = anim.parse(datos)
    parte = anim.set_keyframe_value(a, bone_id=1, channel="translation",
                                    frame=0, axis="y", value=4.0)
    assert parte["before"] == pytest.approx(7.0)
    assert parte["after"] == pytest.approx(4.0)
    reescrito = anim.build(a)
    assert len(reescrito) == len(datos)
    # solo cambia el campo de `y` del primer bloque del hueso 1
    distintos = [i for i, (x, y) in enumerate(zip(datos, reescrito)) if x != y]
    assert 0 < len(distintos) <= 3
    b = anim.parse(reescrito)
    fila_nueva = b.bones[0].splines[1].keys[0].rows[0]
    assert fila_nueva.vector == pytest.approx((0.0, 4.0, 0.0), abs=1e-6)
    # y el resto de componentes del hueso no se mueve
    assert b.bones[0].splines[2].keys[0] == a.bones[0].splines[2].keys[0]
    assert b.keyframe_count == a.keyframe_count


def test_cambiar_un_valor_falla_si_no_hay_clave():
    a = anim.parse(animacion_de_prueba())
    with pytest.raises(anim.AnimError):
        anim.set_keyframe_value(a, bone_id=1, channel="translation", frame=3,
                                axis="y", value=1.0)


def test_cambiar_un_valor_falla_si_el_hueso_no_existe():
    a = anim.parse(animacion_de_prueba())
    with pytest.raises(anim.AnimError):
        anim.set_keyframe_value(a, bone_id=99, channel="rotation", frame=0,
                                axis="x", value=1.0)


# ---------------------------------------------------------------------------
# Errores: lo que NO se debe tragar
# ---------------------------------------------------------------------------

def test_g1a_se_rechaza_con_su_nombre():
    """En disco los magics van al reves: `G1A_` (u32 0x4731415f) son `_A1G`."""
    datos = b"_A1G" + b"2400" + b"\x00" * 24
    with pytest.raises(anim.AnimFormatError) as excinfo:
        anim.parse(datos + b"\x00" * 8)
    assert "G1A_" in str(excinfo.value)


def test_tamano_que_no_cuadra_se_rechaza():
    datos = animacion_de_prueba()
    with pytest.raises(anim.AnimFormatError):
        anim.parse(datos + b"\x00")


def test_version_desconocida_se_rechaza():
    datos = construir([(1, [(0, [0], [bloque(fila())])])], version=b"0500")
    with pytest.raises(anim.AnimFormatError) as excinfo:
        anim.parse(datos)
    assert "version" in str(excinfo.value)


def test_cabecera_cortada_se_rechaza():
    with pytest.raises(anim.AnimFormatError):
        anim.parse(b"_A2G")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _escribir(datos: bytes, tmp_path, nombre: str = "0xprueba.g1a") -> str:
    ruta = tmp_path / nombre
    ruta.write_bytes(datos)
    return str(ruta)


def test_cli_list_de_una_carpeta(tmp_path, capsys):
    _escribir(animacion_de_prueba(), tmp_path)
    assert main(["anim", "list", str(tmp_path), "--deep"]) == 0
    salida = capsys.readouterr().out
    assert "1 animaciones" in salida
    assert "0xprueba" in salida


def test_cli_info(tmp_path, capsys):
    ruta = _escribir(animacion_de_prueba(), tmp_path)
    assert main(["anim", "info", ruta]) == 0
    salida = capsys.readouterr().out
    assert "IDENTICA" in salida
    assert "0x20 + 12" in salida or "geometria" in salida


def test_cli_export_json_y_build(tmp_path, capsys):
    ruta = _escribir(animacion_de_prueba(), tmp_path)
    doc = str(tmp_path / "a.json")
    out = str(tmp_path / "b.g1a")
    assert main(["anim", "export", ruta, "--out", doc]) == 0
    assert main(["anim", "build", doc, "--out", out]) == 0
    assert open(out, "rb").read() == open(ruta, "rb").read()
    assert "IDENTICO" in capsys.readouterr().out


def test_cli_export_csv(tmp_path):
    ruta = _escribir(animacion_de_prueba(), tmp_path)
    csv = str(tmp_path / "a.csv")
    assert main(["anim", "export", ruta, "--out", csv]) == 0
    assert os.path.getsize(csv) > 0
    assert open(csv, encoding="utf-8").readline().startswith("bone_id")


def test_cli_roundtrip(tmp_path, capsys):
    ruta = _escribir(animacion_de_prueba(), tmp_path)
    assert main(["anim", "roundtrip", ruta]) == 0
    assert "IDENTICO byte a byte" in capsys.readouterr().out


def test_cli_set(tmp_path, capsys):
    ruta = _escribir(animacion_de_prueba(), tmp_path)
    out = str(tmp_path / "mod.g1a")
    assert main(["anim", "set", ruta, "--bone", "1", "--channel", "translation",
                 "--frame", "0", "--axis", "y", "--value", "3", "--out", out]) == 0
    assert os.path.getsize(out) == os.path.getsize(ruta)
    salida = capsys.readouterr().out
    assert "leido de vuelta 3" in salida
    nuevo = anim.parse(open(out, "rb").read())
    assert nuevo.bones[0].splines[1].keys[0].rows[0].vector[1] == pytest.approx(3.0)


def test_cli_set_no_escribe_en_el_romfs(tmp_path, monkeypatch, capsys):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    ruta = romfs / "0xprueba.g1a"
    ruta.write_bytes(animacion_de_prueba())
    monkeypatch.setenv("PKP_ROMFS", str(romfs))
    codigo = main(["anim", "set", str(ruta), "--bone", "1", "--channel",
                   "translation", "--frame", "0", "--axis", "y", "--value", "1",
                   "--out", str(ruta)])
    assert codigo == 2
    assert "protegido" in capsys.readouterr().err


def test_cli_ruta_inexistente(capsys):
    assert main(["anim", "info", "no-existe.g1a"]) == 1
    assert "no existe" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Contra el dump real (se saltan con motivo si no esta)
# ---------------------------------------------------------------------------

def _fdata_con_animaciones() -> str:
    raiz = os.path.join(ROMFS, "motor_asset_re")
    for ruta in fdata.find_fdata(raiz) if os.path.isdir(raiz) else []:
        for entry in fdata.iter_entries(ruta):
            if entry.type_ktid == G1A:
                return ruta
    return ""


FDATA = _fdata_con_animaciones()
sin_dump = pytest.mark.skipif(not FDATA,
                              reason="necesita el dump (PKP_ROMFS con los .fdata)")


@sin_dump
def test_dump_cabeceras_de_las_17457():
    from pokopia.anim import source

    total = 0
    g2a_ok = 0
    for entry in source.iter_fdata_entries(FDATA):
        total += 1
        datos = source.read_entry(FDATA, entry, limit=0x20)
        try:
            cab = anim.peek(datos)
        except anim.AnimError:
            continue
        assert cab.magic == g2a.MAGIC
        assert cab.version == b"0400"
        assert cab.file_size == entry.uncompressed_size
        g2a_ok += 1
    assert total == 17457
    assert g2a_ok == 17428


@sin_dump
def test_dump_roundtrip_de_una_muestra():
    from pokopia.anim import source

    entry = next(e for e in source.iter_fdata_entries(FDATA)
                 if e.uncompressed_size == 40252)
    datos = source.read_entry(FDATA, entry)
    a, reescrito = anim.roundtrip(datos)
    assert reescrito == datos
    assert hashlib.sha256(reescrito).hexdigest() == (
        "5ccea9296e058d818ba59e5701c30a6df1bbaaacc8c5f28956d6827459efb72f")
    assert a.frame_rate == pytest.approx(60.0)
    assert a.length_frames == 141
    assert a.bone_count == 46

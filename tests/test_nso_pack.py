"""Pruebas de `tools/nso_pack.py` que no necesitan el dump.

Lo que se prueba es lo que puede dar un falso positivo si esta roto:

* el compresor LZ4 (si emite un bloque invalido, el `main` no arranca y el error
  aparece lejos de aqui);
* la composicion de la cabecera NSO0 (offsets, tamanos empaquetados, sha256);
* las tres comprobaciones, incluidas las que tienen que **fallar** cuando el
  fichero no es el que dice ser.

El modulo es un script de `tools/`, asi que se carga por ruta.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import random
import struct

import pytest

RUTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "nso_pack.py")

if not os.path.isfile(RUTA):
    pytest.skip("tools/ no viaja en la release: nso_pack no esta en este arbol",
                allow_module_level=True)


def _cargar():
    spec = importlib.util.spec_from_file_location("nso_pack", RUTA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


nso_pack = _cargar()
nso_dump = nso_pack._nso_dump()

NOP = b"\x1f\x20\x03\xd5"
B_LT = b"\x6b\x19\x00\x54"  # b.lt #0x... como aparece en el parche h4


# --------------------------------------------------------------------------- LZ4


@pytest.mark.parametrize("datos", [
    b"",
    b"a",
    b"abc",
    b"x" * 12,
    b"x" * 13,
    b"abcabcabcabcabcabcabcabc",
    bytes(range(256)) * 4,
    b"\x00" * 70000,                          # un solo match larguisimo
    b"patron" * 4000,                         # solapamientos de periodo 6
])
def test_lz4_ida_y_vuelta(datos):
    comprimido = nso_pack.lz4_block_compress(datos)
    assert nso_dump.lz4_block_decompress(comprimido, len(datos)) == datos


def test_lz4_ida_y_vuelta_con_texto_azaroso():
    r = random.Random(20261109)
    datos = bytes(r.randrange(256) for _ in range(120000))
    comprimido = nso_pack.lz4_block_compress(datos)
    assert nso_dump.lz4_block_decompress(comprimido, len(datos)) == datos


def test_lz4_respeta_las_dos_reglas_del_formato():
    """Ni el ultimo match empieza en los ultimos 12 B, ni el bloque acaba sin 5 literales."""
    datos = b"abcabcabc" * 10
    comprimido = nso_pack.lz4_block_compress(datos)
    # decodificar a mano contando donde acaba el ultimo match
    i, salida, ultimo_match_fin = 0, 0, 0
    while i < len(comprimido):
        token = comprimido[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = comprimido[i]
                i += 1
                lit += b
                if b != 255:
                    break
        i += lit
        salida += lit
        if i >= len(comprimido):
            break
        i += 2
        mlen = token & 0xF
        if mlen == 15:
            while True:
                b = comprimido[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4
        salida += mlen
        ultimo_match_fin = salida
    assert len(datos) - ultimo_match_fin >= 5


def test_lz4_de_datos_incompresibles_no_crece_de_mas():
    r = random.Random(7)
    datos = bytes(r.randrange(256) for _ in range(5000))
    comprimido = nso_pack.lz4_block_compress(datos)
    assert len(comprimido) <= len(datos) + len(datos) // 255 + 16


# --------------------------------------------------------------------------- NSO sintetico


def _sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def construir_nso(texto: bytes, rodata: bytes, data: bytes) -> bytes:
    """NSO0 minimo y valido para `nso_pack`: comprimido y con sha256 en la cabecera."""
    cab = bytearray(0x100)
    cab[0:4] = b"NSO0"
    struct.pack_into("<I", cab, 4, 0)           # version
    struct.pack_into("<I", cab, 0x0C, 0x3F)     # comprimido + hasheados, los tres
    cab[0x40:0x60] = bytes(range(32))           # build id
    segmentos = [("text", texto, 0), ("rodata", rodata, 0x1000), ("data", data, 0x2000)]
    partes = []
    pos = 0x100
    for i, (nombre, datos, base) in enumerate(segmentos):
        empaq = nso_pack.lz4_block_compress(datos)
        struct.pack_into("<IIII", cab, 0x10 + 0x10 * i, pos, base, len(datos), 0x100)
        struct.pack_into("<I", cab, 0x60 + 4 * i, len(empaq))
        cab[0xA0 + 0x20 * i:0xC0 + 0x20 * i] = _sha(datos)
        partes.append(empaq)
        pos += len(empaq)
    return bytes(cab) + b"".join(partes)


def esqueleto() -> tuple[bytes, dict, dict, list[dict]]:
    texto = bytearray(b"\x00\x00\x00\x14" * 64)   # relleno con palabras cualquiera
    texto[0x40:0x44] = NOP
    texto[0x80:0x84] = B_LT
    texto[0x84:0x88] = b"\x1f\x09\x00\x71"        # cmp w8, #2 (no se toca)
    rodata = b"FPS     %2.2f(%4.2f)\n" * 3
    data = bytes(range(64))
    original = construir_nso(bytes(texto), rodata, data)
    ediciones = [
        {"segmento": "text", "offset": 0x80, "esperado": B_LT, "nuevo": NOP, "motivo": "test"},
        {"segmento": "text", "offset": 0x40, "esperado": NOP, "nuevo": b"\x1f\x20\x03\xd5",
         "motivo": "test: reescribir nop por nop no cambia nada"},
    ]
    cabecera, segmentos = nso_pack.descomponer(nso_dump, original)
    return original, cabecera, segmentos, ediciones


def test_componer_y_verificar_las_tres(tmp_path):
    original, cabecera, segmentos, ediciones = esqueleto()
    parcheados = nso_pack.aplicar_ediciones(segmentos, ediciones)
    nuevo, info = nso_pack.recomponer(nso_dump, original, cabecera, parcheados)
    destino = tmp_path / "main"
    destino.write_bytes(nuevo)

    a = nso_pack.comprobar_a(nso_dump, str(destino))
    assert a["ok"], a
    assert [s["name"] for s in a["segmentos"]] == ["text", "rodata", "data"]
    assert a["build_id"] == bytes(range(32)).hex()

    b = nso_pack.comprobar_b(segmentos, parcheados, ediciones)
    assert b["ok"], b
    assert b["cuenta"] == 4   # solo los 4 B del b.lt; el 0x40 se reescribe igual

    assert nso_pack.comprobar_c(parcheados, ediciones, imprimir=lambda *_: None)["ok"]


def test_la_cabecera_apunta_a_los_segmentos_nuevos(tmp_path):
    original, cabecera, segmentos, ediciones = esqueleto()
    parcheados = nso_pack.aplicar_ediciones(segmentos, ediciones)
    nuevo, info = nso_pack.recomponer(nso_dump, original, cabecera, parcheados)
    cab = nso_dump.read_header(nuevo[:0x100])
    for s, esperado in zip(cab["segments"], info["segmentos"]):
        assert s["file_offset"] == esperado["file_offset"]
        assert s["packed_size"] == esperado["packed_size"]
        assert s["sha256_in_header"] == esperado["sha256"]
    assert info["tamano"] == len(nuevo)


def test_comprobar_b_detecta_un_byte_fuera_del_parche():
    original, cabecera, segmentos, ediciones = esqueleto()
    parcheados = nso_pack.aplicar_ediciones(segmentos, ediciones)
    parcheados["data"] = parcheados["data"][:-1] + bytes([parcheados["data"][-1] ^ 0xFF])
    b = nso_pack.comprobar_b(segmentos, parcheados, ediciones)
    assert not b["ok"]
    assert b["fuera_del_parche"] == ["data+0x3f"]


def test_comprobar_a_detecta_una_cabecera_mentirosa(tmp_path):
    original, cabecera, segmentos, ediciones = esqueleto()
    parcheados = nso_pack.aplicar_ediciones(segmentos, ediciones)
    nuevo, _info = nso_pack.recomponer(nso_dump, original, cabecera, parcheados)
    roto = bytearray(nuevo)
    roto[0xA0] ^= 0xFF   # sha256 del text en la cabecera, cambiado
    destino = tmp_path / "main"
    destino.write_bytes(bytes(roto))
    a = nso_pack.comprobar_a(nso_dump, str(destino))
    assert not a["ok"]
    assert a["segmentos"][0]["ok"] is False


def test_aplicar_ediciones_rechaza_bytes_que_no_cuadran():
    _original, _cabecera, segmentos, _ediciones = esqueleto()
    malas = [{"segmento": "text", "offset": 0x80, "esperado": b"\x00" * 4, "nuevo": NOP,
              "motivo": "test"}]
    with pytest.raises(nso_pack.NsoPackError) as exc:
        nso_pack.aplicar_ediciones(segmentos, malas)
    assert exc.value.exit_code == 4


def test_aplicar_ediciones_rechaza_salirse_del_segmento():
    _original, _cabecera, segmentos, _ediciones = esqueleto()
    malas = [{"segmento": "text", "offset": len(segmentos["text"]) - 2,
              "esperado": b"\x00" * 4, "nuevo": NOP, "motivo": "test"}]
    with pytest.raises(nso_pack.NsoPackError) as exc:
        nso_pack.aplicar_ediciones(segmentos, malas)
    assert exc.value.exit_code == 4


def test_no_se_escribe_dentro_de_la_carpeta_del_original(tmp_path):
    original, _cabecera, _segmentos, _ediciones = esqueleto()
    fuente = tmp_path / "ExeFS"
    fuente.mkdir()
    (fuente / "main").write_bytes(original)
    codigo = nso_pack.main(["escribir", "--nso", str(fuente / "main"),
                            "--out", str(fuente),
                            "--edicion", "0x80:6b190054:1f2003d5"])
    assert codigo == 2
    assert (fuente / "main").read_bytes() == original


def test_identidad_del_parche_se_coteja(tmp_path):
    original, _cabecera, _segmentos, _ediciones = esqueleto()
    fuente = tmp_path / "ExeFS"
    fuente.mkdir()
    (fuente / "main").write_bytes(original)
    parche = tmp_path / "p.parche.json"
    parche.write_text('{"juego": {"sha256": "%s"}, "ediciones": [{"segmento": "text", '
                      '"offset": "0x80", "esperado": "6b190054", "nuevo": "1f2003d5", '
                      '"motivo": "test"}]}' % ("0" * 64), encoding="utf-8")
    codigo = nso_pack.main(["escribir", "--nso", str(fuente / "main"),
                            "--out", str(tmp_path / "out"), "--espec", str(parche)])
    assert codigo == 3
    assert not (tmp_path / "out" / "main").exists()


def test_es_idempotente(tmp_path):
    original, cabecera, segmentos, ediciones = esqueleto()
    parcheados = nso_pack.aplicar_ediciones(segmentos, ediciones)
    uno, _ = nso_pack.recomponer(nso_dump, original, cabecera, parcheados)
    otro, _ = nso_pack.recomponer(nso_dump, original, cabecera, parcheados)
    assert uno == otro


# --------------------------------------------------------------------------- desensamblado


def test_describir_instruccion_nop_y_b_cond():
    assert nso_pack.describir_instruccion(0xD503201F) == "nop"
    assert nso_pack.describir_instruccion(0x5400196B).startswith("b.lt #")
    assert nso_pack.describir_instruccion(0x7100091F) == "7100091f"


def test_ventana_desensamblada_marca_el_offset():
    texto = b"\x1f\x20\x03\xd5" * 6
    lineas = nso_pack.ventana_desensamblada(texto, 8, antes=1, despues=1)
    assert len(lineas) == 3
    assert lineas[1].startswith(">> 00000008")
    assert lineas[1].endswith("nop")

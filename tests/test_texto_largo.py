"""Pruebas del esquema de texto con punteros (`pool`) y de su herramienta.

Las del esquema y los tres modos de escritura van sobre payloads sintéticos
(construidos aquí, con texto propio): no necesitan el dump. Las que usan el
contenedor real se saltan solas si no hay `PKP_ROMFS`.
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from pokopia import paths
from pokopia.tables import idioma, textpool
from tests import helpers

ROMFS = paths.configured_romfs()
HAY_DUMP = os.path.isfile(os.path.join(ROMFS, paths.IDX_NAME))
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego (exporta PKP_ROMFS)")

TEXTOS = [
    b"primera linea de prueba",
    b"",
    b"<br><$tag(1,2)>tercera linea con marcado",
    b"",
    b"quinta",
]


def pool_payload(textos=TEXTOS, version: int = 2, hueco: int = 0, cola: int = 0) -> bytes:
    """Payload con el esquema medido: cabecera 64 B, registros de 8 B y pool.

    `a[fila] = inicio + 8*(count-fila)`, que es la convencion del juego.
    `hueco` mete bytes de relleno entre cadenas (para probar el rechazo) y
    `cola` bytes al final del pool.
    """
    textos = [t if isinstance(t, bytes) else t.encode("utf-8") for t in textos]
    count = len(textos)
    pool = textos[0] + b"\x00" + b"\x00" * hueco + b"".join(t + b"\x00" for t in textos[1:])
    pool += b"\x00" * cola
    buf = bytearray(64 + count * 8)
    struct.pack_into("<II", buf, 0, count, version)
    inicio = 0
    for fila, texto in enumerate(textos):
        struct.pack_into("<II", buf, 64 + fila * 8, inicio + 8 * (count - fila), 0)
        inicio += len(texto) + 1 + (hueco if fila == 0 else 0)
    return bytes(buf) + pool


# --- esquema ---------------------------------------------------------------

def test_parse_lee_geometria():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    assert tabla.count == len(TEXTOS)
    assert tabla.version == 2
    assert tabla.pool_start == 64 + len(TEXTOS) * 8


def test_starts_y_slots():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    starts = tabla.starts(blob)
    assert starts[0] == 0
    assert tabla.slots(blob) == TEXTOS
    assert tabla.textos(blob)[0] == TEXTOS[0].decode()


def test_offsets_guardados_no_son_directos():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    crudos = tabla.raw_offsets(blob)
    assert crudos[0] == 8 * len(TEXTOS)          # el primer `a` no es 0
    assert crudos != tabla.starts(blob)


def test_es_tabla_acepta_el_esquema():
    assert textpool.es_tabla(pool_payload()) is not None


def test_es_tabla_rechaza_version_distinta():
    assert textpool.es_tabla(pool_payload(version=3)) is None


def test_es_tabla_rechaza_hueco_entre_cadenas():
    assert textpool.es_tabla(pool_payload(hueco=2)) is None


def test_es_tabla_rechaza_cola_larga():
    assert textpool.es_tabla(pool_payload(cola=64)) is None


def test_es_tabla_rechaza_registros_de_32_bytes():
    """Una tabla con registros de 32 B y pool detrás no es este esquema."""
    count = 4
    registros = bytearray(64 + count * 32)
    struct.pack_into("<II", registros, 0, count, 2)
    for fila in range(count):
        struct.pack_into("<I", registros, 64 + fila * 32, 96032 - 7 * fila)
    pool = b"".join(b"descripcion %d con texto suficiente para pasar el 10%%" % i + b"\x00"
                    for i in range(count))
    assert textpool.es_tabla(bytes(registros) + pool) is None


def test_validar_limpio():
    blob = pool_payload()
    assert textpool.validar(textpool.parse(7, blob), blob) == []


def test_validar_detecta_count_cambiado():
    tabla = textpool.parse(7, pool_payload())
    blob = bytearray(pool_payload())
    struct.pack_into("<I", blob, 0, 99)
    problemas = textpool.validar(tabla, bytes(blob))
    assert any("count del header" in p for p in problemas)


# --- sustitucion -----------------------------------------------------------

def test_sustituir_igual_no_mueve_nada_salvo_el_texto():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    viejo = tabla.slots(blob)[2]
    prefijo = b"<br><$tag(1,2)>"
    texto = prefijo + b"x" * (len(viejo) - len(prefijo))   # misma longitud exacta
    nuevo = textpool.sustituir(tabla, blob, 2, texto, modo="igual")
    assert len(nuevo) == len(blob)
    assert textpool.parse(7, nuevo).raw_offsets(nuevo) == tabla.raw_offsets(blob)
    slots = textpool.parse(7, nuevo).slots(nuevo)
    assert slots[2] == texto
    assert [s for i, s in enumerate(slots) if i != 2] == [s for i, s in enumerate(TEXTOS) if i != 2]


def test_sustituir_igual_exige_misma_longitud():
    tabla = textpool.parse(7, pool_payload())
    with pytest.raises(textpool.PoolError):
        textpool.sustituir(tabla, pool_payload(), 0, b"corta", modo="igual")


def test_sustituir_relleno_mantiene_tamano_y_offsets():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    viejo = tabla.slots(blob)[0]
    nuevo_texto = b"frase propia"
    nuevo = textpool.sustituir(tabla, blob, 0, nuevo_texto, modo="relleno")
    assert len(nuevo) == len(blob)
    tabla2 = textpool.parse(7, nuevo)
    assert tabla2.raw_offsets(nuevo) == tabla.raw_offsets(blob)
    assert tabla2.slots(nuevo)[0] == nuevo_texto
    # el relleno son NUL: al releer, el slot mide lo que medía
    assert tabla2.ends(nuevo)[0] - tabla2.starts(nuevo)[0] == len(nuevo_texto)
    assert len(viejo) > len(nuevo_texto)


def test_sustituir_ajuste_rebaja_los_punteros_posteriores():
    blob = pool_payload()
    tabla = textpool.parse(7, blob)
    antes = tabla.raw_offsets(blob)
    texto = b"x"
    delta = len(tabla.slots(blob)[0]) - len(texto)
    nuevo = textpool.sustituir(tabla, blob, 0, texto, modo="ajuste")
    assert len(nuevo) == len(blob) - delta
    tabla2 = textpool.parse(7, nuevo)
    despues = tabla2.raw_offsets(nuevo)
    assert despues[0] == antes[0]
    assert despues[1:] == [a - delta for a in antes[1:]]
    assert tabla2.slots(nuevo)[0] == texto
    assert tabla2.slots(nuevo)[1:] == tabla.slots(blob)[1:]
    assert textpool.validar(tabla2, nuevo) == []


def test_sustituir_ajuste_no_admite_texto_mas_largo():
    tabla = textpool.parse(7, pool_payload())
    with pytest.raises(textpool.PoolError):
        textpool.sustituir(tabla, pool_payload(), 0, b"z" * 200, modo="ajuste")


def test_sustituir_rechaza_nul_y_fila_fuera_de_rango():
    tabla = textpool.parse(7, pool_payload())
    with pytest.raises(textpool.PoolError):
        textpool.sustituir(tabla, pool_payload(), 0, b"a\x00b", modo="relleno")
    with pytest.raises(textpool.PoolError):
        textpool.sustituir(tabla, pool_payload(), 99, b"a", modo="relleno")


def test_sustituir_rechaza_texto_no_utf8():
    tabla = textpool.parse(7, pool_payload())
    with pytest.raises(UnicodeDecodeError):
        textpool.sustituir(tabla, pool_payload(), 0, b"\xff\xfe", modo="ajuste")


# --- idioma ----------------------------------------------------------------

FRASES = {
    "es": "La casa está al lado del río y no hay nadie en la puerta, pero me parece que "
          "el perro quiere salir a jugar con nosotros esta tarde.",
    "en": "The house is next to the river and there is nobody at the door, but it seems "
          "that the dog wants to go out and play with us this afternoon.",
    "de": "Das Haus ist neben dem Fluss und es ist niemand an der Tür, aber der Hund "
          "möchte heute Nachmittag mit uns spielen und nicht hier bleiben.",
    "fr": "La maison est à côté de la rivière et il n'y a personne à la porte, mais le "
          "chien veut sortir jouer avec nous cet après-midi dans le jardin.",
    "it": "La casa è accanto al fiume e non c'è nessuno alla porta, ma il cane vuole "
          "uscire a giocare con noi questo pomeriggio nel giardino.",
    "jp": "この家は川のとなりにあります。だれもいませんが、犬は今日の午後にいっしょに"
          "あそびたいようです。",
    "kr": "이 집은 강 옆에 있고 문 앞에는 아무도 없지만 강아지는 오늘 오후에 우리와 "
          "함께 놀고 싶어 합니다.",
    "zh-CN": "这座房子在河边，门口没有人，但是那只小狗今天下午想和我们一起玩，它已经等"
             "了很久了。",
    "zh-TW": "這座房子在河邊，門口沒有人，但是那隻小狗今天下午想和我們一起玩，牠已經等"
             "了很久了。",
}


@pytest.mark.parametrize("esperado", sorted(FRASES))
def test_detectar_idioma(esperado):
    veredicto = idioma.detectar(FRASES[esperado])
    assert veredicto["idioma"] == esperado, veredicto


def test_detectar_ignora_el_marcado():
    a = idioma.detectar(FRASES["es"])["idioma"]
    b = idioma.detectar("<$motion(1,803)><br>" + FRASES["es"])["idioma"]
    assert a == b == "es"


def test_consenso():
    votos = [idioma.detectar(FRASES["es"]) for _ in range(4)]
    votos.append(idioma.detectar(FRASES["en"]))
    resumen = idioma.consenso(votos)
    assert resumen["idioma"] == "es"
    assert resumen["votos"] == 4
    assert resumen["total"] == 5


# --- CLI -------------------------------------------------------------------

def _cli(*argv):
    pytest.importorskip("tools.texto_largo",
                        reason="tools/ no viaja en la release: el censo vive en tools/")
    from tools import texto_largo
    return texto_largo.main(list(argv))


def test_cli_censo_idioma_y_extraer(tmp_path):
    container = helpers.make_container(str(tmp_path / "rom"), {9: pool_payload()}, entries=10)
    salida = tmp_path / "censo.tsv"
    assert _cli("censo", "--container", container.dir, "--out", str(salida)) == 0
    texto = salida.read_text(encoding="utf-8").splitlines()
    assert texto[0].split("\t")[:2] == ["idx", "size"]
    assert len(texto) == 2                     # una tabla
    assert texto[1].split("\t")[0] == "9"

    assert _cli("idioma", "--container", container.dir, "--entrada", "9",
                "--muestras", "2", "--largo-min", "1") == 0

    volcado = tmp_path / "tabla.jsonl"
    assert _cli("extraer", "--container", container.dir, "--entrada", "9",
                "--salida", str(volcado)) == 0
    filas = [json.loads(linea) for linea in volcado.read_text(encoding="utf-8").splitlines()]
    assert [f["texto"] for f in filas] == [t.decode() for t in TEXTOS]


def test_cli_sustituir_escribe_contenedor_legible(tmp_path):
    container = helpers.make_container(str(tmp_path / "rom"), {9: pool_payload()}, entries=10)
    out = tmp_path / "mod"
    assert _cli("sustituir", "--container", container.dir, "--entrada", "9", "--fila", "0",
                "--texto", "texto nuevo", "--modo", "ajuste", "--out", str(out)) == 0
    from pokopia.container import read_index, read_file, unpack_entry
    idx = read_index(str(out / paths.IDX_NAME))
    binp = read_file(str(out / paths.BIN_NAME))
    assert len(idx) == 10
    blob = unpack_entry(binp, idx[9], 9)
    tabla = textpool.parse(9, blob)
    assert tabla.slots(blob)[0] == b"texto nuevo"
    assert len(blob) == len(pool_payload()) - (len(TEXTOS[0]) - len(b"texto nuevo"))


def test_cli_sustituir_no_escribe_en_el_romfs(tmp_path, monkeypatch):
    container = helpers.make_container(str(tmp_path / "rom"), {9: pool_payload()}, entries=10)
    monkeypatch.setenv("PKP_ROMFS", container.dir)
    antes = paths.md5_file(container.bin)
    codigo = _cli("sustituir", "--container", container.dir, "--entrada", "9", "--fila", "0",
                  "--texto", "x", "--modo", "ajuste", "--out", container.dir)
    assert codigo == 1                                    # guard_writable lo impide
    assert paths.md5_file(container.bin) == antes         # el contenedor no se toca


def test_cli_romfs_cuenta_extensiones(tmp_path):
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    (romfs / "nota.txt").write_text("hola", encoding="utf-8")
    (romfs / "otra.msbt").write_bytes(b"MsgStdBn")
    assert _cli("romfs", "--romfs", str(romfs)) == 0


# --- dump real -------------------------------------------------------------

@necesita_dump
def test_dump_pool_es_parte_del_censo():
    from pokopia.container import read_file, read_index, unpack_entry
    idx = read_index(os.path.join(ROMFS, paths.IDX_NAME))
    binp = read_file(os.path.join(ROMFS, paths.BIN_NAME))
    blob = unpack_entry(binp, idx[3255], 3255)
    tabla = textpool.es_tabla(blob, 3255)
    assert tabla is not None and tabla.count == 391
    assert textpool.validar(tabla, blob) == []


@necesita_dump
def test_dump_es_verificado_con_20_muestras():
    from pokopia.container import read_file, read_index, unpack_entry
    idx = read_index(os.path.join(ROMFS, paths.IDX_NAME))
    binp = read_file(os.path.join(ROMFS, paths.BIN_NAME))
    blob = unpack_entry(binp, idx[3255], 3255)
    tabla = textpool.parse(3255, blob)
    utiles = [t for t in tabla.textos(blob) if len(t) >= 150]
    paso = max(1, len(utiles) // 20)
    muestras = utiles[::paso][:20]
    resumen = idioma.consenso([idioma.detectar(t) for t in muestras])
    assert resumen["idioma"] == "es"
    assert resumen["votos"] == len(muestras)


@necesita_dump
def test_dump_sustitucion_ajuste_encoge_el_payload():
    from pokopia.container import read_file, read_index, unpack_entry
    idx = read_index(os.path.join(ROMFS, paths.IDX_NAME))
    binp = read_file(os.path.join(ROMFS, paths.BIN_NAME))
    blob = unpack_entry(binp, idx[3255], 3255)
    tabla = textpool.parse(3255, blob)
    viejo = tabla.slots(blob)[0]
    texto = b"Frase propia de prueba."
    nuevo = textpool.sustituir(tabla, blob, 0, texto, modo="ajuste")
    assert len(nuevo) == len(blob) - (len(viejo) - len(texto))
    tabla2 = textpool.parse(3255, nuevo)
    assert tabla2.slots(nuevo)[0] == texto
    assert textpool.validar(tabla2, nuevo) == []

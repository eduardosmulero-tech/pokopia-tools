"""`tools/recetas.py`: las piezas que deciden un resultado, con datos sinteticos.

Ningun byte del juego aqui: el `.fdata` y el registro se construyen byte a byte
con el formato medido. Lo que fijan estas pruebas, en el orden en que importan:

* `kt_hash` reproduce los tres pares hash<->nombre ya verificados (si esto falla,
  todo el barrido busca la aguja equivocada);
* `iter_refs` ve un hash **en las cuatro rejillas de 4 bytes**: en el dump real
  el bloque del diccionario empieza en un offset impar (+663) y una busqueda
  alineada lo pierde entera;
* `parse_dok` corta los registros `IDOK` por su tamano declarado en +0x08;
* la tasa base y el Poisson se comportan (sin ellos, un 4 de 1.000 millones se
  firma como hallazgo);
* de punta a punta sobre un romfs sintetico: `barrido` encuentra una lista de
  ingredientes cuando la hay, y `control_positivo` lo demuestra.
"""

from __future__ import annotations

import os
import struct
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

sys.path.insert(0, os.path.join(RAIZ, "tools"))
import recetas  # noqa: E402

KIDSOBJDB = 0x20A6A0BB


# ---------------------------------------------------------------------------
# Hash de nombres
# ---------------------------------------------------------------------------

def test_kt_hash_reproduce_los_pares_verificados():
    """Tres pares que no vienen de una tabla publica: dos del dump y uno del .name."""
    assert recetas.kt_hash("CharacterEditor.shader.kidssingletondb") == 0x718CCB8B
    assert recetas.kt_hash("BI00063_RENGA00_00") == 0xEC3B01C3
    assert recetas.kt_hash("BI00063_RENGA") == 0x6D675F64


def test_kt_hash_no_distingue_mayusculas_por_si_solo():
    """El hash es del nombre tal cual: cambiar un byte cambia el hash."""
    assert recetas.kt_hash("BI00063_RENGA00_00") != recetas.kt_hash("bi00063_renga00_00")


def test_kt_hash_trata_los_bytes_altos_como_sbyte():
    """La formula usa `int8(b)`: un byte > 127 entra en negativo. Se fija aqui
    porque es la parte que se copia mal al portar el algoritmo: con el byte como
    `uint8` el mismo nombre daria otro hash."""
    nombre = "A\u00e9"                      # UTF-8: 41 C3 A9
    crudo = nombre.encode()
    con_signo = (crudo[0] * 0x1F) & 0xFFFFFFFF
    sin_signo = con_signo
    k = 0x1F
    for ch in crudo[1:]:
        st = k
        k = (k * 0x1F) & 0xFFFFFFFF
        con_signo = (con_signo + 0x1F * st * (ch - 256)) & 0xFFFFFFFF
        sin_signo = (sin_signo + 0x1F * st * ch) & 0xFFFFFFFF
    assert recetas.kt_hash(nombre) == con_signo
    assert recetas.kt_hash(nombre) != sin_signo


def test_kt_hash_de_un_nombre_vacio_no_inventa():
    with pytest.raises(ValueError):
        recetas.kt_hash("")


# ---------------------------------------------------------------------------
# Control de tasa base
# ---------------------------------------------------------------------------

def test_la_tasa_base_es_una_aparicion_por_4gib_y_patron():
    assert recetas.expected_hits(4294967296, 1) == pytest.approx(1.0)
    assert recetas.expected_hits(4294967296, 87) == pytest.approx(87.0)
    assert recetas.expected_hits(4 * 1024 * 1024, 87) == pytest.approx(87 * (4 * 2**20 - 3) / 2**32)
    assert recetas.expected_hits(3, 87) == 0.0


def test_poisson_dice_cuanto_de_improbable_es_lo_observado():
    assert recetas.poisson_sf(0, 3.0) == 1.0
    assert recetas.poisson_sf(3, 3.0) > recetas.poisson_sf(9, 3.0)
    assert recetas.poisson_sf(9, 3.0) < 0.01
    assert recetas.poisson_sf(60, 3.0) < 1e-20
    for k, lam in ((1, 0.5), (5, 5.0), (40, 30.0), (5000, 4800.0)):
        assert 0.0 <= recetas.poisson_sf(k, lam) <= 1.0


def test_poisson_en_la_zona_normal_aproximada_no_se_sale_del_rango():
    assert 0.0 <= recetas.poisson_sf(1000, 900.0) <= 1.0


# ---------------------------------------------------------------------------
# Lectura del objdb
# ---------------------------------------------------------------------------

def _registro(ident: int, tipo: int, cuerpo: bytes) -> bytes:
    """Un registro `IDOK0000`: cabecera de 68 B + cuerpo, con el tamano en +0x08."""
    tam = 0x44 + len(cuerpo)
    cab = bytearray(0x44)
    cab[0:8] = b"IDOK0000"
    struct.pack_into("<I", cab, 0x08, tam)
    struct.pack_into("<I", cab, 0x0C, ident)
    struct.pack_into("<I", cab, 0x10, tipo)
    return bytes(cab) + cuerpo


def _payload_dok(registros: list[bytes]) -> bytes:
    cab = bytearray(24)
    cab[0:8] = b"_DOK0000"
    struct.pack_into("<I", cab, 8, 0x1C)
    struct.pack_into("<I", cab, 12, 0x18)
    return bytes(cab) + b"".join(registros)


def test_parse_dok_corta_por_el_tamano_declarado():
    payload = _payload_dok([_registro(1, 0xAA, b"\x00" * 12),
                            _registro(2, 0xBB, b"\x00" * 40)])
    recs = recetas.parse_dok(payload)
    assert len(recs) == 2
    assert recs[0] == (24, 0x44 + 12)
    assert recs[1][0] == 24 + 0x44 + 12
    assert recs[1][1] == 0x44 + 40


def test_parse_dok_ignora_lo_que_no_es_un_objdb():
    assert recetas.parse_dok(b"PDRK0000" + b"\x00" * 64) == []


def test_parse_dok_no_se_come_un_registro_con_tamano_imposible():
    cab = bytearray(24)
    cab[0:8] = b"_DOK0000"
    roto = bytes(cab) + b"IDOK0000" + struct.pack("<II", 0xFFFFFF, 1)
    assert recetas.parse_dok(roto) == []


def test_iter_refs_ve_las_cuatro_rejillas():
    """El mismo hash en offsets 0, 1, 2 y 3: los cuatro tienen que salir."""
    objetivo = 0x9DA31EC6
    patron = struct.pack("<I", objetivo)
    for desplazamiento in range(4):
        blob = b"\xAA" * desplazamiento + patron + b"\xAA" * 16
        vistos = list(recetas.iter_refs(blob, {objetivo}))
        assert vistos, "offset %d: la rejilla no lo ve" % desplazamiento
        assert vistos[0][0] == desplazamiento


def test_iter_refs_no_devuelve_lo_que_no_esta():
    assert list(recetas.iter_refs(b"\x00" * 64, {0x9DA31EC6})) == []


def test_posiciones_u32_cuenta_las_cuatro_rejillas_y_no_una():
    """La tasa base se calcula sobre ~n posiciones, no sobre n/4."""
    n = 1000
    una_rejilla = n // 4
    total = recetas.posiciones_u32(n)
    assert total > 3.9 * una_rejilla
    assert n - 7 <= total <= n


def test_posiciones_u32_coincide_con_la_ultima_posicion_de_cada_rejilla():
    """La cuenta de posiciones y el barrido real no pueden separarse.

    Se coloca la aguja en la **ultima** palabra de cada rejilla: es donde una
    aritmetica mal llevada (`n - 3` en vez de `(n - k) // 4`) pierde la cola del
    blob sin que se note en los totales.
    """
    objetivo = 0x9DA31EC6
    patron = struct.pack("<I", objetivo)
    n = 512
    for rejilla in range(4):
        palabras = (n - rejilla) // 4
        assert palabras > 0
        p = rejilla + 4 * (palabras - 1)
        blob = bytearray(b"\xAA" * n)
        blob[p:p + 4] = patron
        hallados = [pos for pos, _ in recetas.iter_refs(bytes(blob), {objetivo})]
        assert hallados == [p], "rejilla %d no ve +%d: %r" % (rejilla, p, hallados)
    assert recetas.posiciones_u32(n) == sum((n - k) // 4 for k in range(4))


def test_el_xref_cobra_la_tasa_base_sobre_las_cuatro_rejillas(tmp_path):
    """`esperadas_por_azar` tiene que salir de las posiciones barridas, no de n/4."""
    root = _romfs_sintetico(tmp_path, NOMBRES, [])
    hashes = recetas.read_entities(root)["hashes"]
    info = recetas.resumen_xref(root, hashes, str(tmp_path / "out"))
    assert info["rejillas"] == 4
    assert info["posiciones_barridas"] > 3.9 * info["palabras_u32"]
    assert info["esperadas_por_azar"] == (info["posiciones_barridas"] * len(hashes)
                                         / 4294967296.0)


def test_la_tasa_base_del_xref_deja_fuera_el_diccionario(tmp_path):
    """El registro que cita las 2.043 entidades no es azar: sale de la tasa base.

    Si entrara, 2.043 apariciones "explicarian" cualquier cifra. Se comprueba con
    un romfs de 5 entidades donde el diccionario cita 5 y una receta cita 3.
    """
    receta = ["BP02249_A00_CONCRETE_MIXER00_00",
              "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = _romfs_sintetico(tmp_path, NOMBRES, [receta])
    hashes = recetas.read_entities(root)["hashes"]
    info = recetas.resumen_xref(root, hashes, str(tmp_path / "out"))
    assert info["registros_diccionario"] == 1
    assert info["refs_entidad"] == len(NOMBRES) + 3      # diccionario + receta
    assert info["refs_fuera_diccionario"] == 3
    assert info["blobs_fuera_diccionario"] >= 1
    assert info["posiciones_fuera_diccionario"] > 0
    assert info["esperadas_fuera_diccionario"] == (
        info["posiciones_fuera_diccionario"] * len(hashes) / 4294967296.0)
    assert 0.0 <= info["p_valor_fuera_diccionario"] <= 1.0


def test_el_control_positivo_inyecta_en_las_cuatro_rejillas_y_las_ve(tmp_path):
    """El control positivo tiene que suspender si el detector pierde una rejilla."""
    nombres = ["BI00010_KOMUGI00_00", "BI00014_POTATO00_00", "BI00056_TETSU_INGOT00_00",
               "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = _romfs_sintetico(tmp_path, nombres, [])
    hashes = recetas.read_entities(root)["hashes"]
    ctrl = recetas.control_positivo(root, hashes)
    assert ctrl["patrones_inyectados"] == 5
    assert ctrl["detectados_en_el_sintetico"] == 5
    assert ctrl["rejillas_usadas"] == [0, 1, 2, 3]
    # el control elige un blob que NO contenga ya los patrones: si eligiera el
    # del diccionario, este 0 seria una tautologia y no mediria nada
    assert ctrl["blob_limpio"] is True
    assert ctrl["detectados_en_el_original"] == 0
    assert ctrl["falsos_positivos"] == 0
    recetas.comprobar_control(ctrl)          # no levanta


def test_el_control_positivo_se_niega_a_firmar_con_un_blob_sucio(tmp_path):
    """Si no hay blob limpio, el control lo declara y `comprobar_control` para."""
    nombres = ["BI00010_KOMUGI00_00", "BI00014_POTATO00_00", "BI00056_TETSU_INGOT00_00",
               "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = str(tmp_path / "solo_diccionario")
    os.makedirs(os.path.join(root, "motor_asset_re"), exist_ok=True)
    bloque_hashes = b"".join(struct.pack("<I", recetas.kt_hash(n)) for n in nombres)
    # con los nombres, para que `read_entities` reconozca el diccionario
    cuerpo = bloque_hashes + b"\x00" * 64 + b"".join(n.encode() + b"\x00" for n in nombres)
    with open(os.path.join(root, "motor_asset_re", "0x0000beef.fdata"), "wb") as fh:
        fh.write(_fdata_plano(_payload_dok([_registro(0x1111, 0xDAC911D7, cuerpo)]),
                              0x0000BEEF, KIDSOBJDB))
    hashes = recetas.read_entities(root)["hashes"]
    ctrl = recetas.control_positivo(root, hashes)
    assert ctrl["blob_limpio"] is False
    assert ctrl["detectados_en_el_original"] == 5
    with pytest.raises(RuntimeError, match="control positivo roto"):
        recetas.comprobar_control(ctrl)


def test_el_control_positivo_falla_si_el_detector_pierde_una_rejilla(tmp_path, monkeypatch):
    """Con un detector de una sola rejilla, el control deja de dar 5/5.

    Es la prueba de que el control sirve: si `iter_refs` se rompe, `todo` se
    entera en vez de firmar un negativo falso.
    """
    from array import array

    def solo_rejilla_0(payload, conocidos):
        n = len(payload)
        palabras = n // 4
        for i, valor in enumerate(array("I", payload[:4 * palabras])):
            if valor in conocidos:
                yield 4 * i, valor

    nombres = ["BI00010_KOMUGI00_00", "BI00014_POTATO00_00", "BI00056_TETSU_INGOT00_00",
               "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = _romfs_sintetico(tmp_path, nombres, [])
    hashes = recetas.read_entities(root)["hashes"]
    monkeypatch.setattr(recetas, "iter_refs", solo_rejilla_0)
    ctrl = recetas.control_positivo(root, hashes)
    assert ctrl["detectados_en_el_sintetico"] < ctrl["patrones_inyectados"]
    with pytest.raises(RuntimeError, match="detector"):
        recetas.comprobar_control(ctrl)


# ---------------------------------------------------------------------------
# De punta a punta sobre un romfs sintetico
# ---------------------------------------------------------------------------

def _fdata_plano(payload: bytes, name_hash: int, type_ktid: int) -> bytes:
    """`.fdata` con una sola entrada sin comprimir (formato PDRK/IDRK)."""
    cab = b"PDRK0000" + struct.pack("<II", 0x10, 0)
    ent = b"IDRK0000" + struct.pack("<3Q", 0x30 + len(payload), len(payload),
                                    len(payload))
    ent += struct.pack("<4I", 1, name_hash, type_ktid, 0)
    blob = cab + ent + payload
    relleno = (-len(blob)) % 0x10
    return blob + b"\x00" * relleno


def _romfs_sintetico(tmp_path, nombres: list[str], recetas_sinteticas: list[list[str]]) -> str:
    """Romfs con un objdb que lleva el diccionario y, si se pide, recetas.

    Lleva ademas un segundo `kidsobjdb` **sin ningun nombre de entidad**: el
    control negativo del `control_positivo` solo vale sobre un blob que no
    contenga ya los patrones, y el registro del diccionario los contiene todos.
    """
    bloque_hashes = b"".join(struct.pack("<I", recetas.kt_hash(n)) for n in nombres)
    bloque_nombres = b"".join(n.encode() + b"\x00" for n in nombres)
    # el bloque de hashes va desplazado 3 bytes, como en el dump real (+663)
    cuerpo_dic = b"\x00\x00\x00" + bloque_hashes + b"\x00" * 64 + bloque_nombres
    registros = [_registro(0x1111, 0xDAC911D7, cuerpo_dic)]
    for i, receta in enumerate(recetas_sinteticas):
        # producto, 3 ingredientes con cantidad, todo pegado: forma de receta
        cuerpo = struct.pack("<I", recetas.kt_hash(receta[0]))
        for ingrediente, cantidad in zip(receta[1:], (3, 2, 1)):
            cuerpo += struct.pack("<IH", recetas.kt_hash(ingrediente), cantidad)
        registros.append(_registro(0x2000 + i, 0xC0FFEE01, cuerpo))
    root = str(tmp_path / "romfs")
    os.makedirs(os.path.join(root, "motor_asset_re"), exist_ok=True)
    ruta = os.path.join(root, "motor_asset_re", "0x0000beef.fdata")
    with open(ruta, "wb") as fh:
        fh.write(_fdata_plano(_payload_dok(registros), 0x0000BEEF, KIDSOBJDB))
    # blob de control limpio: relleno sin hashes de entidad (0x00 no es entidad)
    neutral = _registro(0x3333, 0x12345678, b"\x00" * 4096)
    with open(os.path.join(root, "motor_asset_re", "0x0000cafe.fdata"), "wb") as fh:
        fh.write(_fdata_plano(_payload_dok([neutral]), 0x0000CAFE, KIDSOBJDB))
    return root


NOMBRES = [
    "BI00010_KOMUGI00_00",
    "BI00060_NENDO00_00",
    "BI00063_RENGA00_00",
    "BP02249_A00_CONCRETE_MIXER00_00",
    "BP09999_A00_OTRA_COSA00_00",
]


def test_entidades_lee_el_diccionario_y_verifica_los_hashes(tmp_path):
    root = _romfs_sintetico(tmp_path, NOMBRES, [])
    tabla = recetas.read_entities(root)
    assert tabla["meta"]["nombres_total"] == len(NOMBRES)
    assert tabla["meta"]["hashes_presentes"] == len(NOMBRES)
    assert tabla["meta"]["prefijos"] == {"BI": 3, "BP": 2}
    assert recetas.kt_hash("BI00063_RENGA00_00") in tabla["hashes"]


def test_el_barrido_encuentra_una_lista_de_ingredientes_cuando_la_hay(tmp_path):
    """Control positivo de punta a punta: si hay receta, sale. Y con su tasa base."""
    receta = ["BP02249_A00_CONCRETE_MIXER00_00",
              "BI00010_KOMUGI00_00", "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = _romfs_sintetico(tmp_path, NOMBRES, [receta])
    hashes = recetas.read_entities(root)["hashes"]
    info = recetas.barrido(root, hashes, None, frozenset(), None)
    # 3 hashes de material en el diccionario + 3 en la receta
    assert info["hits"] == 6
    assert info["blobs_con_hits"] == 1
    # la tasa base de 87 patrones en 3 KB es practicamente cero
    assert info["esperadas_por_azar"] < 1e-3
    assert info["p_valor"] < 1e-6


def test_el_barrido_no_inventa_cuando_no_hay_receta(tmp_path):
    root = _romfs_sintetico(tmp_path, NOMBRES, [])
    tabla = recetas.read_entities(root)
    hashes = tabla["hashes"]
    meta = tabla["meta"]
    dicc = (meta["fichero"], meta["entrada"], meta["registro"])
    info = recetas.barrido(root, hashes, None, frozenset(), None, dicc)
    assert info["hits"] == 3          # solo el diccionario
    assert info["hits_fuera_del_diccionario"] == 0


def test_buscar_dice_en_que_registro_cae_un_hash(tmp_path):
    receta = ["BP02249_A00_CONCRETE_MIXER00_00",
              "BI00060_NENDO00_00", "BI00063_RENGA00_00"]
    root = _romfs_sintetico(tmp_path, NOMBRES, [receta])
    patrones = {"BI00063_RENGA00_00":
                struct.pack("<I", recetas.kt_hash("BI00063_RENGA00_00"))}
    info = recetas.buscar(root, patrones)
    # aparece dos veces: en el diccionario y en la receta
    assert info["hits"] == 2
    tipos = {fila.get("registro_tipo") for fila in info["detalle"]}
    assert "0xc0ffee01" in tipos
    assert "0xdac911d7" in tipos


def test_el_grafo_por_id_encuentra_las_aristas_sinteticas(tmp_path):
    """Dos registros que se citan por su id: el grafo tiene que verlo."""
    a = _registro(0xAAAA0001, 0xC0FFEE01, struct.pack("<II", 0xAAAA0002, 7))
    b = _registro(0xAAAA0002, 0xC0FFEE02, b"\x00" * 8)
    root = str(tmp_path / "romfs")
    os.makedirs(os.path.join(root, "motor_asset_re"), exist_ok=True)
    with open(os.path.join(root, "motor_asset_re", "0x0000beef.fdata"), "wb") as fh:
        fh.write(_fdata_plano(_payload_dok([a, b]), 0x0000BEEF, KIDSOBJDB))
    info = recetas.grafo_ids(root, str(tmp_path / "out"))
    assert info["ids"] == 2
    assert info["aristas"] >= 1


# ---------------------------------------------------------------------------
# Contra el dump real (se saltan con motivo si no esta)
# ---------------------------------------------------------------------------

def _romfs_real():
    from pokopia import paths

    root = paths.configured_romfs()
    if not os.path.isdir(root):
        return None
    if not os.path.isfile(os.path.join(root, paths.IDX_NAME)):
        return None
    return root


@pytest.mark.skipif(_romfs_real() is None, reason="sin romfs real (PKP_ROMFS)")
def test_el_diccionario_real_da_los_2043_nombres_y_todos_los_hashes():
    root = _romfs_real()
    tabla = recetas.read_entities(root)
    assert tabla["meta"]["nombres_total"] == 2043
    assert tabla["meta"]["hashes_presentes"] == 2043
    assert tabla["meta"]["prefijos"] == {"BP": 1473, "PM": 399, "BI": 87, "PC": 73, "AP": 11}


@pytest.mark.skipif(_romfs_real() is None, reason="sin romfs real (PKP_ROMFS)")
def test_el_control_positivo_ve_lo_que_inyecta_sobre_el_dump_real():
    root = _romfs_real()
    hashes = recetas.read_entities(root)["hashes"]
    ctrl = recetas.control_positivo(root, hashes)
    assert ctrl["detectados_en_el_sintetico"] == ctrl["patrones_inyectados"]
    assert ctrl["blob_limpio"] is True
    assert ctrl["detectados_en_el_original"] == 0
    assert ctrl["falsos_positivos"] == 0
    recetas.comprobar_control(ctrl)

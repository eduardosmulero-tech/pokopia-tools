"""`expect_sha256`: criterio del hash, esquema, validacion, aplicacion y merge.

Todo el texto de este fichero es **inventado** (`ALFA-INVENTADO`, ...): ni una
cadena del juego. El vector fija el criterio de `docs/MOD-FORMAT.md` §3.1 con un
literal, para que un cambio de criterio rompa el test en vez de pasar inadvertido,
y para que el test no tenga que creerse a la funcion que comprueba.
"""

from __future__ import annotations

import hashlib

import pytest

from pokopia import paths, tables
from pokopia.cli import main
from pokopia.mod import apply_mod, load_mod, merge_mods, validate
from pokopia.mod.apply import make_plan
from pokopia.mod.errors import ModError
from pokopia.mod.manifest import ContainerView, TextEdit

from tests import helpers

# ---------------------------------------------------------------------------
# Vector inventado (literal, calculado a mano con hashlib)
# ---------------------------------------------------------------------------

BLOQUE = [b"ALFA-INVENTADO", b"", b"BETA-INVENTADO",
          b"GAMMA-INVENTADO", b"", b"DELTA-INVENTADO"]
#: sha256(b"ALFA-INVENTADO" + b"" + b"BETA-INVENTADO" + b"GAMMA-INVENTADO" + b"" + b"DELTA-INVENTADO")
SHA_BLOQUE = "b709b75b4a857dc119f2583b1c532930b5f61c8669e1daa64282b01422ee6831"
SHA_BLOQUE_NUL = "97f8cba07314af2f0f5ac47dbee566a28a73772df4af4c27363740e76aef19ec"

#: Bloque truncado: solo tres slots existen en el pool.
TRUNCADO = [b"UNO-INVENTADO", b"", b"DOS-INVENTADO"]
SHA_TRUNCADO = "810fe5deac9c7dfd856f94c7b6a27eb26163888c1204b83d72deac6ab40c6ffd"

#: sha256 de la cadena vacia (bloque con todos los slots vacios).
SHA_VACIO = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

SPEC = tables.TableSpec(index=helpers.TEXT_TABLE, kind="text", header=64, stride=32,
                        count=helpers.TEXT_COUNT, version=2,
                        pool_start=64 + 32 * helpers.TEXT_COUNT)


def _slots() -> list[bytes]:
    """Pool sintetico de 40 slots: los bloques 4..9 completos y el 10 truncado."""
    relleno = [b"RELLENO-%02d" % i for i in range(helpers.TEXT_SLOTS - len(BLOQUE))]
    return BLOQUE + relleno


# ---------------------------------------------------------------------------
# Criterio del hash
# ---------------------------------------------------------------------------

def test_vector_del_bloque():
    assert tables.block_sha256(SPEC, _slots(), 4) == SHA_BLOQUE


def test_sin_terminador_y_sin_separador():
    """El criterio es concatenacion pura: ni NUL de separacion ni nada añadido."""
    assert hashlib.sha256(b"".join(BLOQUE)).hexdigest() == SHA_BLOQUE
    assert hashlib.sha256(b"\x00".join(BLOQUE)).hexdigest() == SHA_BLOQUE_NUL
    assert SHA_BLOQUE != SHA_BLOQUE_NUL


def test_el_orden_de_los_slots_importa():
    al_reves = list(reversed(BLOQUE)) + _slots()[len(BLOQUE):]
    assert tables.block_sha256(SPEC, al_reves, 4) != SHA_BLOQUE


def test_bloque_truncado_hashea_los_slots_que_hay():
    """El ultimo bloque puede tener menos de 6 slots: se hashea lo que existe."""
    slots = [b"RELLENO-%02d" % i for i in range(6)] + TRUNCADO
    assert tables.block_sha256(SPEC, slots, 5) == SHA_TRUNCADO


def test_bloque_vacio_hashea_la_cadena_vacia():
    slots = [b""] * 6 + _slots()[6:]
    assert tables.block_sha256(SPEC, slots, 4) == SHA_VACIO


def test_id_fuera_de_rango_no_se_silencia():
    with pytest.raises(tables.TableError):
        tables.block_sha256(SPEC, _slots(), 3)
    with pytest.raises(tables.TableError):
        tables.block_slots(SPEC, _slots(), helpers.TEXT_COUNT + 4)


# ---------------------------------------------------------------------------
# Esquema (sin contenedor)
# ---------------------------------------------------------------------------

def _doc(**campos) -> dict:
    edit = {"table": 4650, "id": 5, "slot": 0, "value": "MOD-INVENTADO-1", "why": "prueba"}
    edit.update(campos)
    return {
        "mod_format": 1, "name": "m", "version": "0.1.0", "authors": ["t"],
        "game": {"title": "pokopia", "version": "2.0.1a",
                 "container_md5": {paths.BIN_NAME: "0" * 32, paths.IDX_NAME: "1" * 32}},
        "edits": [], "text": [edit],
    }


def _validar(doc: dict, tmp_path, container=None) -> tuple[bool, list[str]]:
    ruta = helpers.write_mod(str(tmp_path / "m"), doc)
    mod = load_mod(ruta)
    rep = validate(mod, container)
    return rep.ok, [str(i) for i in rep.issues]


def test_expect_sha256_valido_pasa_el_esquema(tmp_path):
    ok, issues = _validar(_doc(expect_sha256=SHA_BLOQUE), tmp_path)
    assert ok, issues


def test_expect_vacio_sigue_valiendo(tmp_path):
    """La forma antigua (texto en claro) no desaparece: solo deja de ser publicable."""
    ok, issues = _validar(_doc(expect=""), tmp_path)
    assert ok, issues


def test_los_dos_campos_son_error_de_esquema(tmp_path):
    ok, issues = _validar(_doc(expect="ALFA-INVENTADO", expect_sha256=SHA_BLOQUE), tmp_path)
    assert not ok
    assert any("mutuamente excluyentes" in i for i in issues), issues


def test_sin_ninguno_de_los_dos_es_error_de_esquema(tmp_path):
    ok, issues = _validar(_doc(), tmp_path)
    assert not ok
    assert any("falta 'expect_sha256'" in i for i in issues), issues


@pytest.mark.parametrize("valor", [
    SHA_BLOQUE.upper(),                     # mayusculas
    SHA_BLOQUE[:63],                        # 63 caracteres
    SHA_BLOQUE + "0",                       # 65 caracteres
    "0x" + SHA_BLOQUE,                      # prefijo
    SHA_BLOQUE.replace("b", "z"),           # no es hex
    12345,                                  # no es cadena
])
def test_expect_sha256_mal_formado_es_error(tmp_path, valor):
    ok, issues = _validar(_doc(expect_sha256=valor), tmp_path)
    assert not ok, issues
    assert any("expect_sha256" in i for i in issues), issues


def test_as_dict_conserva_el_hash_y_no_inventa_texto():
    edit = TextEdit(table=4650, id=5, value="MOD-INVENTADO-1", why="t",
                    expect_sha256=SHA_BLOQUE)
    doc = edit.as_dict()
    assert doc["expect_sha256"] == SHA_BLOQUE
    assert "expect" not in doc

    claro = TextEdit(table=4650, id=5, value="MOD-INVENTADO-1", why="t", expect="")
    doc = claro.as_dict()
    assert doc["expect"] == "" and "expect_sha256" not in doc


# ---------------------------------------------------------------------------
# Contra un contenedor sintetico
# ---------------------------------------------------------------------------

@pytest.fixture()
def contenedor(tmp_path):
    with helpers.text_spec():
        payload = helpers.text_payload(_slots())
        yield helpers.make_container(str(tmp_path / "copia"),
                                     {helpers.TEXT_TABLE: payload})


def _doc_texto(cont, **campos) -> dict:
    doc = helpers.base_doc(cont, "mod-texto-hash")
    edit = {"table": helpers.TEXT_TABLE, "id": 4, "slot": 2,
            "value": "MOD-INVENTADO-1", "why": "prueba"}
    edit.update(campos)
    doc["text"] = [edit]
    return doc


def test_validate_con_hash_que_cuadra(contenedor, tmp_path):
    ok, issues = _validar(_doc_texto(contenedor, expect_sha256=SHA_BLOQUE),
                          tmp_path, contenedor)
    assert ok, issues


def test_validate_con_hash_desfasado_no_imprime_texto(contenedor, tmp_path):
    ok, issues = _validar(_doc_texto(contenedor, expect_sha256="0" * 64),
                          tmp_path, contenedor)
    assert not ok
    texto = "\n".join(issues)
    assert "esperaba el bloque con sha256" in texto, texto
    assert "58 B" in texto and "6 slots" in texto, texto
    assert hashlib.sha256(b"".join(BLOQUE)).hexdigest()[:12] in texto, texto
    for inventado in BLOQUE:
        if inventado:
            assert inventado.decode() not in texto, texto


def test_expect_en_claro_desfasado_tampoco_imprime_texto(contenedor, tmp_path):
    """El defecto que motivo la tarjeta: `%r` del expect imprimia texto del juego."""
    ok, issues = _validar(_doc_texto(contenedor, expect="OTRA-COSA-INVENTADA"),
                          tmp_path, contenedor)
    assert not ok
    texto = "\n".join(issues)
    assert "esperaba un texto de 19 B" in texto, texto
    assert "ALFA-INVENTADO" not in texto, texto        # lo que hay en el contenedor
    assert "OTRA-COSA-INVENTADA" not in texto, texto   # lo que traia el manifiesto
    assert "sha256" in texto, texto


def test_apply_con_hash_escribe_solo_su_slot(contenedor, tmp_path):
    mod = load_mod(helpers.write_mod(
        str(tmp_path / "mods" / "hash"), _doc_texto(contenedor, expect_sha256=SHA_BLOQUE)))
    antes = helpers.read_payload(contenedor, helpers.TEXT_TABLE)
    res = apply_mod(mod, contenedor.dir, write=True)
    assert res["ok"], res["issues"]
    assert res["tables"][0]["pool_prefix_identical"] is True

    despues = helpers.read_payload(contenedor, helpers.TEXT_TABLE)
    slots_antes, _ = tables.parse_pool(tables.get(helpers.TEXT_TABLE), antes)
    slots_despues, _ = tables.parse_pool(tables.get(helpers.TEXT_TABLE), despues)
    assert len(slots_antes) == len(slots_despues)
    assert slots_despues[2] == b"MOD-INVENTADO-1"
    assert slots_despues[:2] == slots_antes[:2]
    assert slots_despues[3:] == slots_antes[3:]


def test_apply_con_hash_desfasado_se_para_sin_escribir(contenedor, tmp_path):
    doc = _doc_texto(contenedor, expect_sha256="0" * 64)
    mod = load_mod(helpers.write_mod(str(tmp_path / "mods" / "malo"), doc))
    antes = paths.container_md5(contenedor)
    res = apply_mod(mod, contenedor.dir, write=True)
    assert not res["ok"]
    texto = "\n".join(i["message"] for i in res["issues"])
    for inventado in BLOQUE:
        if inventado:
            assert inventado.decode() not in texto, texto
    assert paths.container_md5(contenedor) == antes


def test_make_plan_es_quien_comprueba_el_hash(contenedor):
    """Segunda puerta: aunque `validate` se saltara, el plan no escribe a ciegas."""
    edit = TextEdit(table=helpers.TEXT_TABLE, id=4, slot=2, value="MOD-INVENTADO-1",
                    why="t", expect_sha256="0" * 64)
    mod = type("M", (), {"edits": [], "texts": [edit], "name": "m", "version": "0",
                         "manifest": "", "doc": {}})()
    with pytest.raises(ModError) as exc:
        make_plan(mod, contenedor, view=ContainerView(contenedor))
    assert exc.value.code == "mod.text.expect"
    for inventado in BLOQUE:
        if inventado:
            assert inventado.decode() not in str(exc.value)


def test_merge_conserva_el_hash(contenedor, tmp_path):
    a = helpers.write_mod(str(tmp_path / "mods" / "a"),
                          _doc_texto(contenedor, expect_sha256=SHA_BLOQUE))
    doc_b = _doc_texto(contenedor, expect_sha256=SHA_TRUNCADO)
    doc_b["name"] = "mod-texto-b"
    doc_b["text"][0]["id"] = 5
    doc_b["text"][0]["slot"] = 0
    b = helpers.write_mod(str(tmp_path / "mods" / "b"), doc_b)
    res = merge_mods(a, b, check_container=False)
    assert res.ok, [str(i) for i in res.report.issues]
    textos = res.doc["text"]
    assert [t.get("expect_sha256") for t in textos] == [SHA_BLOQUE, SHA_TRUNCADO]
    assert all("expect" not in t for t in textos)


def test_la_cli_imprime_el_hash_del_bloque(contenedor, capsys):
    assert main(["row", str(helpers.TEXT_TABLE), "4", "--container", contenedor.dir]) == 0
    salida = capsys.readouterr().out
    assert "bloque" in salida and SHA_BLOQUE in salida, salida
    for inventado in BLOQUE:
        if inventado:
            assert inventado.decode() not in salida, salida


# ---------------------------------------------------------------------------
# Varias ediciones a la vez: la referencia es SIEMPRE el bloque pristino
# ---------------------------------------------------------------------------
#
# `expect_sha256` hashea el bloque entero, asi que si `apply` comparase contra el
# buffer en curso, la segunda edicion de un mismo bloque fallaria por lo que hizo
# la primera y `validate` (que mira el payload pristino) diria otra cosa para el
# mismo mod y el mismo contenedor. Estos tests fijan el criterio: verificacion
# contra el original, construccion sobre la copia de trabajo.

#: Bloque del id 5 en el pool sintetico: slots 6..11 = RELLENO-00..RELLENO-05.
RELLENO = [b"RELLENO-%02d" % i for i in range(6)]
SHA_RELLENO = hashlib.sha256(b"".join(RELLENO)).hexdigest()


def _doc_con(cont, *ediciones, nombre: str = "mod-varias") -> dict:
    """Mod con varias ediciones de texto: `(id, slot, value, expect_sha256)`."""
    doc = helpers.base_doc(cont, nombre)
    doc["text"] = [{"table": helpers.TEXT_TABLE, "id": i, "slot": s, "value": v,
                    "why": "prueba", "expect_sha256": h}
                   for i, s, v, h in ediciones]
    return doc


def _leer_slots(cont) -> list[bytes]:
    payload = helpers.read_payload(cont, helpers.TEXT_TABLE)
    slots, _ = tables.parse_pool(tables.get(helpers.TEXT_TABLE), payload)
    return slots


def test_dos_ids_de_la_misma_tabla_con_hash(contenedor, tmp_path):
    """Caso del acta: dos textos existentes de la misma tabla en un solo mod."""
    doc = _doc_con(contenedor,
                   (4, 0, "MOD-UNO-INVENTADO", SHA_BLOQUE),
                   (5, 0, "MOD-DOS-INVENTADO", SHA_RELLENO))
    mod = load_mod(helpers.write_mod(str(tmp_path / "m"), doc))
    rep = validate(mod, contenedor)
    assert rep.ok, [str(i) for i in rep.issues]

    res = apply_mod(mod, contenedor.dir, write=True)
    assert res["ok"], res["issues"]
    slots = _leer_slots(contenedor)
    assert slots[0] == b"MOD-UNO-INVENTADO"     # bloque id 4, +0
    assert slots[6] == b"MOD-DOS-INVENTADO"     # bloque id 5, +0
    assert slots[1:6] == BLOQUE[1:]
    assert slots[7:12] == RELLENO[1:]


def test_dos_slots_del_mismo_bloque(contenedor, tmp_path):
    """Singular (+0) y plural (+2) del mismo id: las dos ediciones entran."""
    doc = _doc_con(contenedor,
                   (4, 0, "MOD-UNO-INVENTADO", SHA_BLOQUE),
                   (4, 2, "MOD-DOS-INVENTADO", SHA_BLOQUE))
    mod = load_mod(helpers.write_mod(str(tmp_path / "m"), doc))
    rep = validate(mod, contenedor)
    assert rep.ok, [str(i) for i in rep.issues]

    res = apply_mod(mod, contenedor.dir, write=True)
    assert res["ok"], res["issues"]
    assert res["tables"][0]["pool_prefix_identical"] is True
    slots = _leer_slots(contenedor)
    assert slots[0] == b"MOD-UNO-INVENTADO"
    assert slots[2] == b"MOD-DOS-INVENTADO"
    assert slots[1] == BLOQUE[1] and slots[3:6] == BLOQUE[3:]
    assert slots[6:] == _slots()[6:]


def test_segundo_hash_desfasado_falla_por_el_hash_y_no_por_el_buffer(contenedor, tmp_path):
    """La segunda edicion se compara contra el bloque PRISTINO, no contra el mutado."""
    doc = _doc_con(contenedor,
                   (4, 0, "MOD-UNO-INVENTADO", SHA_BLOQUE),   # esta cuadra
                   (4, 2, "MOD-DOS-INVENTADO", SHA_RELLENO))  # esta no
    mod = load_mod(helpers.write_mod(str(tmp_path / "m"), doc))
    rep = validate(mod, contenedor)
    assert not rep.ok
    assert any(i.code == "mod.text.expect" for i in rep.issues), [str(i) for i in rep.issues]

    texto = "\n".join(str(i) for i in rep.issues)
    assert "esperaba el bloque con sha256" in texto, texto
    # El "encontre" es el bloque tal como esta ANTES del mod...
    assert SHA_BLOQUE[:12] in texto, texto
    # ...no el que dejaria la primera edicion ya aplicada.
    mutado = [b"MOD-UNO-INVENTADO"] + BLOQUE[1:]
    huella_mutada = hashlib.sha256(b"".join(mutado)).hexdigest()
    assert huella_mutada[:12] not in texto, texto
    for inventado in BLOQUE + [b"MOD-UNO-INVENTADO"]:
        if inventado:
            assert inventado.decode() not in texto, texto

    # Y `apply` dice lo mismo que `validate`: nada de dos veredictos.
    antes = paths.container_md5(contenedor)
    res = apply_mod(mod, contenedor.dir, write=True)
    assert not res["ok"]
    assert any(i["code"] == "mod.text.expect" for i in res["issues"]), res["issues"]
    assert paths.container_md5(contenedor) == antes


def test_dos_ediciones_del_mismo_slot_es_error(contenedor, tmp_path):
    """La segunda pisaria a la primera en silencio: se rechaza con las dos ubicaciones."""
    doc = _doc_con(contenedor,
                   (4, 0, "MOD-UNO-INVENTADO", SHA_BLOQUE),
                   (4, 0, "MOD-DOS-INVENTADO", SHA_BLOQUE))
    mod = load_mod(helpers.write_mod(str(tmp_path / "m"), doc))
    rep = validate(mod, contenedor)
    assert not rep.ok
    duplicados = [i for i in rep.issues if i.code == "mod.text.duplicate"]
    assert len(duplicados) == 1, [str(i) for i in rep.issues]
    assert "text[0]" in duplicados[0].message and "text[1]" in duplicados[0].message

    antes = paths.container_md5(contenedor)
    res = apply_mod(mod, contenedor.dir, write=True)
    assert not res["ok"]
    assert any(i["code"] == "mod.text.duplicate" for i in res["issues"]), res["issues"]
    assert paths.container_md5(contenedor) == antes


def test_make_plan_tambien_para_el_slot_duplicado(contenedor):
    """Segunda puerta: `make_plan` por si solo, sin pasar por el esquema."""
    primero = TextEdit(table=helpers.TEXT_TABLE, id=4, slot=2, value="MOD-UNO-INVENTADO",
                       why="t", expect_sha256=SHA_BLOQUE, index=0)
    segundo = TextEdit(table=helpers.TEXT_TABLE, id=4, slot=2, value="MOD-DOS-INVENTADO",
                       why="t", expect_sha256=SHA_BLOQUE, index=1)
    mod = type("M", (), {"edits": [], "texts": [primero, segundo], "name": "m",
                         "version": "0", "manifest": "", "doc": {}})()
    with pytest.raises(ModError) as exc:
        make_plan(mod, contenedor, view=ContainerView(contenedor))
    assert exc.value.code == "mod.text.duplicate"
    assert "text[0]" in str(exc.value) and "text[1]" in str(exc.value)


def test_merge_mismo_bloque_slots_distintos_se_aplica(contenedor, tmp_path):
    """`merge` compone la pareja con aviso; el compuesto se aplica de verdad (§4)."""
    a = helpers.write_mod(str(tmp_path / "mods" / "a"),
                          _doc_con(contenedor, (4, 0, "MOD-UNO-INVENTADO", SHA_BLOQUE),
                                   nombre="mod-a"))
    b = helpers.write_mod(str(tmp_path / "mods" / "b"),
                          _doc_con(contenedor, (4, 2, "MOD-DOS-INVENTADO", SHA_BLOQUE),
                                   nombre="mod-b"))
    res = merge_mods(a, b, out_dir=str(tmp_path / "comp"), check_container=False)
    assert res.ok, [str(i) for i in res.report.issues]
    assert any("mismo bloque" in str(i) for i in res.report.issues), \
        [str(i) for i in res.report.issues]

    mod = load_mod(res.written)
    rep = validate(mod, contenedor)
    assert rep.ok, [str(i) for i in rep.issues]

    aplicado = apply_mod(mod, contenedor.dir, write=True)
    assert aplicado["ok"], aplicado["issues"]
    slots = _leer_slots(contenedor)
    assert slots[0] == b"MOD-UNO-INVENTADO"
    assert slots[2] == b"MOD-DOS-INVENTADO"

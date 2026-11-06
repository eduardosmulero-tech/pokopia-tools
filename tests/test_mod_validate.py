"""Carga y validacion de `mod.json`: esquema, rangos, md5 y expect."""

from __future__ import annotations

import copy
import json
import os

import pytest

from pokopia import paths
from pokopia.mod import load_mod, validate
from pokopia.mod.errors import ModError

from tests import helpers

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EJEMPLOS = os.path.join(RAIZ, "ejemplos")
HAY_DUMP = os.path.isfile(os.path.join(paths.configured_romfs(), paths.IDX_NAME))
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego")


# --------------------------------------------------------------------------
# Esquema (sin contenedor)
# --------------------------------------------------------------------------

def _mod_minimo() -> dict:
    return {
        "mod_format": 1, "name": "m", "version": "0.1.0", "authors": ["t"],
        "game": {"title": "pokopia", "version": "2.0.1a",
                 "container_md5": {"LD_C0_R.BIN": "0" * 32, "LI_C0_R.IDX": "1" * 32}},
        "edits": [{"table": 983, "row": 1, "offset": 34, "type": "u16",
                   "expect": "1", "value": "2", "why": "x"}],
    }


def _validar(doc: dict, tmp_path, container=None) -> tuple[bool, list[str]]:
    ruta = helpers.write_mod(str(tmp_path / "m"), doc)
    mod = load_mod(ruta)
    rep = validate(mod, container)
    return rep.ok, [str(i) for i in rep.issues]


def test_mod_minimo_valido(tmp_path):
    ok, issues = _validar(_mod_minimo(), tmp_path)
    assert ok, issues


def test_falta_mod_format(tmp_path):
    doc = _mod_minimo()
    doc.pop("mod_format")
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("mod_format" in i for i in issues)


def test_mod_format_incorrecto(tmp_path):
    doc = _mod_minimo()
    doc["mod_format"] = 2
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("solo entiende 1" in i for i in issues)


def test_falta_expect(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0].pop("expect")
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("'expect' es obligatorio" in i for i in issues)


def test_falta_why(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0].pop("why")
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("'why' es obligatorio" in i for i in issues)


def test_tipo_desconocido(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["type"] = "u24"
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("'type' debe ser uno de" in i for i in issues)


def test_offsetylen_se_sale_del_stride(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["offset"] = 67           # 67 + 2 > 68
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("se sale del stride" in i for i in issues)


def test_fila_fuera_de_rango(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["row"] = 4600
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("fuera de rango" in i for i in issues)


def test_falta_container_md5(tmp_path):
    doc = _mod_minimo()
    doc["game"].pop("container_md5")
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("container_md5" in i for i in issues)


def test_md5_con_formato_invalido(tmp_path):
    doc = _mod_minimo()
    doc["game"]["container_md5"]["LD_C0_R.BIN"] = "xyz"
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("32 caracteres hex" in i for i in issues)


def test_valor_fuera_de_rango_del_tipo(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["value"] = "70000"       # no cabe en u16
    ok, issues = _validar(doc, tmp_path)
    assert not ok and any("fuera de rango para u16" in i for i in issues)


def test_json_invalido(tmp_path):
    ruta = os.path.join(str(tmp_path), "mod.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("{ no es json")
    with pytest.raises(ModError) as exc:
        load_mod(ruta)
    assert "JSON invalido" in str(exc.value)


def test_tabla_sin_geometria_avisa_pero_no_rompe(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["table"] = 12000
    ok, issues = _validar(doc, tmp_path)
    assert ok
    assert any("no tiene geometria declarada" in i for i in issues)


def test_confidence_guess_avisa(tmp_path):
    doc = _mod_minimo()
    doc["edits"][0]["confidence"] = "guess"
    ok, issues = _validar(doc, tmp_path)
    assert ok
    assert any("confidence=guess" in i for i in issues)


def test_mod_sin_ediciones_avisa(tmp_path):
    doc = _mod_minimo()
    doc["edits"] = []
    ok, issues = _validar(doc, tmp_path)
    assert ok and any("no declara ninguna edicion" in i for i in issues)


# --------------------------------------------------------------------------
# Contra el contenedor sintetico
# --------------------------------------------------------------------------

def _contenedor_sintetico(tmp_path):
    payload = helpers.records_payload({1: b"\x2a\x00" + b"\x00" * 4})
    return helpers.make_container(str(tmp_path / "c"), {1: b"x" * 40,
                                                        helpers.REC_TABLE: payload})


def test_md5_del_contenedor_distinto(tmp_path):
    with helpers.records_spec():
        cont = _contenedor_sintetico(tmp_path)
        doc = helpers.base_doc(cont)
        doc["game"]["container_md5"]["LD_C0_R.BIN"] = "f" * 32
        doc["edits"] = [{"table": helpers.REC_TABLE, "row": 1, "offset": 0,
                         "type": "u16", "expect": "42", "value": "43", "why": "t"}]
        ok, issues = _validar(doc, tmp_path, cont)
        assert not ok and any("esperaba" in i and "encontre" in i for i in issues)


def test_expect_correcto_pasa(tmp_path):
    with helpers.records_spec():
        cont = _contenedor_sintetico(tmp_path)
        doc = helpers.base_doc(cont)
        doc["edits"] = [{"table": helpers.REC_TABLE, "row": 1, "offset": 0,
                         "type": "u16", "expect": "42", "value": "43", "why": "t"}]
        ok, issues = _validar(doc, tmp_path, cont)
        assert ok, issues


def test_expect_incorrecto_dice_que_esperaba_y_que_encontro(tmp_path):
    with helpers.records_spec():
        cont = _contenedor_sintetico(tmp_path)
        doc = helpers.base_doc(cont)
        doc["edits"] = [{"table": helpers.REC_TABLE, "row": 1, "offset": 0,
                         "type": "u16", "expect": "7", "value": "43", "why": "t"}]
        ok, issues = _validar(doc, tmp_path, cont)
        assert not ok
        texto = "\n".join(issues)
        assert "esperaba 7" in texto and "encontre 42" in texto


# --------------------------------------------------------------------------
# Los tres ejemplos del repo, contra el dump real
# --------------------------------------------------------------------------

@necesita_dump
@pytest.mark.parametrize("carpeta", sorted(os.listdir(EJEMPLOS)))
def test_ejemplos_del_repo_validan(carpeta):
    ruta = os.path.join(EJEMPLOS, carpeta)
    if not os.path.isdir(ruta):
        pytest.skip("no es una carpeta de mod")
    mod = load_mod(ruta)
    cont = paths.resolve_container(None)
    rep = validate(mod, cont)
    assert rep.ok, [str(i) for i in rep.issues]

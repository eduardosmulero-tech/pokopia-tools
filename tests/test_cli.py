"""CLI `pkp`: superficie de comandos y codigos de salida."""

from __future__ import annotations

import json
import os

import pytest

from pokopia import paths
from pokopia.cli import main

from tests import helpers

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAY_DUMP = os.path.isfile(os.path.join(paths.configured_romfs(), paths.IDX_NAME))
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego")


@necesita_dump
def test_info_json(capsys):
    assert main(["info", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["entries"] == 12298
    assert doc["flags"] == {"0": 4169, "1": 8129}
    assert doc["bin"]["md5"] == "358a672d506ce2b0399149ede64a6760"
    assert doc["problems"] == 0


@necesita_dump
def test_table_y_row(capsys):
    assert main(["table", "983", "--rows", "1324:1325"]) == 0
    salida = capsys.readouterr().out
    assert "count 4600" in salida and "nameIndex=2278" in salida
    assert main(["row", "983", "1324"]) == 0
    salida = capsys.readouterr().out
    assert "nameIndex" in salida and "2278" in salida


@necesita_dump
def test_dump_de_una_entrada(tmp_path, capsys):
    destino = str(tmp_path / "e40.bin")
    assert main(["dump", "40", destino]) == 0
    assert os.path.getsize(destino) == 327744


@necesita_dump
def test_repack_identico(tmp_path, capsys):
    salida = str(tmp_path / "repack")
    assert main(["repack", salida]) == 0
    texto = capsys.readouterr().out
    assert texto.count("IDENTICO") == 2


def test_mod_apply_yes_exige_container_explicito(capsys):
    assert main(["mod", "apply", "ejemplos/editar-fila", "--yes"]) == 2
    assert "--container" in capsys.readouterr().err


@necesita_dump
def test_mod_apply_dry_run_sin_container_usa_el_dump_y_no_escribe(capsys):
    cont = paths.resolve_container(None)
    antes = paths.container_md5(cont)
    assert main(["mod", "apply", "ejemplos/editar-fila", "--dry-run"]) == 0
    salida = capsys.readouterr().out
    assert "no se ha escrito nada" in salida
    assert "solo lectura (dump)" in salida
    assert paths.container_md5(cont) == antes


def test_mod_apply_yes_y_dry_run_incompatibles(tmp_path, capsys):
    doc = {"mod_format": 1}
    ruta = helpers.write_mod(str(tmp_path / "m"), doc)
    with pytest.raises(SystemExit) as exc:
        main(["mod", "apply", os.path.dirname(ruta), "--container", str(tmp_path),
              "--yes", "--dry-run"])
    assert exc.value.code == 2


def test_mod_new_escribe_esqueleto(tmp_path, capsys):
    with helpers.records_spec():
        cont = helpers.make_container(str(tmp_path / "c"), {1: b"x" * 10})
        destino = str(tmp_path / "nuevo")
        assert main(["mod", "new", "mi-mod", "--dir", destino,
                     "--container", cont.dir]) == 0
        doc = json.load(open(os.path.join(destino, "mod.json"), encoding="utf-8"))
        assert doc["mod_format"] == 1
        assert doc["edits"] == []
        assert doc["game"]["container_md5"] == paths.container_md5(cont)
    # no sobrescribe
    assert main(["mod", "new", "mi-mod", "--dir", destino,
                 "--container", cont.dir]) == 2


def test_mod_validate_json_de_un_mod_invalido(tmp_path, capsys):
    doc = {"mod_format": 1, "name": "x", "version": "0.1.0", "authors": [],
           "game": {"title": "t", "version": "2.0.1a",
                    "container_md5": {"LD_C0_R.BIN": "0" * 32, "LI_C0_R.IDX": "1" * 32}},
           "edits": [{"table": 983, "row": 0, "offset": 0, "type": "u16",
                      "value": "1", "why": "sin expect"}]}
    ruta = helpers.write_mod(str(tmp_path / "m"), doc)
    assert main(["mod", "validate", os.path.dirname(ruta), "--no-container", "--json"]) == 1
    salida = json.loads(capsys.readouterr().out)
    assert salida["ok"] is False
    assert any("expect" in i["message"] for i in salida["issues"])


def test_mod_merge_conflicto_sale_con_codigo_1(tmp_path, capsys):
    with helpers.records_spec():
        payload = helpers.records_payload({1: b"\x00" * 8})
        cont = helpers.make_container(str(tmp_path / "c"), {helpers.REC_TABLE: payload})
        edit = {"table": helpers.REC_TABLE, "row": 1, "offset": 0, "type": "u32",
                "expect": "0", "value": "7", "why": "t"}
        a = os.path.dirname(helpers.write_mod(str(tmp_path / "a"), {
            **helpers.base_doc(cont, "a"), "edits": [edit]}))
        otra = dict(edit, value="9")
        b = os.path.dirname(helpers.write_mod(str(tmp_path / "b"), {
            **helpers.base_doc(cont, "b"), "edits": [otra]}))
        assert main(["mod", "merge", a, b, "--container", cont.dir]) == 1
        assert "CONFLICTO" in capsys.readouterr().out

        ok_b = os.path.dirname(helpers.write_mod(str(tmp_path / "b2"), {
            **helpers.base_doc(cont, "b2"), "edits": [dict(edit, row=2)]}))
        salida = str(tmp_path / "compuesto")
        assert main(["mod", "merge", a, ok_b, "-o", salida,
                     "--container", cont.dir]) == 0
        assert os.path.isfile(os.path.join(salida, "mod.json"))


def test_apply_en_arbol_protegido_sale_con_2(tmp_path, capsys, monkeypatch):
    with helpers.records_spec():
        payload = helpers.records_payload({1: b"\x2a\x00"})
        cont = helpers.make_container(str(tmp_path / "c"),
                                     {helpers.REC_TABLE: payload})
        doc = helpers.base_doc(cont, "m")
        doc["edits"] = [{"table": helpers.REC_TABLE, "row": 1, "offset": 0,
                         "type": "u16", "expect": "42", "value": "43", "why": "t"}]
        moddir = os.path.dirname(helpers.write_mod(str(tmp_path / "m"), doc))
        monkeypatch.setattr(paths, "PROTECTED_TREES", (cont.dir,))
        assert main(["mod", "apply", moddir, "--container", cont.dir, "--yes"]) == 2
        assert "destino protegido" in capsys.readouterr().err

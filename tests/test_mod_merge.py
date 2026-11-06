"""Composicion de mods: conflictos, avisos y mod compuesto aplicable."""

from __future__ import annotations

import json
import os

import pytest

from pokopia.mod import apply_mod, load_mod, merge_mods, validate

from tests import helpers


@pytest.fixture()
def contenedor(tmp_path):
    with helpers.records_spec():
        payload = helpers.records_payload({1: b"\x00" * 8, 2: b"\x00" * 8})
        cont = helpers.make_container(str(tmp_path / "copia"),
                                     {helpers.REC_TABLE: payload})
        yield cont


def _mod(cont, nombre, edits) -> str:
    doc = helpers.base_doc(cont, nombre)
    doc["edits"] = edits
    ruta = helpers.write_mod(str(cont.dir + "-mods-" + nombre), doc)
    return os.path.dirname(ruta)


def _edit(row, offset, expect="0", value="7", typ="u32"):
    return {"table": helpers.REC_TABLE, "row": row, "offset": offset, "type": typ,
            "expect": expect, "value": value, "why": "prueba"}


def test_filas_distintas_se_componen(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])
    b = _mod(contenedor, "mod-b", [_edit(2, 0, value="9")])
    out = str(tmp_path / "compuesto")
    res = merge_mods(a, b, out, container_dir=contenedor.dir)
    assert res.ok, [str(i) for i in res.report.issues]
    assert len(res.doc["edits"]) == 2
    assert res.written and os.path.isfile(res.written)
    assert res.report.warnings == []

    mod = load_mod(out)
    assert validate(mod, contenedor).ok
    aplicado = apply_mod(mod, contenedor.dir, write=True)
    assert aplicado["ok"], aplicado["issues"]
    payload = helpers.read_payload(contenedor, helpers.REC_TABLE)
    assert helpers.u32(payload, 64 + 1 * 68) == 7
    assert helpers.u32(payload, 64 + 2 * 68) == 9


def test_misma_fila_mismo_offset_valores_distintos_es_conflicto(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])
    b = _mod(contenedor, "mod-b", [_edit(1, 0, value="9")])
    res = merge_mods(a, b, str(tmp_path / "conf"), container_dir=contenedor.dir)
    assert not res.ok
    texto = "\n".join(str(i) for i in res.report.issues)
    assert "solape exacto" in texto
    assert not os.path.exists(os.path.join(str(tmp_path / "conf"), "mod.json"))


def test_mismo_valor_tambien_es_conflicto(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])
    b = _mod(contenedor, "mod-b", [_edit(1, 0, value="7")])
    res = merge_mods(a, b, None, container_dir=contenedor.dir)
    assert not res.ok and any("solape exacto" in str(i) for i in res.report.issues)


def test_solape_parcial_es_conflicto(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])          # bytes 0..4
    b = _mod(contenedor, "mod-b", [_edit(1, 2, value="9")])          # bytes 2..6
    res = merge_mods(a, b, None, container_dir=contenedor.dir)
    assert not res.ok and any("solape parcial" in str(i) for i in res.report.issues)


def test_misma_fila_offsets_distintos_avisa_y_compone(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])
    b = _mod(contenedor, "mod-b", [_edit(1, 4, value="9")])
    res = merge_mods(a, b, None, container_dir=contenedor.dir)
    assert res.ok, [str(i) for i in res.report.issues]
    assert any("misma fila" in str(i) for i in res.report.warnings)


def test_md5_distinto_entre_mods_es_conflicto(contenedor, tmp_path):
    a = _mod(contenedor, "mod-a", [_edit(1, 0, value="7")])
    b = _mod(contenedor, "mod-b", [_edit(2, 0, value="9")])
    ruta_b = os.path.join(b, "mod.json")
    doc = json.load(open(ruta_b, encoding="utf-8"))
    doc["game"]["container_md5"] = {"LD_C0_R.BIN": "a" * 32, "LI_C0_R.IDX": "b" * 32}
    json.dump(doc, open(ruta_b, "w", encoding="utf-8"))
    res = merge_mods(a, b, None, container_dir=contenedor.dir, check_container=False)
    assert not res.ok
    assert any("contenedores distintos" in str(i) for i in res.report.issues)

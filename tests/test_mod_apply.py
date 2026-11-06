"""Aplicacion de un mod sobre una COPIA (dry-run, --yes, guardas y verificacion)."""

from __future__ import annotations

import os

import pytest

from pokopia import paths, tables
from pokopia.container import compare_payloads
from pokopia.mod import GuardError, apply_mod, load_mod, validate

from tests import helpers


@pytest.fixture()
def contenedor(tmp_path):
    """Contenedor sintetico con una tabla de registros (#5) y una de texto (#6)."""
    with helpers.records_spec(), helpers.text_spec():
        payload_rec = helpers.records_payload({1: b"\x2a\x00\x00\x00\x00\x00\x00\x00"})
        slots = [b"slot-%d" % i if i % 3 else b"" for i in range(helpers.TEXT_SLOTS)]
        payload_txt = helpers.text_payload(slots)
        cont = helpers.make_container(
            str(tmp_path / "copia"),
            {helpers.REC_TABLE: payload_rec, helpers.TEXT_TABLE: payload_txt})
        yield cont, slots


def _mod_bytes(cont, *, expect="42", value="43", offset=0, row=1, table=None):
    doc = helpers.base_doc(cont, "mod-bytes")
    doc["edits"] = [{"table": table or helpers.REC_TABLE, "row": row, "offset": offset,
                     "type": "u16", "expect": expect, "value": value, "why": "prueba"}]
    return doc


def _mod_texto(cont, *, expect="", value="HOLA", text_id=4, slot=0):
    doc = helpers.base_doc(cont, "mod-texto")
    doc["text"] = [{"table": helpers.TEXT_TABLE, "id": text_id, "slot": slot,
                    "expect": expect, "value": value, "why": "prueba"}]
    return doc


def _guardar(doc, tmp_path, name="mod.json") -> str:
    ruta = helpers.write_mod(str(tmp_path / "mods" / doc["name"]), doc)
    return os.path.dirname(ruta)


def test_dry_run_no_toca_ningun_fichero(contenedor, tmp_path):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont), tmp_path))
    antes = paths.container_md5(cont)
    res = apply_mod(mod, cont.dir, write=False)
    assert res["ok"], res["issues"]
    assert res["dry_run"] and not res["written"]
    assert paths.container_md5(cont) == antes
    assert not [p for p in os.listdir(cont.dir) if p.startswith(".pkp-tmp")]
    assert not os.path.exists(os.path.join(cont.dir, ".pkp-backup"))


def test_apply_yes_cambia_solo_lo_declarado(contenedor, tmp_path):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont), tmp_path))
    antes = paths.container_md5(cont)
    payload_antes = helpers.read_payload(cont, helpers.REC_TABLE)

    res = apply_mod(mod, cont.dir, write=True)
    assert res["ok"], res["issues"]
    assert res["written"]
    assert paths.container_md5(cont) != antes

    payload_despues = helpers.read_payload(cont, helpers.REC_TABLE)
    assert len(payload_despues) == len(payload_antes)
    distintos = [i for i in range(len(payload_antes))
                 if payload_antes[i] != payload_despues[i]]
    assert distintos == [64 + 1 * 68 + 0], distintos   # solo el u16 declarado
    assert helpers.u32(payload_despues, 64 + 1 * 68) == 43
    assert res["backup"] and os.path.isdir(res["backup"])
    assert len(res["undo"]) == 2 and res["undo"][0].startswith("cp ")


def test_apply_yes_sin_backup(contenedor, tmp_path):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont), tmp_path))
    res = apply_mod(mod, cont.dir, write=True, keep_backup=False)
    assert res["ok"] and res["backup"] is None and res["undo"] == []
    assert not os.path.exists(os.path.join(cont.dir, ".pkp-backup"))


def test_expect_incorrecto_se_rechaza_sin_escribir(contenedor, tmp_path):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont, expect="7"), tmp_path))
    antes = paths.container_md5(cont)
    res = apply_mod(mod, cont.dir, write=True)
    assert not res["ok"]
    texto = "\n".join(i["message"] for i in res["issues"])
    assert "esperaba" in texto and "encontre" in texto
    assert paths.container_md5(cont) == antes


def test_no_escribe_en_arbol_protegido(contenedor, tmp_path, monkeypatch):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont), tmp_path))
    antes = paths.container_md5(cont)
    monkeypatch.setattr(paths, "PROTECTED_TREES", (cont.dir,))
    with pytest.raises(GuardError):
        apply_mod(mod, cont.dir, write=True)
    monkeypatch.undo()
    assert paths.container_md5(cont) == antes


def test_texto_edita_solo_su_slot(contenedor, tmp_path):
    cont, slots = contenedor
    mod = load_mod(_guardar(_mod_texto(cont), tmp_path))
    payload_antes = helpers.read_payload(cont, helpers.TEXT_TABLE)
    res = apply_mod(mod, cont.dir, write=True)
    assert res["ok"], res["issues"]
    tabla = res["tables"][0]
    assert tabla["pool_prefix_identical"] is True
    assert tabla["slots_changed"] and tabla["slots_changed"][0]["slot"] == 0

    payload_despues = helpers.read_payload(cont, helpers.TEXT_TABLE)
    assert payload_despues[:tables.get(helpers.TEXT_TABLE).pool_start] == \
        payload_antes[:tables.get(helpers.TEXT_TABLE).pool_start]
    slots_nuevos, _ = tables.parse_pool(tables.get(helpers.TEXT_TABLE), payload_despues)
    assert slots_nuevos[0] == b"HOLA"
    assert slots_nuevos[1:] == slots[1:]
    assert len(slots_nuevos) == len(slots)


def test_texto_expect_incorrecto(contenedor, tmp_path):
    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_texto(cont, expect="lo que no hay"), tmp_path))
    antes = paths.container_md5(cont)
    res = apply_mod(mod, cont.dir, write=True)
    assert not res["ok"]
    texto = "\n".join(i["message"] for i in res["issues"])
    assert "esperaba" in texto and "encontre otro texto" in texto
    assert paths.container_md5(cont) == antes


def test_verificacion_byte_a_byte_con_el_lector(contenedor, tmp_path):
    """Tras --yes, el lector independiente ve exactamente una entrada distinta."""
    import subprocess
    import sys

    cont, _ = contenedor
    mod = load_mod(_guardar(_mod_bytes(cont), tmp_path))
    original_dir = str(tmp_path / "original")
    os.makedirs(original_dir, exist_ok=True)
    for name in (paths.BIN_NAME, paths.IDX_NAME):
        with open(os.path.join(cont.dir, name), "rb") as src, \
                open(os.path.join(original_dir, name), "wb") as dst:
            dst.write(src.read())
    res = apply_mod(mod, cont.dir, write=True)
    assert res["ok"]
    lector = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tests", "independent_reader.py")
    salida = subprocess.run(
        [sys.executable, lector, cont.idx, cont.bin, "--contra",
         os.path.join(original_dir, paths.IDX_NAME),
         os.path.join(original_dir, paths.BIN_NAME)],
        capture_output=True, text=True)
    assert salida.returncode == 1, salida.stderr      # hay diferencias, esperadas
    assert '"distintas": 1' in salida.stdout, salida.stdout
    comp = compare_payloads(os.path.join(original_dir, paths.IDX_NAME),
                            os.path.join(original_dir, paths.BIN_NAME),
                            cont.idx, cont.bin)
    assert comp["different"] == [helpers.REC_TABLE]

"""El vehiculo B3 (`ejemplos/b3-texto-nuevo`): bloque poblado y alcanzable.

Que fija este fichero, y por que merece test:

- la cadena que hace visible el texto — `hueco 3 -> id 14 -> #983 fila 14 -> +34
  -> id de texto 2489 -> #4650` — se **recalcula del dump**, no se copia del
  comentario del ejemplo: si el ejemplo se queda apuntando a otro bloque, el test
  rompe;
- el bloque que declara el ejemplo es **poblado** (mascara `0x2D`: +0, +2, +3 y +5
  con contenido) y el ejemplo escribe **exactamente** esos cuatro slots, que es lo
  que quita el riesgo declarado en A1 (no hay que adivinar que grupo pinta el
  juego);
- el ensayo cambia **solo** lo declarado y el payload crece **solo** el largo de lo
  escrito;
- con el digest cambiado en un caracter, el comando **rechaza** (exit 1) y no toca
  el contenedor.

Ningun literal de este fichero es contenido del juego: ids, offsets y longitudes.
"""

from __future__ import annotations

import json
import os

import pytest

from pokopia import paths, tables
from pokopia.cli import main
from pokopia.container import read_container, unpack_entry
from pokopia.mod import load_mod
from pokopia.mod.apply import make_plan, verify_plan
from pokopia.mod.errors import ModError
from pokopia.mod.manifest import ContainerView

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EJEMPLO = os.path.join(RAIZ, "ejemplos", "b3-texto-nuevo")

#: Fila de `#983` del objeto del hueco 0 del inventario de la partida de
#: referencia (id de objeto 63, docs/SPEC-NAMES.md 9). Solo el numero.
FILA_ITEM = 63
#: Mascara de slots no vacios de un id con nombre en `#4650` (SPEC-NAMES.md 6.1).
MASCARA_ES = (True, False, True, True, False, True)

HAY_DUMP = os.path.isfile(os.path.join(paths.configured_romfs(), paths.IDX_NAME))
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego")


def _manifiesto() -> dict:
    with open(os.path.join(EJEMPLO, "mod.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _view() -> ContainerView:
    return ContainerView(paths.resolve_container(None))


def _bloque(view: ContainerView, text_id: int):
    spec = tables.get(4650)
    assert spec is not None
    payload = view.payload(4650)
    slots, _ = tables.parse_pool(spec, payload)
    return spec, slots, tables.block_slots(spec, slots, text_id)


def _id_de_texto_del_objeto(view: ContainerView, fila: int) -> int:
    """`#983 fila i` -> `+34` u16 -> id de texto `+3` (SPEC-NAMES.md 6.3)."""
    spec = tables.get(983)
    assert spec is not None
    fila_bytes = tables.read_row(spec, view.payload(983), fila)
    return int.from_bytes(fila_bytes[34:36], "little") + 3


# ---------------------------------------------------------------------------
# La cadena y el bloque
# ---------------------------------------------------------------------------

@necesita_dump
def test_el_ejemplo_apunta_al_bloque_del_objeto_declarado():
    doc = _manifiesto()
    view = _view()
    esperado = _id_de_texto_del_objeto(view, FILA_ITEM)
    declarados = {e["id"] for e in doc["text"]}
    assert declarados == {esperado}, (
        "el ejemplo escribe en %s y la cadena de la fila %d da %d"
        % (sorted(declarados), FILA_ITEM, esperado))


@necesita_dump
def test_el_bloque_es_poblado_y_el_ejemplo_escribe_los_slots_llenos():
    doc = _manifiesto()
    view = _view()
    text_id = _id_de_texto_del_objeto(view, FILA_ITEM)
    spec, _slots, bloque = _bloque(view, text_id)

    assert len(bloque) == tables.SLOTS_PER_BLOCK
    assert tuple(bool(s) for s in bloque) == MASCARA_ES, (
        "el bloque no tiene la mascara 0x2D de #4650: %s"
        % [len(s) for s in bloque])
    escritos = sorted(e["slot"] for e in doc["text"])
    llenos = [i for i, s in enumerate(bloque) if s]
    assert escritos == llenos, "el ejemplo escribe %s y el bloque llena %s" % (escritos, llenos)


@necesita_dump
def test_el_digest_del_ejemplo_es_el_del_bloque_pristino():
    doc = _manifiesto()
    view = _view()
    text_id = _id_de_texto_del_objeto(view, FILA_ITEM)
    spec, slots, _bloque_bytes = _bloque(view, text_id)
    real = tables.block_sha256(spec, slots, text_id)
    for entrada in doc["text"]:
        assert entrada["expect_sha256"] == real
    # y el manifiesto no lleva contenido: el valor es el marcador, no el texto de
    # origen (que este test nunca lee).
    assert {e["value"] for e in doc["text"]} == {"MOD-TEXT-NUEVO"}


# ---------------------------------------------------------------------------
# El ensayo: solo lo declarado, y el tamano sube solo lo escrito
# ---------------------------------------------------------------------------

@necesita_dump
def test_el_ensayo_cambia_solo_lo_declarado_y_crece_lo_escrito():
    doc = _manifiesto()
    view = _view()
    cont = view.container
    mod = load_mod(EJEMPLO)
    plan = make_plan(mod, cont, view=view)
    check = verify_plan(plan, view)
    assert check["ok"], check["errors"]

    info = check["tables"][4650]
    text_id = _id_de_texto_del_objeto(view, FILA_ITEM)
    spec, slots, _bloque_bytes = _bloque(view, text_id)
    base = tables.SLOTS_PER_BLOCK * (text_id - tables.TEXT_FIRST_ID)

    assert info["pool_prefix_identical"] is True
    assert info["roundtrip_ok"] is True
    assert info["slots_total"][0] == info["slots_total"][1]

    declarados = {(e["id"], e["slot"]): e["value"] for e in doc["text"]}
    cambios = info["slots_changed"]
    assert [c["slot"] for c in cambios] == sorted(base + s for (_i, s) in declarados)

    delta_slots = sum(len(v.encode("utf-8")) - c["old_len"] for c in cambios
                      for (_i, s), v in declarados.items() if base + s == c["slot"])
    assert info["new_size"] - info["old_size"] == delta_slots
    for c in cambios:
        assert c["new_len"] == len(declarados[(text_id, c["slot"] - base)])


# ---------------------------------------------------------------------------
# Control negativo: un caracter del digest
# ---------------------------------------------------------------------------

@necesita_dump
def test_digest_cambiado_en_un_caracter_rechaza_y_no_escribe(tmp_path):
    doc = _manifiesto()
    for entrada in doc["text"]:
        digest = entrada["expect_sha256"]
        entrada["expect_sha256"] = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    carpeta = tmp_path / "b3-digest-malo"
    carpeta.mkdir()
    (carpeta / "mod.json").write_text(json.dumps(doc), encoding="utf-8")

    cont = paths.resolve_container(None)
    antes = paths.container_md5(cont)
    assert main(["mod", "apply", str(carpeta), "--container", cont.dir, "--dry-run"]) == 1
    assert paths.container_md5(cont) == antes

    with pytest.raises(ModError) as exc:
        make_plan(load_mod(str(carpeta)), cont, view=_view())
    assert exc.value.code == "mod.text.expect"
    assert "sha256" in str(exc.value)


def test_el_ejemplo_no_lleva_ficheros_de_contenido():
    """El vehiculo es un manifiesto y su LEEME: ni un fichero del juego."""
    assert sorted(os.listdir(EJEMPLO)) == ["LEEME.md", "mod.json"]

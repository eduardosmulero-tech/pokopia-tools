"""El mod real de contenido `mods/regalo-dipplin` contra una COPIA del contenedor.

Que se comprueba aqui, y por que:

- que el manifiesto valida contra el build declarado (md5 y `expect` reales);
- que la fila destino estaba **sin nombre** antes del mod (nameIndex 0 -> id de
  texto 3, y los ids 0..3 no tienen bloque: docs/SPEC-NAMES.md §6);
- que el unico campo `verified` es el `+34 u16 nameIndex`, con el valor que la
  regla del repo exige (`r = nameIndex + 3`, §6.3);
- que el plan del mod escribe **solo** dentro de los rangos declarados y que la
  fila resultante es el clon del donante con el `nameIndex` propio;
- que el dry-run no toca ni un byte.

Sin copia del contenedor en `build/copia` (o con otro md5) los tests **se saltan
con motivo**: el dump del juego no viaja en el repo
(docs/NORMA-CONTENIDO-Y-PUBLICACION.md §4).
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from pokopia import paths
from pokopia.mod import apply_mod, load_mod, validate
from pokopia.mod.apply import make_plan
from pokopia.tables import registry

from tests import helpers

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(RAIZ, "mods", "regalo-dipplin")
COPIA = os.path.join(RAIZ, "build", "copia")

TABLA = 983
TABLA_TEXTO_ES = 4650
NAME_INDEX = 34
FILA_DESTINO = 0
FILA_DONANTE = 2234
VALOR_NAME_INDEX = 1014          # id de texto = 1014 + 3 = 1017

MD5 = {
    "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
    "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8",
}


def _motivo_salto() -> str | None:
    if not os.path.isfile(os.path.join(COPIA, paths.IDX_NAME)):
        return "sin copia del contenedor en build/copia"
    cont = paths.Container(COPIA, os.path.join(COPIA, paths.IDX_NAME),
                           os.path.join(COPIA, paths.BIN_NAME))
    real = paths.container_md5(cont)
    if real != MD5:
        return "build/copia no es el build declarado por el mod (%s)" % real
    return None


MOTIVO = _motivo_salto()
necesita_copia = pytest.mark.skipif(MOTIVO is not None, reason=MOTIVO or "")


@pytest.fixture(scope="module")
def manifiesto() -> dict:
    if not os.path.isfile(os.path.join(MOD, "mod.json")):
        # `mods/` es material montado del repo y no viaja en la release
        # (lista blanca de `tools/build_release.py`); en el arbol siempre esta.
        pytest.skip("mods/regalo-dipplin no viaja en el paquete (lista blanca)")
    with open(os.path.join(MOD, "mod.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def mod():
    return load_mod(MOD)


@pytest.fixture(scope="module")
def contenedor() -> paths.Container:
    return paths.resolve_container(COPIA)


@pytest.fixture(scope="module")
def payload(contenedor) -> bytes:
    return helpers.read_payload(contenedor, TABLA)


# --------------------------------------------------------------------------
# Manifiesto (no necesita contenedor)
# --------------------------------------------------------------------------

def test_el_manifiesto_es_valido_como_documento(manifiesto):
    assert manifiesto["mod_format"] == 1
    assert manifiesto["name"] == "regalo-dipplin"
    assert manifiesto["game"]["container_md5"] == MD5
    assert manifiesto["edits"], "un mod sin ediciones no hace nada"
    assert manifiesto["text"] == [], "este mod no escribe en tablas de texto"


def test_no_hay_texto_del_juego_en_el_manifiesto(manifiesto):
    """Solo ids, offsets, valores y prosa del autor: ninguna tabla de texto."""
    assert all(e["table"] == TABLA for e in manifiesto["edits"])
    for edit in manifiesto["edits"]:
        assert set(edit) <= {"table", "row", "offset", "type", "expect", "value",
                             "why", "confidence", "note"}
        assert edit["why"].strip()


def test_un_solo_campo_verified_y_es_el_name_index(manifiesto):
    verified = [e for e in manifiesto["edits"] if e.get("confidence") == "verified"]
    assert len(verified) == 1, verified
    edit = verified[0]
    assert (edit["table"], edit["row"], edit["offset"], edit["type"]) == \
        (TABLA, FILA_DESTINO, NAME_INDEX, "u16")
    assert int(edit["value"]) == VALOR_NAME_INDEX
    assert "§6.3" in edit["why"]


def test_los_demas_campos_van_como_guess(manifiesto):
    guess = [e for e in manifiesto["edits"] if e.get("confidence") == "guess"]
    assert len(guess) == len(manifiesto["edits"]) - 1
    for edit in guess:
        assert edit["offset"] not in (NAME_INDEX, NAME_INDEX + 1), \
            "los bytes del nameIndex los cubre la edicion verified"


def test_ninguna_edicion_se_sale_del_stride(manifiesto):
    spec = registry.get(TABLA)
    assert spec is not None
    for edit in manifiesto["edits"]:
        tam = 1 if edit["type"] == "u8" else 2
        assert 0 <= edit["row"] < spec.count
        assert edit["offset"] + tam <= spec.stride


# --------------------------------------------------------------------------
# Contra la copia del contenedor
# --------------------------------------------------------------------------

@necesita_copia
def test_valida_contra_la_copia(mod, contenedor):
    rep = validate(mod, contenedor)
    assert rep.ok, [str(i) for i in rep.issues]
    assert not rep.errors
    avisos = [str(i) for i in rep.issues]
    assert sum("confidence=guess" in a for a in avisos) == 17


@necesita_copia
def test_la_fila_destino_estaba_sin_nombre(payload):
    spec = registry.get(TABLA)
    assert spec is not None
    fila = registry.read_row(spec, payload, FILA_DESTINO)
    name_index = struct.unpack_from("<H", fila, NAME_INDEX)[0]
    assert name_index == 0
    # nameIndex 0 -> id de texto 3, y los ids 0..3 no tienen bloque (SPEC-NAMES §6)
    assert name_index + 3 < registry.TEXT_FIRST_ID
    # lo unico no cero de la fila virgen es el centinela de +32..+33
    no_cero = {off for off, b in enumerate(fila) if b}
    assert no_cero <= {32, 33}, no_cero


@necesita_copia
def test_el_texto_destino_existe_y_tiene_sus_seis_slots(contenedor):
    spec = registry.get(TABLA_TEXTO_ES)
    assert spec is not None
    slots, _terminado = registry.parse_pool(spec, helpers.read_payload(contenedor, TABLA_TEXTO_ES))
    k = registry.slot_ordinal(spec, VALOR_NAME_INDEX + 3)
    bloque = slots[k:k + 6]
    assert len(bloque) == 6
    assert bloque[0], "el slot singular del id destino esta vacio en este build"


@necesita_copia
def test_el_plan_cae_dentro_de_los_rangos_declarados(mod, contenedor, payload, manifiesto):
    spec = registry.get(TABLA)
    assert spec is not None
    plan = make_plan(mod, contenedor)
    declarados = sorted(
        spec.row_offset(e["row"]) + e["offset"] for e in manifiesto["edits"])
    escritos = sorted(w.abs_offset for w in plan.writes)
    assert escritos == declarados

    antes = registry.read_row(spec, payload, FILA_DESTINO)
    despues = plan.updated[TABLA][spec.row_offset(FILA_DESTINO):][:spec.stride]
    distintos = [i for i in range(spec.stride) if antes[i] != despues[i]]
    assert distintos == [8, 16, 17, 20, 24, 26, 27, 30, 32, 33, 34, 35,
                         36, 37, 38, 42, 43, 58, 66], distintos
    assert struct.unpack_from("<H", despues, NAME_INDEX)[0] == VALOR_NAME_INDEX


@necesita_copia
def test_la_fila_nueva_es_el_clon_del_donante(mod, contenedor, payload):
    """Salvo los dos bytes del nameIndex, la fila nueva es la fila donante."""
    spec = registry.get(TABLA)
    assert spec is not None
    plan = make_plan(mod, contenedor)
    nueva = plan.updated[TABLA][spec.row_offset(FILA_DESTINO):][:spec.stride]
    donante = registry.read_row(spec, payload, FILA_DONANTE)
    # el donante nombra el id de texto 1014 -> +34 = 1014 - 3
    assert struct.unpack_from("<H", donante, NAME_INDEX)[0] == VALOR_NAME_INDEX - 3
    distintos = [i for i in range(spec.stride) if nueva[i] != donante[i]]
    assert distintos == [NAME_INDEX], distintos


@necesita_copia
def test_el_dry_run_no_toca_ni_un_byte(mod, contenedor):
    antes = paths.container_md5(contenedor)
    res = apply_mod(mod, contenedor.dir, write=False)
    assert res["ok"], res["issues"]
    assert res["dry_run"] and not res["written"]
    assert paths.container_md5(contenedor) == antes
    assert not [p for p in os.listdir(contenedor.dir) if p.startswith(".pkp-tmp")]

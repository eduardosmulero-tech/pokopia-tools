"""Tests del parte de progreso: ficheros de zona y contrato del informe.

Cubren los criterios C1 (el parte no publica una lista de «sin medir», sino el motivo de
cada cifra), C2 (confianza y evidencia declaradas), C3 (un save con mas progreso da
cifras mayores) y C4 (el comando no imprime nombres propios).
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import save_fixture as fx  # noqa: E402
from pokopia import save as S  # noqa: E402
from pokopia.save import zones as Z  # noqa: E402
from pokopia.cli import main as cli_main  # noqa: E402


def write_zone(directory: str, page: str, index: int, *,
               declared: int | None = None, body: bytes = b"\x78\x9c\x03\x00") -> str:
    """Fichero de zona sintetico: cabecera de 0x124 B y un cuerpo de relleno.

    El cuerpo **no** se descomprime (serian 138 MB por zona), asi que puede ser
    cualquier cosa: lo que se valida es la cabecera y el tamano declarado.
    """
    os.makedirs(os.path.join(directory, page), exist_ok=True)
    head = bytearray(Z.ZONE_HEADER_SIZE)
    total = Z.ZONE_HEADER_SIZE + len(body)
    struct.pack_into("<i", head, 0x10, total if declared is None else declared)
    path = Z.zone_path(directory, page, index)
    with open(path, "wb") as fh:
        fh.write(bytes(head) + body)
    return path


# ---------------------------------------------------------------------------
# zona: ficheros STGDATnn.BIN
# ---------------------------------------------------------------------------

def test_zonas_cuenta_los_ficheros_de_zona(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(villagers=2))
    report = S.build_report(S.open_page(str(tmp_path)))
    assert report.get("zonas").value == 0
    assert any(k == "zona" for k, _ in report.unmeasured)

    write_zone(str(tmp_path), "G00", 1)
    write_zone(str(tmp_path), "G00", 3)
    report = S.build_report(S.open_page(str(tmp_path)))
    zonas = report.get("zonas")
    assert zonas.value == 2
    assert zonas.total is None
    assert zonas.confidence == "inferred"
    assert "01, 03" in zonas.evidence
    # `zonas` son los ficheros; `zona` (nivel ambiental por zona) sigue sin medirse y
    # se declara aparte: son dos cosas distintas y no se tapa una con la otra.
    assert any(k == "zona" for k, _ in report.unmeasured)


def test_zona_con_cabecera_rota_no_se_cuenta_y_se_declara(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(villagers=1))
    write_zone(str(tmp_path), "G00", 1, declared=0)
    report = S.build_report(S.open_page(str(tmp_path)))
    assert report.get("zonas").value == 0
    assert "no se pudo leer" in report.get("zonas").evidence


def test_zonas_pide_la_pagina_no_el_otro_slot(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(), pages=("G00", "B00"))
    write_zone(str(tmp_path), "G00", 1)
    write_zone(str(tmp_path), "G00", 3)
    write_zone(str(tmp_path), "B00", 7)
    assert S.build_report(S.open_page(str(tmp_path), "G00")).get("zonas").value == 2
    assert S.build_report(S.open_page(str(tmp_path), "B00")).get("zonas").value == 1


# ---------------------------------------------------------------------------
# C3: mas progreso -> cifras mayores
# ---------------------------------------------------------------------------

def test_save_con_mas_progreso_da_cifras_mayores(tmp_path):
    pobre = tmp_path / "pobre"
    rico = tmp_path / "rico"
    pobre.mkdir()
    rico.mkdir()

    fx.make_save(str(pobre), payload=fx.make_payload(
        items={0: (101, 1)}, villagers=2, homes=2, catalogue={101: 0x01}))
    fx.make_save(str(rico), payload=fx.make_payload(
        items={0: (101, 1), 1: (400, 3), 2: (1500, 2)}, villagers=6, homes=7,
        catalogue={101: 0x01, 400: 0x43, 1500: 0x47, 63: 0x01}))
    write_zone(str(pobre), "G00", 1)
    for index in (1, 3, 5):
        write_zone(str(rico), "G00", index)

    chico = S.build_report(S.open_page(str(pobre)))
    grande = S.build_report(S.open_page(str(rico)))
    for clave in ("bolsa", "bolsa_ids", "aldeanos", "casas", "catalogo", "zonas"):
        a = chico.get(clave).value
        b = grande.get(clave).value
        assert b > a, "%s no crece: %d -> %d" % (clave, a, b)


# ---------------------------------------------------------------------------
# C1 y C2: el parte lleva el motivo y la confianza
# ---------------------------------------------------------------------------

def test_el_parte_explica_lo_que_no_se_mide(tmp_path, capsys):
    fx.make_save(str(tmp_path), payload=fx.make_payload(villagers=1))
    write_zone(str(tmp_path), "G00", 1)
    assert cli_main(["progress", "--save", str(tmp_path)]) == 0
    salida = capsys.readouterr().out
    assert "sin medir" not in salida
    for clave in ("peticiones", "coleccionable"):
        linea = [l for l in salida.splitlines()
                 if l.strip().split(":", 1)[0].strip() == clave]
        assert linea, "no hay linea para %s" % clave
        assert "no medido" in linea[0]
        assert len(linea[0].split("—", 1)[-1].strip()) > 30, "el motivo es demasiado corto"
    assert "zonas" in salida and "zona(s)" in salida


def test_json_declara_confianza_y_evidencia_de_zonas(tmp_path, capsys):
    fx.make_save(str(tmp_path), payload=fx.make_payload(villagers=1))
    write_zone(str(tmp_path), "G00", 1)
    assert cli_main(["progress", "--save", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    values = {v["key"]: v for v in doc["values"]}
    assert values["zonas"]["value"] == 1
    assert values["zonas"]["confidence"] == "inferred"
    assert values["zonas"]["evidence"]
    assert {u["key"] for u in doc["unmeasured"]} == {"zona", "peticiones",
                                                    "coleccionable"}
    for u in doc["unmeasured"]:
        assert u["reason"]


# ---------------------------------------------------------------------------
# C4: sin nombres propios
# ---------------------------------------------------------------------------

#: Vocabulario cerrado del parte (formato, cifras e indices). Vive en `tests/`
#: para que el test del CLI y este compartan la misma puerta.
from vocabulario import PERMITIDAS  # noqa: E402


def test_parte_con_zonas_no_imprime_nombres_propios(tmp_path, capsys):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}, villagers=3))
    write_zone(str(tmp_path), "G00", 1)
    write_zone(str(tmp_path), "G00", 3)
    assert cli_main(["progress", "--save", str(tmp_path)]) == 0
    salida = capsys.readouterr().out
    palabras = set(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", salida.lower()))
    assert palabras <= PERMITIDAS, \
        "palabras fuera de la lista: %s" % sorted(palabras - PERMITIDAS)
    assert "zonas" in salida


def test_la_lista_de_palabras_detecta_lo_que_no_es_del_parte():
    """La lista cerrada no es decorativa: una palabra de contenido la rompe."""
    ejemplo = "parte de progreso zona\n  bolsa: 1 colosal"
    palabras = set(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", ejemplo.lower()))
    assert palabras - PERMITIDAS == {"colosal"}

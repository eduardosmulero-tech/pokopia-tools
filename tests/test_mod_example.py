"""`pkp mod example`: el mod de las dos paginas de uso.

Lo que fija: el ejemplo es valido para `load_mod`, no lleva nada del juego (23 B
nuestros), no sobrescribe sin `--forzar` y con `--container` copia los md5.
"""

from __future__ import annotations

import json
import os

import pytest

from pokopia import paths
from pokopia.cli import main
from pokopia.mod import example
from pokopia.mod.manifest import load_mod

from tests import helpers


def leer(destino: str) -> dict:
    with open(os.path.join(destino, "mod.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_escribe_un_mod_valido_con_bytes_nuestros(tmp_path):
    res = example.escribir(os.path.join(str(tmp_path), "mod"))
    assert res["bytes"] == 23
    doc = leer(res["dir"])
    assert doc["mod_format"] == 1
    assert doc["name"] == "ejemplo-overlay"
    assert doc["romfs"][0]["path"] == example.RUTA
    with open(res["payload"], "rb") as fh:
        assert fh.read() == example.PAYLOAD
    mod = load_mod(res["dir"])
    assert mod.report.ok, [str(i) for i in mod.report.issues]
    assert len(mod.romfs) == 1


def test_no_sobrescribe_sin_forzar(tmp_path):
    destino = os.path.join(str(tmp_path), "mod")
    example.escribir(destino)
    with pytest.raises(FileExistsError):
        example.escribir(destino)
    example.escribir(destino, forzar=True)


def test_con_container_copia_los_md5(tmp_path):
    contenedor = helpers.make_container(os.path.join(str(tmp_path), "dump"),
                                        {0: helpers.records_payload({})})
    res = example.escribir(os.path.join(str(tmp_path), "mod"), contenedor.dir)
    assert res["container_md5"] == paths.container_md5(contenedor)
    assert leer(res["dir"])["game"]["container_md5"] == res["container_md5"]


def test_sin_container_usa_el_configurado(tmp_path, monkeypatch):
    contenedor = helpers.make_container(os.path.join(str(tmp_path), "dump"),
                                        {0: helpers.records_payload({})})
    monkeypatch.setenv("PKP_ROMFS", contenedor.dir)
    res = example.escribir(os.path.join(str(tmp_path), "mod"))
    assert res["container_md5"] == paths.container_md5(contenedor)


def test_cli_example_luego_validate(tmp_path):
    destino = os.path.join(str(tmp_path), "mod")
    assert main(["mod", "example", destino]) == 0
    assert main(["mod", "validate", destino, "--no-container", "--no-expect"]) == 0

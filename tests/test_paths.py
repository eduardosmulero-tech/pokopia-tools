"""Rutas por defecto y guardas de escritura: ninguna ruta de esta maquina en el codigo.

Cubren lo que la tarjeta exige que falle si alguien lo rompe:

* C5 — escribir dentro del romfs configurado sigue rechazado, y el mensaje nombra el destino;
* C6 — `PKP_PROTECTED` protege una ruta arbitraria, aunque no sea un romfs.
"""

from __future__ import annotations

import os

import pytest

from pokopia import paths
from pokopia.cli import main
from pokopia.save import page as save_page

from tests import helpers


def test_las_rutas_por_defecto_son_relativas():
    """Un valor absoluto aqui es una ruta local filtrada al repo (NORMA §4)."""
    assert not os.path.isabs(paths.DEFAULT_ROMFS)
    assert not os.path.isabs(save_page.DEFAULT_SAVE)


def test_el_romfs_configurado_sale_de_la_variable_o_del_directorio_de_trabajo(monkeypatch):
    monkeypatch.delenv("PKP_ROMFS", raising=False)
    assert paths.configured_romfs() == paths.DEFAULT_ROMFS
    monkeypatch.setenv("PKP_ROMFS", "otra/carpeta")
    assert paths.configured_romfs() == "otra/carpeta"


def test_romfs_configurado_sigue_siendo_solo_lectura(tmp_path, monkeypatch, capsys):
    """C5: el romfs que se configure, sea cual sea, no se escribe nunca."""
    cont = helpers.make_container(str(tmp_path / "romfs"), {1: b"x" * 10})
    monkeypatch.setenv("PKP_ROMFS", cont.dir)
    destino = os.path.join(cont.dir, "salida.bin")

    with pytest.raises(PermissionError) as exc:
        paths.guard_writable(destino)
    assert destino in str(exc.value), "el mensaje tiene que nombrar el destino"

    # y por la CLI: exit 2, mensaje con el destino, sin traza de Python
    assert main(["dump", "1", destino]) == 2
    err = capsys.readouterr().err
    assert "destino protegido" in err
    assert destino in err


def test_pkp_protected_protege_una_ruta_arbitraria(tmp_path, monkeypatch):
    """C6: cualquier ruta de `PKP_PROTECTED` queda protegida, no solo el romfs."""
    arbol = tmp_path / "arbol-del-juego"
    destino = arbol / "sub" / paths.BIN_NAME
    monkeypatch.setenv(paths.PROTECTED_ENV, str(arbol))

    assert paths.is_protected(str(destino))
    with pytest.raises(PermissionError) as exc:
        paths.guard_writable(str(destino))
    assert str(destino) in str(exc.value)

    # fuera de lo listado no hay proteccion
    paths.guard_writable(str(tmp_path / "trabajo" / paths.BIN_NAME))


def test_pkp_protected_admite_varias_rutas(tmp_path, monkeypatch):
    a = tmp_path / "uno"
    b = tmp_path / "dos"
    monkeypatch.setenv(paths.PROTECTED_ENV, os.pathsep.join([str(a), str(b)]))
    assert paths.is_protected(str(a / "x"))
    assert paths.is_protected(str(b / "x"))
    assert not paths.is_protected(str(tmp_path / "tres" / "x"))

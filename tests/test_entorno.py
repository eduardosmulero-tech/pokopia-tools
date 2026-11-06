"""Guardas del entorno: sin ellas, «los tests pasan» es una foto de una maquina.

Tres comprobaciones, cada una con su defecto detras (informe 4.1):

1. el paquete `tests` que se importa es el del repo, no el de otro entorno;
2. el interprete es el declarado en `pyproject.toml` (`requires-python`);
3. la zlib es la declarada en `[tool.pokopia] zlib`. Si no lo es, la suite no
   firma identidad byte a byte: el test que la sostiene se **salta con motivo**,
   no pasa en verde.
"""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib
import zlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CFG = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
PY_DECLARADO = CFG["project"]["requires-python"]
ZLIB_DECLARADA = CFG["tool"]["pokopia"]["zlib"]


def _rango(expresion: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Convierte '>=3.11,<3.12' en ((3,11),(3,12))."""
    partes = re.findall(r"(>=|<)\s*(\d+)\.(\d+)", expresion)
    if len(partes) != 2:
        raise AssertionError("requires-python no interpretable: %r" % expresion)
    return tuple((int(a), int(b)) for _, a, b in partes)  # type: ignore[return-value]


def test_el_paquete_tests_es_el_del_repo():
    """`from tests import helpers` tiene que resolver aqui (defecto 4.1)."""
    import tests

    resuelto = pathlib.Path(tests.__file__).resolve().parent
    assert resuelto == (RAIZ / "tests").resolve(), (
        "`tests` resuelve a %s y no al del repo (%s): el defecto 4.1 ha vuelto"
        % (resuelto, (RAIZ / "tests").resolve())
    )


def test_interprete_declarado():
    """La suite se declara para el rango de `pyproject.toml`, no para cualquiera."""
    minimo, maximo = _rango(PY_DECLARADO)
    medido = sys.version_info[:2]
    assert minimo <= medido < maximo, (
        "interprete %s fuera de %s (pyproject.toml): %s"
        % (sys.version.split()[0], PY_DECLARADO, sys.executable)
    )


def test_zlib_declarada():
    """La identidad byte a byte solo se firma con la zlib declarada."""
    medido = zlib.ZLIB_RUNTIME_VERSION
    if medido != ZLIB_DECLARADA:
        pytest.skip(
            "zlib %s != %s declarada en pyproject.toml: la identidad byte a byte "
            "no se firma con este interprete (%s)"
            % (medido, ZLIB_DECLARADA, sys.executable)
        )
    assert medido == ZLIB_DECLARADA

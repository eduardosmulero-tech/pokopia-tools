#!/usr/bin/env python3
"""Comando unico de la suite: `python run-tests.py` desde CUALQUIER carpeta.

Fija las tres cosas que antes cambiaban el resultado (informe 4.1):

- el interprete: se declara en `pyproject.toml` (`requires-python`) y aqui se
  comprueba antes de ejecutar nada;
- el directorio: pytest se lanza con cwd = raiz del repo;
- la zlib: si no es la declarada en `[tool.pokopia] zlib`, se avisa y los tests
  que firman identidad byte a byte se saltan con motivo en vez de mentir.

Uso:
    python run-tests.py            # suite completa
    python run-tests.py -k mod     # cualquier argumento de pytest
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
import zlib

RAIZ = os.path.dirname(os.path.abspath(__file__))


def _config() -> tuple[str, str]:
    with open(os.path.join(RAIZ, "pyproject.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    return cfg["project"]["requires-python"], cfg["tool"]["pokopia"]["zlib"]


def _rango(expresion: str) -> tuple[tuple[int, int], tuple[int, int]]:
    partes = re.findall(r"(>=|<)\s*(\d+)\.(\d+)", expresion)
    if len(partes) != 2:
        raise SystemExit("requires-python no interpretable: %r" % expresion)
    return tuple((int(a), int(b)) for _, a, b in partes)  # type: ignore[return-value]


def main(argv: list[str]) -> int:
    requiere, zlib_declarada = _config()
    minimo, maximo = _rango(requiere)
    print(
        "interprete : python %s | zlib %s (compilado %s)"
        % (sys.version.split()[0], zlib.ZLIB_VERSION, zlib.ZLIB_RUNTIME_VERSION)
    )
    print("declarado  : requires-python %s | zlib %s" % (requiere, zlib_declarada))
    print("cwd        : %s" % RAIZ)

    if not (minimo <= sys.version_info[:2] < maximo):
        print(
            "ERROR: la suite esta declarada para %s y este interprete es %s.\n"
            "       Usa el declarado, p. ej.:\n"
            "       <interprete>/python.exe run-tests.py" % (requiere, sys.version.split()[0]),
            file=sys.stderr,
        )
        return 2

    if zlib.ZLIB_RUNTIME_VERSION != zlib_declarada:
        print(
            "AVISO: zlib %s != %s declarada. Identidad byte a byte NO se firma en este\n"
            "       entorno; esos tests se saltaran con motivo (ver pyproject.toml)."
            % (zlib.ZLIB_RUNTIME_VERSION, zlib_declarada),
            file=sys.stderr,
        )

    return subprocess.call([sys.executable, "-m", "pytest", *argv], cwd=RAIZ)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["-q"]))

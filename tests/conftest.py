"""Raiz del repo en sys.path y directorio de trabajo fijo.

Dos garantias, y las dos son defectos reales ya pagados (informe 4.1):

- la raiz del repo va **primero** en `sys.path`, para que `import pokopia` y
  `from tests import helpers` resuelvan a este repo y no a un paquete homonimo
  del entorno (el venv de Hermes tiene su propio `tests/`);
- el directorio de trabajo se fija a la raiz, porque varios tests usan rutas
  relativas (`ejemplos/editar-fila`) y antes daban resultados distintos segun
  desde donde se lanzara pytest.
"""

import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


@pytest.fixture(scope="session", autouse=True)
def _cwd_en_la_raiz():
    """Fija el cwd a la raiz del repo durante toda la sesion de tests."""
    anterior = os.getcwd()
    os.chdir(RAIZ)
    yield RAIZ
    os.chdir(anterior)


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

#: Pruebas cuyo sujeto vive en `tools/`, que **nunca viaja** en la release
#: (lista blanca de `tools/build_release.py`, por diseno: el paquete trae el
#: kit, no el cuaderno de herramientas). En el arbol los modulos existen y
#: estas pruebas corren como siempre; en el paquete no estarian y, sin esta
#: guarda, la coleccion entera de pytest falla y se lleva por delante la suite
#: entera. Criterio unico y central: si el modulo que la prueba existe, se
#: colecciona; si no, no. (Mismo patron que `collect_ignore` de la doc de
#: pytest; nada de saltos repartidos por ocho ficheros.)
_HERRAMIENTAS = {
    "test_cruce_objdb_catalogo.py": ("tools", "cruce_objdb_catalogo.py"),
    "test_h4_game_dll.py": ("tools", "parcheo", "h4_game_dll.py"),
    "test_parcheo.py": ("tools", "parcheo", "parche.py"),
    "test_probe_unknown_fields.py": ("tools", "spec", "probe_unknown_fields.py"),
    "test_rdb_names.py": ("tools", "rdb_names.py"),
    "test_recetas.py": ("tools", "recetas.py"),
    "test_romfs_img.py": ("tools", "romfs", "img_inspect.py"),
    "test_scripts_mud.py": ("tools", "scripts_mud.py"),
}
collect_ignore = [
    nombre
    for nombre, partes in _HERRAMIENTAS.items()
    if not os.path.exists(os.path.join(RAIZ, *partes))
]


@pytest.fixture(scope="session", autouse=True)
def _cwd_en_la_raiz():
    """Fija el cwd a la raiz del repo durante toda la sesion de tests."""
    anterior = os.getcwd()
    os.chdir(RAIZ)
    yield RAIZ
    os.chdir(anterior)


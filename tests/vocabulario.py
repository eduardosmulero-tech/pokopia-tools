"""Vocabulario cerrado de la salida de `pkp progress`.

El parte solo publica formato, cifras e indices. Esta lista es la unica puerta: si una
edicion mete una palabra nueva —y con ella, posiblemente un nombre del juego— los tests
que la usan fallan. Se mantiene a mano a proposito; ampliarla es una decision consciente.

Mismo mecanismo que `informes/t_d4e6c951/terminos-permitidos.txt`.
"""

PERMITIDAS = {
    "aldeanos", "ambiental", "aparece", "array", "bin", "bitmap", "bolsa", "cabecera",
    "casas", "catalogo", "cmndat", "coleccionable", "coleccionables", "con", "contador",
    "contadores", "de", "disponibles", "en", "espacio", "fichero", "g", "hechas",
    "identifica", "ids", "la", "localiza", "los", "medido", "ni", "ningun", "nivel",
    "no", "otro", "pagina", "par", "parte", "peticiones", "por", "progreso", "s",
    "save", "se", "stgdatnn", "zona", "zonas", "distintos", "medir", "sin",
}

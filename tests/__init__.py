"""Paquete de pruebas del kit.

Existe para que `from tests import helpers` resuelva **siempre** a este
directorio y no a un paquete `tests` de otro entorno que este en `sys.path`
(por ejemplo, el del venv de Hermes). Sin este fichero la coleccion dependia
del directorio de invocacion y del interprete: ver
docs/INFORME-COMPLETO-2026-11-04.md 4.1.
"""

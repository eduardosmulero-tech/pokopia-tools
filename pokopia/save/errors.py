"""Errores del modulo de save.

Todos heredan de `SaveError` para que la CLI los traduzca a un codigo de salida sin
tener que conocer cada caso.
"""
from __future__ import annotations


class SaveError(Exception):
    """Error generico del save."""

    exit_code = 1


class SaveFormatError(SaveError):
    """El fichero no tiene la forma esperada (magic, cabecera, zlib, tamano)."""


class SaveVersionError(SaveError):
    """Version de save sin geometria declarada en `layout.py`."""

    def __init__(self, version: int):
        self.version = version
        super().__init__(
            "version de save %#010x sin geometria declarada; conocidas: %s"
            % (version, ", ".join("%#010x" % v for v in sorted(_known_versions()))))


class SaveReadOnlyError(SaveError):
    """Se ha pedido escribir en un arbol protegido (save vivo o dump)."""

    exit_code = 2


class SlotError(SaveError):
    """Registro o valor fuera de rango."""


def _known_versions():
    from .layout import LAYOUTS

    return LAYOUTS

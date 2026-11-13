"""Errores del formato de parche de ejecutable (`*.parche.json`).

Misma forma que `pokopia.mod.errors`: `exit_code` lo fija la CLI y `code` permite
que los tests y el informe distingan el motivo sin mirar el texto.
"""

from __future__ import annotations


class ParcheError(Exception):
    """El parche no se puede leer, validar o aplicar."""

    exit_code = 1

    def __init__(self, message: str, *, code: str = "parche", where: str = "",
                 details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.where = where
        self.details = details or {}

    def __str__(self) -> str:
        prefix = ("%s: " % self.where) if self.where else ""
        return prefix + super().__str__()


class GuardError(ParcheError):
    """Intento de escribir sobre el original o sobre un arbol protegido."""

    exit_code = 2


class UsageError(ParcheError):
    """Falta un dato de invocacion o un fichero."""

    exit_code = 2


class IdentidadError(ParcheError):
    """El binario no es el que el parche declara (sha256, tamano o build id)."""

    exit_code = 3


class BytesError(ParcheError):
    """Los bytes que hay en el offset no son los `esperado` del parche."""

    exit_code = 4

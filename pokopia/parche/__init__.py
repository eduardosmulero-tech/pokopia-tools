"""Parche de ejecutable: definicion en texto, aplicacion y reversion.

Contrato en `docs/SPEC-PARCHE.md`. Resumen:

- El parche es un `*.parche.json` legible: sha256 del ejecutable esperado,
  version, y por cada byte cambiado el offset de modulo, los bytes que hay
  (`esperado`) y los que se ponen (`nuevo`), con su motivo.
- `comprobar()` se niega si el sha256, el tamano, el build id o los bytes no
  cuadran. Nunca se escribe "a ciegas" por offset.
- `aplicar()` trabaja sobre una copia y deja la imagen parcheada y el `.ips`
  que consume el emulador; `revertir()` los borra y coteja que el original
  sigue con el mismo sha256.
- El original no se modifica: se abre en modo lectura y su sha256 se recalcula
  al revertir.
"""

from __future__ import annotations

from .aplicar import (IMAGEN_ORIGINAL, IMAGEN_PARCHEADA, INFORME, aplicar, comprobar,
                      revertir)
from .errors import (BytesError, GuardError, IdentidadError, ParcheError, UsageError)
from .espec import PARCHE_FORMAT, Edicion, Espec, Juego, cargar, validar
from .imagen import CABECERA, SEGMENTOS, Cabecera, Segmento, leer

__all__ = [
    "PARCHE_FORMAT", "CABECERA", "SEGMENTOS", "IMAGEN_ORIGINAL", "IMAGEN_PARCHEADA",
    "INFORME", "BytesError", "Cabecera", "Edicion", "Espec", "GuardError",
    "IdentidadError", "Juego", "ParcheError", "Segmento", "UsageError", "aplicar",
    "cargar", "comprobar", "leer", "revertir", "validar",
]

#!/usr/bin/env python3
"""pkp - CLI del kit de datos de Pokemon Pokopia.

    python pkp.py info
    python pkp.py table 983 --rows 1320:1330
    python pkp.py row 983 1324
    python pkp.py mod validate ejemplos/editar-fila
    python pkp.py mod apply ejemplos/editar-fila --container build/copia

Atajo en Windows/MSYS: los scripts `pkp` y `pkp.cmd` de esta misma carpeta
llaman aqui. Contrato de comandos: docs/ARQUITECTURA-KIT.md §5.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokopia.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

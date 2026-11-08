#!/usr/bin/env python3
"""pkp_pack.py - envoltorio de compatibilidad de la CLI del contenedor.

La implementacion vive desde la tarjeta t_df136634 en `pokopia/container/ktgl.py`
(capa de formato del kit, ver `docs/ARQUITECTURA-KIT.md` §2). Este fichero
mantiene la interfaz historica, sin codigo nuevo:

    python pkp_pack.py verify    LI_C0_R.IDX LD_C0_R.BIN
    python pkp_pack.py extract   LI_C0_R.IDX 983 salida.bin
    python pkp_pack.py unpack-all / pack / set / repack / roundtrip

Para los comandos del kit (informacion de tablas, mods) usa `pkp.py`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokopia.container.ktgl import *  # noqa: F401,F403
from pokopia.container.ktgl import main  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())

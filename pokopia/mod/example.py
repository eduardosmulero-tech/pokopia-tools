"""Mod de ejemplo con bytes propios: el que usan las dos paginas de uso.

`pkp mod example <carpeta>` escribe un `mod.json` valido y un payload de 23 bytes
ASCII en la ruta de romfs que el mod declara. Existe para que
`docs/MAKE-A-MOD.md` y `docs/INSTALL-AND-DIAGNOSE.md` se puedan seguir sin
repartir contenido del juego: el payload lo genera este modulo, no viaja en el
repo ni sale de un dump.

No es un asset valido a proposito: demuestra el circuito (manifiesto -> pack ->
install -> servido -> uninstall). Un mod de verdad pone en `file` el contenedor
editado, el `.fdata` o el fichero generado con las herramientas de formato.
"""

from __future__ import annotations

import json
import os

from .. import paths

#: Ruta del romfs que sustituye el ejemplo. Es una ruta del arbol, no contenido:
#: los bytes que se sirven son los de `PAYLOAD`.
RUTA = "motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx"
PAYLOAD = b"PKP ejemplo de overlay\n"
NOMBRE = "ejemplo-overlay"


def plantilla(md5s: dict[str, str]) -> dict:
    return {
        "mod_format": 1,
        "name": NOMBRE,
        "version": "0.1.0",
        "authors": ["tu nombre"],
        "description": "Ejemplo generado por `pkp mod example`: sustituye un fichero del "
                       "romfs por bytes propios. No es un asset valido.",
        "game": {"title": "pokopia", "version": "2.0.1a", "container_md5": md5s},
        "requires": [],
        "edits": [],
        "text": [],
        "files": [],
        "romfs": [{
            "path": RUTA,
            "file": "payload/" + RUTA,
            "why": "ejemplo: demuestra el circuito del overlay sin tocar el img",
        }],
    }


def escribir(destino: str, container: str | None = None, *, forzar: bool = False) -> dict:
    """Crea el mod de ejemplo en `destino`; devuelve las rutas escritas.

    `container` (opcional) es la carpeta con `LD_C0_R.BIN` + `LI_C0_R.IDX`: sus
    md5 van al manifiesto. Sin ella se escriben ceros, que `validate` acepta
    mientras no se le pase un contenedor con el que comparar.
    """
    destino = os.path.abspath(os.path.expanduser(destino))
    manifiesto = os.path.join(destino, "mod.json")
    if os.path.exists(manifiesto) and not forzar:
        raise FileExistsError("ya existe %s: no se sobrescribe (--forzar para rehacerlo)"
                              % manifiesto)
    if container:
        md5s = paths.container_md5(paths.resolve_container(container))
    else:
        # sin --container, si hay uno configurado (PKP_ROMFS o ./romfs) se usan sus md5:
        # el ejemplo queda coherente con el build del usuario sin pedirle nada mas
        try:
            md5s = paths.container_md5(paths.resolve_container(must_exist=True))
        except (paths.ContainerNotFound, OSError):
            md5s = {paths.BIN_NAME: "0" * 32, paths.IDX_NAME: "0" * 32}

    payload = os.path.join(destino, "payload", RUTA.replace("/", os.sep))
    os.makedirs(os.path.dirname(payload), exist_ok=True)
    with open(payload, "wb") as fh:
        fh.write(PAYLOAD)
    with open(manifiesto, "w", encoding="utf-8") as fh:
        json.dump(plantilla(md5s), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return {"dir": destino, "manifest": manifiesto, "payload": payload,
            "path": RUTA, "bytes": len(PAYLOAD), "container_md5": md5s}

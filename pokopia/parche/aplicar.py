"""Comprobacion, aplicacion y reversion de un parche de ejecutable.

Todo se escribe en la carpeta de trabajo que se indique (`--out`). El ejecutable
original **se abre en modo lectura y no se toca nunca**; la prueba de que sigue
intacto es que al revertir se recalculan sus sha256 y md5 y se cotejan con los
que declara el parche.

Que se escribe en la carpeta de trabajo:

    imagen.original    imagen del modulo tal cual (cabecera + segmentos), testigo
    imagen.parcheada   la misma imagen con los bytes nuevos ya puestos
    <build_id>.ips     el parche en el formato que aplica el emulador
    aplicacion.json    sha256 de todo, para poder revertir y auditar despues

La reversion no "adivina" los bytes viejos: los vuelve a sacar del original y
comprueba que la imagen regenerada tiene el mismo sha256 que `imagen.original`.
"""

from __future__ import annotations

import json
import os

from .. import paths
from . import imagen as nso_imagen
from . import ips as ips_mod
from .errors import BytesError, GuardError, IdentidadError, ParcheError, UsageError
from .espec import Edicion, Espec

IMAGEN_ORIGINAL = "imagen.original"
IMAGEN_PARCHEADA = "imagen.parcheada"
INFORME = "aplicacion.json"
#: Los `.ips` de exefs se nombran con el build id del modulo parcheado.
NOMBRE_IPS = "%s.ips"


def _dentro_de(ruta: str, carpeta: str) -> bool:
    ruta = os.path.normcase(os.path.abspath(ruta))
    carpeta = os.path.normcase(os.path.abspath(carpeta))
    try:
        return os.path.commonpath([ruta, carpeta]) == carpeta
    except ValueError:      # unidades distintas
        return False


def _salida_segura(salida: str, binario: str) -> None:
    """Nunca se escribe al lado del original ni en un arbol protegido."""
    paths.guard_writable(salida)
    if _dentro_de(salida, os.path.dirname(os.path.abspath(binario))):
        raise GuardError("la salida no puede caer junto al ejecutable original: %s" % salida,
                         code="guardia")


def _identidad(binario: str, espec: Espec) -> dict:
    """sha256/md5/tamano del binario frente a los que declara el parche."""
    if not os.path.isfile(binario):
        raise UsageError("no existe el ejecutable: %s" % binario, code="fichero")
    tamano = os.path.getsize(binario)
    sha = paths.sha256_file(binario)
    md5 = paths.md5_file(binario)
    with open(binario, "rb") as fh:
        cab = nso_imagen.leer_cabecera(fh.read(nso_imagen.CABECERA))
    iguales = {
        "tamano": tamano == espec.juego.tamano,
        "sha256": sha == espec.juego.sha256,
        "md5": md5 == espec.juego.md5,
        "build_id": cab.build_id == espec.juego.build_id,
    }
    informe = {"binario": binario, "tamano": tamano, "sha256": sha, "md5": md5,
               "build_id": cab.build_id, "coincide": iguales}
    if not all(iguales.values()):
        mal = [k for k, v in iguales.items() if not v]
        raise IdentidadError(
            "el ejecutable no es el que declara el parche (%s).\n"
            "  esperado: tamano %d B  sha256 %s  build id %s\n"
            "  medido  : tamano %d B  sha256 %s  build id %s\n"
            "  no se ha escrito nada."
            % (", ".join(mal), espec.juego.tamano, espec.juego.sha256,
               espec.juego.build_id, tamano, sha, cab.build_id),
            code="identidad", details=informe)
    return informe


def comprobar(binario: str, espec: Espec) -> dict:
    """Identidad + bytes esperados en cada edicion. No escribe nada."""
    ident = _identidad(binario, espec)
    imagen, cab = nso_imagen.leer(binario)
    comprobaciones = []
    for ed in espec.ediciones:
        seg = cab.segmento(ed.segmento)
        if ed.offset + ed.tam > seg.tam:
            raise ParcheError("%s+%#x+%d B se sale del segmento (%d B)"
                              % (ed.segmento, ed.offset, ed.tam, seg.tam), code="rango")
        ini = nso_imagen.CABECERA + seg.base + ed.offset
        actual = imagen[ini:ini + ed.tam]
        comprobaciones.append({"segmento": ed.segmento, "offset": ed.offset,
                               "esperado": ed.esperado.hex(), "actual": actual.hex(),
                               "ok": actual == ed.esperado, "motivo": ed.motivo})
    malas = [c for c in comprobaciones if not c["ok"]]
    if malas:
        detalle = "\n".join(
            "  %s+%#x: hay %s, el parche espera %s"
            % (c["segmento"], c["offset"], c["actual"], c["esperado"]) for c in malas)
        raise BytesError("los bytes del binario no son los del parche:\n%s\n"
                         "  no se ha escrito nada." % detalle, code="bytes",
                         details={"ediciones": comprobaciones})
    return {"identidad": ident, "imagen_sha256": nso_imagen.sha256(imagen),
            "ediciones": comprobaciones}


def aplicar(binario: str, espec: Espec, salida: str) -> dict:
    """Comprueba, escribe la imagen parcheada y el `.ips`, y devuelve el informe."""
    _salida_segura(salida, binario)
    chequeo = comprobar(binario, espec)

    imagen, cab = nso_imagen.leer(binario)
    parcheada = bytearray(imagen)
    for ed in espec.ediciones:
        seg = cab.segmento(ed.segmento)
        ini = nso_imagen.CABECERA + seg.base + ed.offset
        parcheada[ini:ini + ed.tam] = ed.nuevo
    parcheada = bytes(parcheada)

    os.makedirs(salida, exist_ok=True)
    ruta_original = os.path.join(salida, IMAGEN_ORIGINAL)
    ruta_parcheada = os.path.join(salida, IMAGEN_PARCHEADA)
    ruta_ips = os.path.join(salida, NOMBRE_IPS % cab.build_id)
    with open(ruta_original, "wb") as fh:
        fh.write(imagen)
    with open(ruta_parcheada, "wb") as fh:
        fh.write(parcheada)
    datos_ips = ips_mod.construir(espec.pares_ips())
    with open(ruta_ips, "wb") as fh:
        fh.write(datos_ips)

    informe = {
        "parche": {"nombre": espec.nombre, "version": espec.version,
                   "espec": os.path.abspath(espec.ruta) if espec.ruta else "",
                   "descripcion": espec.descripcion, "reversion": espec.reversion},
        "juego": {"titulo": espec.juego.titulo, "version": espec.juego.version,
                  "fichero": espec.juego.fichero, "build_id": cab.build_id},
        "binario": chequeo["identidad"],
        "imagen": {
            "sha256_antes": chequeo["imagen_sha256"],
            "sha256_despues": nso_imagen.sha256(parcheada),
            "bytes": len(imagen),
            "ediciones": len(espec.ediciones),
            "bytes_cambiados": sum(ed.tam for ed in espec.ediciones),
        },
        "ediciones": chequeo["ediciones"],
        "ficheros": {"imagen_original": os.path.abspath(ruta_original),
                     "imagen_parcheada": os.path.abspath(ruta_parcheada),
                     "ips": os.path.abspath(ruta_ips),
                     "ips_sha256": paths.sha256_file(ruta_ips),
                     "ips_bytes": len(datos_ips)},
    }
    with open(os.path.join(salida, INFORME), "w", encoding="utf-8") as fh:
        json.dump(informe, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return informe


def revertir(binario: str, espec: Espec, salida: str) -> dict:
    """Borra los productos del parche y prueba que el original sigue igual.

    No toca el ejecutable: vuelve a leerlo, recompone su imagen y compara el
    sha256 con el de `imagen.original` (si existe) y con el que declara el parche.
    """
    _salida_segura(salida, binario)
    ident = _identidad(binario, espec)
    imagen, cab = nso_imagen.leer(binario)
    sha_original = nso_imagen.sha256(imagen)

    ruta_original = os.path.join(salida, IMAGEN_ORIGINAL)
    if os.path.isfile(ruta_original):
        with open(ruta_original, "rb") as fh:
            testigo = nso_imagen.sha256(fh.read())
        if testigo != sha_original:
            raise ParcheError("la imagen testigo no es la del original: %s != %s"
                              % (testigo, sha_original), code="reversion")

    borrados = []
    for nombre in (IMAGEN_PARCHEADA, NOMBRE_IPS % cab.build_id, NOMBRE_IPS % espec.juego.build_id):
        ruta = os.path.join(salida, nombre)
        if os.path.isfile(ruta):
            os.remove(ruta)
            borrados.append(ruta)
    ruta_informe = os.path.join(salida, INFORME)
    if os.path.isfile(ruta_informe):
        with open(ruta_informe, "r", encoding="utf-8") as fh:
            antes = json.load(fh)
        antes["revertido"] = {"sha256_imagen": sha_original, "borrados": borrados}
        with open(os.path.join(salida, INFORME + ".revertido"), "w", encoding="utf-8") as fh:
            json.dump(antes, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.remove(ruta_informe)

    quedan = [n for n in (IMAGEN_PARCHEADA, NOMBRE_IPS % cab.build_id)
              if os.path.isfile(os.path.join(salida, n))]
    return {"binario": ident, "sha256_imagen": sha_original, "borrados": borrados,
            "quedan": quedan,
            "revertido": not quedan}

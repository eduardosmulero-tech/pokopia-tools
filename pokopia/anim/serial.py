"""Exportar e importar animaciones `G2A` en texto.

Dos representaciones, con propositos distintos:

- **JSON sin perdida** (`to_json`/`from_json`): todo lo que hay en el fichero,
  incluidos los `int64` crudos de los bloques cuantizados. `pkp anim export
  --format json` + `pkp anim build` devuelve el fichero **byte a byte identico**
  (lo comprueba el test y el censo). Es la forma de tocar una animacion.
- **CSV horneado** (`csv_rows`): una fila por hueso, canal y frame, con el valor
  ya evaluado (cuaternion para rotacion, vector para traslacion y escala). Es
  para leer y comprobar a ojo; no sirve para reconstruir, porque el cubico se
  muestrea.

Nada de esto imprime contenido del juego en los informes: las cifras y los
hashes si, las animaciones exportadas se quedan en `build/`.
"""

from __future__ import annotations

import json
import os

from .g2a import (
    AnimError,
    Animation,
    Bone,
    KeyBlock,
    Spline,
)

#: Canales que el formato define (opcode -> nombre).
CANAL_POR_OPCODE = {0: "rotation", 1: "translation", 2: "scale"}
OPCODE_POR_CANAL = {v: k for k, v in CANAL_POR_OPCODE.items()}


def to_json(anim: Animation, *, name: str | None = None,
            sha256: str | None = None, size: int | None = None) -> dict:
    """Documento completo y reversible de la animacion."""
    doc: dict = {
        "format": "G2A",
        "version": anim.version.decode("ascii", "replace"),
        "frame_rate": anim.frame_rate,
        "length_frames": anim.length_frames,
        "reserved": anim.reserved,
        "key_blocks": [[row.raw for row in bloque.rows] for bloque in anim.key_blocks],
        "bones": [
            {
                "bone_id_raw": hueso.bone_id_raw,
                "bone_id": hueso.bone_id,
                "timing_offset": hueso.timing_offset,
                "splines": [
                    {
                        "opcode": spline.opcode,
                        "channel": spline.channel,
                        "first_data_index": spline.first_data_index,
                        "timings": list(spline.timings),
                        "key_block_indexes": [
                            spline.first_data_index + k
                            for k in range(spline.keyframe_count)],
                    }
                    for spline in hueso.splines
                ],
            }
            for hueso in anim.bones
        ],
    }
    if name is not None:
        doc["source"] = {"name": name, "size": size, "sha256": sha256}
    return doc


def from_json(doc: dict) -> Animation:
    """Reconstruye la animacion desde `to_json`. Valida lo que toca."""
    if doc.get("format") != "G2A":
        raise AnimError("el documento no es format G2A: %r" % doc.get("format"))
    version = str(doc["version"]).encode("ascii")
    bloques = [KeyBlock(tuple(_fila(valores) for valores in fila))  # type: ignore[arg-type]
               for fila in doc["key_blocks"]]
    huesos: list[Bone] = []
    for fila in doc["bones"]:
        splines: list[Spline] = []
        for s in fila["splines"]:
            splines.append(Spline(
                opcode=s["opcode"],
                timings=tuple(s["timings"]),
                first_data_index=s["first_data_index"]))
        huesos.append(Bone(bone_id_raw=fila["bone_id_raw"],
                           splines=splines,
                           bone_id=fila.get("bone_id", fila["bone_id_raw"]),
                           timing_offset=fila.get("timing_offset", 0)))
    anim = Animation(version=version,
                     frame_rate=float(doc["frame_rate"]),
                     length_frames=int(doc["length_frames"]),
                     bones=huesos,
                     key_blocks=bloques,
                     reserved=int(doc.get("reserved", 0)))
    # rellenar las claves de cada spline desde los bloques
    for hueso in anim.bones:
        for spline in hueso.splines:
            inicio = spline.first_data_index
            fin = inicio + spline.keyframe_count
            if inicio < 0 or fin > len(bloques):
                raise AnimError(
                    "hueso %d, canal %s: bloques %d..%d fuera de %d"
                    % (hueso.bone_id, spline.channel, inicio, fin, len(bloques)))
            spline.keys = bloques[inicio:fin]
    return anim


def _fila(valores) -> "object":
    from .g2a import Row

    if isinstance(valores, dict):
        return Row(valores["raw"], valores["x"], valores["y"], valores["z"],
                   valores["exp"])
    return Row.from_int(int(valores))


def timeline(spline: Spline, length_frames: int):
    """Tramos `(frame_inicio, frame_fin, clave)` de un spline.

    El tramo `k` cubre los frames `[timings[k], timings[k+1])`, y el ultimo
    llega hasta la longitud de la animacion. Si un spline tiene una sola clave
    (o los tiempos no dejan sitio), el tramo es de un frame en `timings[0]`.
    """
    n = spline.keyframe_count
    for k in range(n):
        inicio = spline.timings[k]
        if k + 1 < n:
            fin = spline.timings[k + 1]
        else:
            fin = max(length_frames, inicio + 1)
        if fin <= inicio:
            fin = inicio + 1
        yield inicio, fin, k


def csv_rows(anim: Animation):
    """Genera `(bone_id, channel, frame, time_s, x, y, z, w)` horneado."""
    for hueso in anim.bones:
        for spline in hueso.splines:
            for inicio, fin, k in timeline(spline, anim.length_frames):
                tramo = fin - inicio
                for frame in range(inicio, fin):
                    t = (frame - inicio) / tramo
                    valores = spline.sample(k, t)
                    relleno = (None,) * (4 - len(valores))
                    yield (hueso.bone_id, spline.channel, frame,
                           frame / anim.frame_rate if anim.frame_rate else 0.0,
                           *valores, *relleno)


#: Cabecera del CSV horneado.
CSV_HEADER = ("bone_id", "channel", "frame", "time_s", "x", "y", "z", "w")


def write_csv(anim: Animation, ruta: str) -> int:
    """Escribe el CSV horneado; devuelve las filas escritas."""
    import csv

    filas = 0
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(CSV_HEADER)
        for fila in csv_rows(anim):
            escritor.writerow(
                [fila[0], fila[1], fila[2], "%.6f" % fila[3]]
                + ["" if v is None else "%.9g" % v for v in fila[4:]])
            filas += 1
    return filas


def write_json(doc: dict, ruta: str) -> None:
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def read_json(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cargar(ruta: str) -> bytes:
    """Bytes de una animacion desde disco, sin escribir nada."""
    if not os.path.isfile(ruta):
        raise AnimError("no existe el fichero: %s" % ruta)
    with open(ruta, "rb") as fh:
        return fh.read()


__all__ = [
    "CANAL_POR_OPCODE",
    "CSV_HEADER",
    "OPCODE_POR_CANAL",
    "cargar",
    "csv_rows",
    "from_json",
    "read_json",
    "timeline",
    "to_json",
    "write_csv",
    "write_json",
]

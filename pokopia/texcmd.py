#!/usr/bin/env python3
"""Comandos `pkp tex`: listar, censar, extraer a PNG y reinyectar.

Va aparte de `cli.py` para no engordarlo; `cli.py` solo engancha el subparser y
delega aqui. Todo lo que escribe pasa por `paths.guard_writable` y por
`offload` (nunca escribe en el dump).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import zlib
from collections import Counter

from . import fdata, g1t, paths, textures


class TexError(Exception):
    """Error de uso o de formato de `pkp tex`; la CLI lo traduce a exit 1/2."""

    exit_code = 1


def _out(stream, line: str = "") -> None:
    try:
        stream.write(line + "\n")
    except OSError:      # Windows devuelve EINVAL cuando la tuberia se cierra
        raise BrokenPipeError from None


# ---------------------------------------------------------------------------
# Lectura de todas las texturas de una ruta: .g1t suelto, carpeta o .fdata
# ---------------------------------------------------------------------------

def iter_g1t(via: str):
    """(nombre, bytes) de cada .g1t que haya en `via`.

    - fichero `.g1t`: el propio fichero
    - carpeta: todos los `.g1t` de dentro (recursivo)
    - `.fdata`: sus entradas de tipo `g1t`, descomprimidas en memoria
    """
    if os.path.isdir(via):
        hallados = []
        for carpeta, _, ficheros in os.walk(via):
            for nombre in sorted(ficheros):
                if nombre.lower().endswith(".g1t"):
                    ruta = os.path.join(carpeta, nombre)
                    with open(ruta, "rb") as fh:
                        hallados.append((os.path.basename(ruta), fh.read()))
        if not hallados:
            raise TexError("no hay ningun .g1t bajo %s" % via)
        return hallados
    if not os.path.isfile(via):
        raise TexError("no existe: %s" % via)
    with open(via, "rb") as fh:
        datos = fh.read()
    if datos[:4] == g1t.MAGIC:
        return [(os.path.basename(via), datos)]
    if via.lower().endswith(fdata.FDATA_SUFFIX):
        salida = []
        with open(via, "rb", buffering=0) as fh:
            for entry in fdata.iter_entries(via):
                if entry.type_ktid != 0xAFBEC60C:
                    continue
                salida.append(("0x%08x.g1t" % entry.name_hash, fdata.read_entry(fh, entry)))
        if not salida:
            raise TexError("%s no tiene entradas g1t" % via)
        return salida
    raise TexError("%s no es un .g1t ni un .fdata" % via)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_tex_list(args) -> int:
    documento = {"path": os.path.abspath(args.path), "files": []}
    for nombre, datos in iter_g1t(args.path):
        doc = g1t.parse(datos, source_name=nombre)
        documento["files"].append({
            "file": nombre,
            "version": doc.version.decode("ascii", "replace"),
            "platform": doc.platform_name,
            "textures": [t.as_dict() for t in doc.textures],
        })
    if args.json:
        json.dump(documento, sys.stdout, indent=2, ensure_ascii=False)
        _out(sys.stdout)
        return 0
    for fichero in documento["files"]:
        _out(sys.stdout, "%s  %s  %s  %d textura(s)"
             % (fichero["file"], fichero["version"], fichero["platform"],
                len(fichero["textures"])))
        _out(sys.stdout, "  %-3s %-8s %11s %5s %11s %11s %9s"
             % ("#", "formato", "dimensiones", "mips", "datos", "cadena", "relleno"))
        for t in fichero["textures"]:
            _out(sys.stdout, "  %-3d %-8s %5dx%-5d %5d %11d %11d %9d"
                 % (t["index"], t["format"], t["width"], t["height"], t["mips"],
                    t["data_size"], t["chain_size"], t["padding"]))
    return 0


# ---------------------------------------------------------------------------
# stat: censo de formatos con porcentaje escribible
# ---------------------------------------------------------------------------

def cmd_tex_stat(args) -> int:
    """Censo completo: parsea cada `g1t` de cada `.fdata` (descomprime ~6,3 GB)."""
    rutas = fdata.find_fdata(args.romfs)
    formatos: Counter = Counter()
    ficheros = 0
    texturas = 0
    ilegibles = 0
    plataformas: Counter = Counter()
    versiones: Counter = Counter()
    cabeceras: Counter = Counter()
    pre_tabla: Counter = Counter()
    for ruta in rutas:
        with open(ruta, "rb", buffering=0) as fh:
            for entry in fdata.iter_entries(ruta):
                if entry.type_ktid != 0xAFBEC60C:
                    continue
                ficheros += 1
                try:
                    doc = g1t.parse(fdata.read_entry(fh, entry),
                                    source_name="0x%08x" % entry.name_hash)
                except g1t.G1TError:
                    ilegibles += 1
                    continue
                versiones[doc.version] += 1
                plataformas[doc.platform] += 1
                cabeceras[(doc.header_size, doc.extra_size)] += 1
                pre_tabla[len(doc.pre_table)] += 1
                for tex in doc.textures:
                    formatos[tex.format_code] += 1
                    texturas += 1
    escribibles = sum(n for code, n in formatos.items() if textures.encodable(code))
    document = {
        "romfs": os.path.abspath(args.romfs),
        "files": ficheros,
        "textures": texturas,
        "unreadable": ilegibles,
        "writable": escribibles,
        "writable_pct": round(100.0 * escribibles / texturas, 2) if texturas else 0.0,
        "versions": {k.decode("ascii", "replace"): v for k, v in versiones.items()},
        "platforms": {"0x%02x" % k: v for k, v in plataformas.items()},
        "headers": {"0x%x/+%d" % k: v for k, v in cabeceras.most_common()},
        "pre_table": dict(pre_tabla.most_common()),
        "formats": [
            {"code": "0x%02x" % code, "name": g1t.format_of(code).name,
             "textures": n, "pct": round(100.0 * n / texturas, 2),
             "decodable": textures.decodable(code), "writable": textures.encodable(code)}
            for code, n in sorted(formatos.items(), key=lambda kv: -kv[1])],
    }
    if args.json:
        json.dump(document, sys.stdout, indent=2, ensure_ascii=False)
        _out(sys.stdout)
        return 0
    _out(sys.stdout, "romfs      : %s" % document["romfs"])
    _out(sys.stdout, "entradas   : %d g1t (de los .fdata del romfs)" % ficheros)
    _out(sys.stdout, "texturas   : %d (ilegibles: %d)" % (texturas, ilegibles))
    _out(sys.stdout, "versiones  : %s" % document["versions"])
    _out(sys.stdout, "plataformas: %s" % document["platforms"])
    _out(sys.stdout, "  %-6s %-8s %10s %8s %10s %10s" % (
        "code", "nombre", "texturas", "%", "decodif.", "escribible"))
    for fila in document["formats"]:
        _out(sys.stdout, "  %-6s %-8s %10d %7.2f%% %10s %10s"
             % (fila["code"], fila["name"], fila["textures"], fila["pct"],
                "si" if fila["decodable"] else "no", "si" if fila["writable"] else "no"))
    _out(sys.stdout, "escribibles: %d de %d (%.2f %%)"
         % (escribibles, texturas, document["writable_pct"]))
    return 0


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def _destino_png(args, nombre: str, indice: int) -> str:
    if os.path.isdir(args.out) or args.out.endswith(os.sep):
        os.makedirs(args.out, exist_ok=True)
        return os.path.join(args.out, "%s.%d.png" % (os.path.splitext(nombre)[0], indice))
    return args.out


def _fuente(args) -> tuple[str, bytes]:
    """El `.g1t` pedido: `args.path` (fichero o `.fdata`) y `args.g1t` (cual de dentro)."""
    hallados = iter_g1t(args.path)
    indice = getattr(args, "g1t", 0) or 0
    if not 0 <= indice < len(hallados):
        raise TexError("%s tiene %d .g1t; --g1t %d esta fuera de rango"
                       % (args.path, len(hallados), indice))
    return hallados[indice]


def cmd_tex_extract(args) -> int:
    if os.path.isdir(args.path):
        raise TexError("extract trabaja sobre un .g1t o un .fdata concreto, no sobre "
                       "una carpeta: los PNG se llamarian igual")
    nombre, datos = _fuente(args)
    doc = g1t.parse(datos, source_name=nombre)
    indices = [args.index] if args.index is not None else (
        range(len(doc.textures)) if args.all else [0])
    escritos = []
    for i in indices:
        if not 0 <= i < len(doc.textures):
            raise TexError("indice %d fuera de rango (0..%d)" % (i, len(doc.textures) - 1))
        tex = doc.textures[i]
        imagen = textures.decode_rgba(doc.payload(tex)[:tex.mip0_size],
                                      tex.width, tex.height, tex.format)
        destino = _destino_png(args, nombre, i)
        paths.guard_writable(destino)
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        with open(destino, "wb") as fh:
            fh.write(textures.png_encode(imagen))
        escritos.append((tex, destino))
    if args.json:
        json.dump({"path": os.path.abspath(args.path), "files": [
            {"index": t.index, "format": t.format.name, "width": t.width,
             "height": t.height, "png": os.path.abspath(d)} for t, d in escritos]},
            sys.stdout, indent=2, ensure_ascii=False)
        _out(sys.stdout)
        return 0
    for tex, destino in escritos:
        _out(sys.stdout, "  #%d  %-8s %dx%d  ->  %s  (%d B)"
             % (tex.index, tex.format.name, tex.width, tex.height, destino,
                os.path.getsize(destino)))
    return 0


# ---------------------------------------------------------------------------
# inject
# ---------------------------------------------------------------------------

def cmd_tex_inject(args) -> int:
    if os.path.isdir(args.path):
        raise TexError("inject trabaja sobre un .g1t o un .fdata concreto")
    if args.png and args.same:
        raise TexError("--png y --same se excluyen")
    if not args.png and not args.same:
        raise TexError("di que haces: --png <fichero> (reinyectar pixeles) o --same "
                       "(reescribir la misma textura, round-trip neutro)")
    nombre, datos = _fuente(args)
    doc = g1t.parse(datos, source_name=nombre)
    i = args.index if args.index is not None else 0
    if not 0 <= i < len(doc.textures):
        raise TexError("indice %d fuera de rango (0..%d)" % (i, len(doc.textures) - 1))
    tex = doc.textures[i]
    payload = doc.payload(tex)
    if args.same:
        nuevo_payload = payload
        cambio = 0.0
    else:
        with open(args.png, "rb") as fh:
            imagen = textures.png_decode(fh.read())
        if imagen.shape[:2] != (tex.height, tex.width):
            raise TexError("el PNG mide %dx%d y la textura %dx%d: no se reescala"
                           % (imagen.shape[1], imagen.shape[0], tex.width, tex.height))
        mip0 = textures.encode_rgba(imagen, tex.width, tex.height, tex.format)
        nuevo_payload = mip0 + payload[tex.mip0_size:]
        antes = textures.decode_rgba(payload[:tex.mip0_size], tex.width, tex.height,
                                     tex.format)
        cambio = float(abs(antes.astype("int32") - imagen.astype("int32")).mean())
    salida = doc.with_payload(i, nuevo_payload)
    if len(salida) != len(datos):
        raise TexError("el fichero reinyectado mide %d B y el original %d B"
                       % (len(salida), len(datos)))
    paths.guard_writable(args.out)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(salida)
    sha_antes = hashlib.sha256(datos).hexdigest()
    sha_despues = hashlib.sha256(salida).hexdigest()
    # releer lo escrito: el fichero tiene que volver a parsear y del mismo tamano
    releido = g1t.parse(open(args.out, "rb").read(), source_name=args.out)
    if len(releido.textures) != len(doc.textures):
        raise TexError("la relectura del fichero escrito no cuadra")
    if args.json:
        json.dump({"in": os.path.abspath(args.path), "out": os.path.abspath(args.out),
                   "index": i, "sha256_before": sha_antes, "sha256_after": sha_despues,
                   "identical": sha_antes == sha_despues,
                   "size": len(salida), "mean_abs_diff": round(cambio, 3)},
                  sys.stdout, indent=2, ensure_ascii=False)
        _out(sys.stdout)
        return 0
    _out(sys.stdout, "textura #%d  %s %dx%d  ->  %s"
         % (i, tex.format.name, tex.width, tex.height, args.out))
    _out(sys.stdout, "  bytes        : %d (identico)" % len(salida))
    _out(sys.stdout, "  sha256 antes : %s" % sha_antes)
    _out(sys.stdout, "  sha256 despues: %s" % sha_despues)
    _out(sys.stdout, "  %s" % ("IDENTICO byte a byte" if sha_antes == sha_despues
                               else "cambia (diferencia media %.2f/255)" % cambio))
    return 0


__all__ = ["TexError", "cmd_tex_list", "cmd_tex_stat", "cmd_tex_extract",
           "cmd_tex_inject", "iter_g1t"]

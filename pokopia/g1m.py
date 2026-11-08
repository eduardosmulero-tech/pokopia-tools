#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""g1m.py - lector minimo e independiente de `G1M` (modelo) y `G1T` (textura) de KTGL.

**Que es.** La capa de *formato* del paquete: abre un `.g1m` o un `.g1t`
suelto y devuelve la estructura (cabecera, chunks, secciones) y las cifras de
malla (vertices, indices, triangulos). No escribe: el que reempaqueta es la
herramienta de la comunidad (`tools/modelos/pkp_modelo.py`, que no viaja en la
release).

**Por que vive en `pokopia/`.** Estuvo en `tools/modelos/g1m.py` hasta la 0.3.0.
`tools/` no entra en la release (son scripts de medicion), asi que el lector de
modelos se quedo fuera de lo publicado. Se movio aqui, con el resto del formato,
para que el lector viaje; `tools/modelos/g1m.py` queda como reexportacion.

**Por que existe si ya hay herramientas.** Dos razones:

1. *Verificar sin depender del que escribe.* Comparar el `.g1m` original con el
   reempaquetado usando el mismo programa que lo reempaqueto seria medir el
   programa contra si mismo. Este lector es propio y solo comparte con
   `gust_stuff` los nombres de los campos, no el codigo.
2. *Un solo barrido para todo el censo.* `censo_magics.py` clasifica las 12.298
   entradas con `clasificar()`, sin cargar nada mas.

**Procedencia del conocimiento del formato** (codigo escrito desde los bytes del
contenedor, no copiado):

* `eArmada8/gust_stuff` (GPL-3.0, `g1m_export_meshes.py:1305` `parseG1M` y
  `:603` `parseG1MG`) — recorrido de chunks y tabla de secciones del chunk G1MG.
* `Joschuka/fmt_g1m` (GPL-3.0) — el plugin de Noesis del que sale medio el
  ecosistema (el propio gust_stuff lo cita como origen).
* `VitaSmith/gust_tools` (GPL-3.0 en `gust_g1t.c`) — magic `GT1G`, cabecera de
  texturas.

Nada de codigo ajeno: este fichero es propio y se distribuye con la licencia del
repo. La dependencia de las herramientas se declara en `tools/modelos/README.md`.

**Estructura medida** (ver `docs/MODELOS-G1M-Y-TEXTURAS-G1T.md`):

    G1M: 4s magic "_M1G" | 4s version | u32 tamano | u32 offset primer chunk
         | u32 reservado | u32 n chunks
    chunk: 4s magic | 4s version | u32 tamano  (tamano INCLUYE la cabecera:
           el chunk siguiente empieza en pos+tamano)
    GM1G: 4s magic | u32 version | u32 tamano | 4s plataforma | u32 reservado
          | 6f caja envolvente | u32 n secciones, y despues las secciones:
          12 B de cabecera (u32 magic, u32 tamano, u32 count) + datos; el
          tamano tambien incluye la cabecera de 12 B.
"""

from __future__ import annotations

import struct

MAGIC_G1M = b"_M1G"          # constante 0x47314D5F escrita little-endian ("G1M_")
MAGIC_G1T = b"GT1G"          # constante 0x47315447 escrita little-endian ("G1TG")
MAGIC_G1A = b"_A1G"
MAGIC_G2A = b"_A2G"

CHUNKS_G1M = (b"FM1G", b"SM1G", b"MM1G", b"GM1G", b"EM1G", b"OM1G")

SEC_GEOMETRY_SOCKETS = 0x00010001
SEC_MATERIALS = 0x00010002
SEC_SHADER_PARAMS = 0x00010003
SEC_VERTEX_BUFFERS = 0x00010004
SEC_VERTEX_ATTRIBUTES = 0x00010005
SEC_JOINT_PALETTES = 0x00010006
SEC_INDEX_BUFFER = 0x00010007
SEC_SUBMESH = 0x00010008
SEC_MESH_LOD = 0x00010009

NOMBRES_SECCION = {
    SEC_GEOMETRY_SOCKETS: "GEOMETRY_SOCKETS",
    SEC_MATERIALS: "MATERIALS",
    SEC_SHADER_PARAMS: "SHADER_PARAMS",
    SEC_VERTEX_BUFFERS: "VERTEX_BUFFERS",
    SEC_VERTEX_ATTRIBUTES: "VERTEX_ATTRIBUTES",
    SEC_JOINT_PALETTES: "JOINT_PALETTES",
    SEC_INDEX_BUFFER: "INDEX_BUFFER",
    SEC_SUBMESH: "SUBMESH",
    SEC_MESH_LOD: "MESH_LOD",
}

# Topologia tal y como la guarda el submesh. El 4 como "strip" y el 3 como "list"
# es la correspondencia que usa gust_stuff (`generate_fmts`, linea 900) y la que
# cuadra con los datos: con 4 los indices se leen como tira (76 indices -> 74
# triangulos) y con 3 como lista.
TOPOLOGIA = {1: "point", 3: "trianglelist", 4: "trianglestrip"}

# Version de G1MG a partir de la cual los buffers llevan un u32 extra. Es el
# mismo corte que usa gust_stuff; se comprueba contra el fichero al leer.
VERSION_BUFFER_CON_EXTRA = 0x30303430


class FormatoG1M(ValueError):
    """El fichero no tiene la estructura que el formato exige."""


# ---------------------------------------------------------------------------
# G1M: cabecera y chunks
# ---------------------------------------------------------------------------

def parse_g1m(buf: bytes, base: int = 0) -> dict:
    """Cabecera y lista de chunks de un G1M que empieza en `base`."""
    if len(buf) < base + 24 or buf[base:base + 4] != MAGIC_G1M:
        raise FormatoG1M("no empieza por _M1G en %d" % base)
    version = buf[base + 4:base + 8].decode("ascii", "replace")
    tamano, primer, reservado, n = struct.unpack_from("<IIII", buf, base + 8)
    out = {"base": base, "version": version, "tamano": tamano,
           "offset_primer_chunk": primer, "reservado": reservado,
           "n_chunks": n, "chunks": [], "problemas": []}
    pos = base + primer
    for i in range(n):
        if pos + 12 > base + tamano:
            out["problemas"].append("chunk %d se sale del fichero" % i)
            break
        magic = buf[pos:pos + 4]
        ver = buf[pos + 4:pos + 8].decode("ascii", "replace")
        size = struct.unpack_from("<I", buf, pos + 8)[0]
        out["chunks"].append({"magic": magic.decode("latin-1"), "version": ver,
                              "tamano": size, "offset": pos - base,
                              "datos": buf[pos:pos + size]})
        if magic not in CHUNKS_G1M:
            out["problemas"].append("chunk %d con magic desconocido %r" % (i, magic))
        if size < 12:
            out["problemas"].append("chunk %d con tamano %d" % (i, size))
            break
        pos += size
    if pos != base + tamano:
        out["problemas"].append("los chunks acaban en %d y el G1M declara %d"
                                % (pos - base, tamano))
    return out


def chunk(g1m: dict, magic: str) -> dict | None:
    for c in g1m["chunks"]:
        if c["magic"] == magic:
            return c
    return None


# ---------------------------------------------------------------------------
# GM1G: secciones
# ---------------------------------------------------------------------------

def parse_g1mg(datos: bytes) -> dict:
    """Tabla de secciones de un chunk GM1G (o GM1G entero)."""
    if len(datos) < 48 or not datos.startswith((b"GM1G", b"G1MG")):
        raise FormatoG1M("no es un GM1G")
    version, tamano = struct.unpack_from("<II", datos, 4)
    plataforma = datos[12:16].decode("latin-1")
    caja = struct.unpack_from("<6f", datos, 20)
    n = struct.unpack_from("<I", datos, 44)[0]
    out = {"version": version, "tamano": tamano, "plataforma": plataforma,
           "caja": caja, "n_secciones": n, "secciones": [], "problemas": []}
    pos = 48
    for i in range(n):
        if pos + 12 > len(datos):
            out["problemas"].append("seccion %d fuera del chunk" % i)
            break
        magic, size, count = struct.unpack_from("<III", datos, pos)
        sec = {"magic": magic, "tipo": NOMBRES_SECCION.get(magic, "0x%08X" % magic),
               "tamano": size, "count": count, "offset": pos}
        if magic == SEC_VERTEX_BUFFERS and count:
            sec["buffers"] = _buffers_vb(datos, pos, count, version)
        elif magic == SEC_INDEX_BUFFER and count:
            sec["buffers"] = _buffers_ib(datos, pos, count, version)
        elif magic == SEC_SUBMESH and count:
            sec["submeshes"] = _submeshes(datos, pos, count)
        out["secciones"].append(sec)
        if size < 12:
            out["problemas"].append("seccion %s con tamano %d" % (sec["tipo"], size))
            break
        pos += size
    return out


def _buffers_vb(datos: bytes, pos: int, count: int, version: int) -> list[dict]:
    """Entradas de VERTEX_BUFFERS. Devuelve solo lo que hace falta: stride y count.

    Los `offset` que se devuelven son relativos al inicio del chunk GM1G, que es
    justo el buffer `datos` que se esta recorriendo.
    """
    extra = 4 if version > VERSION_BUFFER_CON_EXTRA else 0
    out = []
    p = pos + 12
    for i in range(count):
        if p + 12 > len(datos):
            break
        desconocido, stride, n = struct.unpack_from("<III", datos, p)
        p += 12 + extra
        out.append({"stride": stride, "count": n, "offset": p})
        p += stride * n
    return out


def _buffers_ib(datos: bytes, pos: int, count: int, version: int) -> list[dict]:
    """Entradas de INDEX_BUFFER: count, bits por indice y donde empiezan los datos."""
    extra = 4 if version > VERSION_BUFFER_CON_EXTRA else 0
    out = []
    p = pos + 12
    for i in range(count):
        if p + 8 > len(datos):
            break
        n, bits = struct.unpack_from("<II", datos, p)
        p += 8 + extra
        if bits not in (16, 32):
            raise FormatoG1M("indices de %d bits en el buffer %d" % (bits, i))
        out.append({"count": n, "bits": bits, "offset": p})
        p += (bits // 8) * n
        p = (p + 3) & ~3
    return out


def _submeshes(datos: bytes, pos: int, count: int) -> list[dict]:
    campos = ("flags", "vb_index", "paleta_index", "hueso_index", "desconocido",
              "shader_index", "material_index", "ib_index", "desconocido2",
              "primitiva", "vb_offset", "vertex_count", "ib_offset", "index_count")
    out = []
    p = pos + 12
    for i in range(count):
        if p + 56 > len(datos):
            break
        vals = struct.unpack_from("<14I", datos, p)
        out.append(dict(zip(campos, vals)))
        p += 56
    return out


# ---------------------------------------------------------------------------
# Cifras de malla
# ---------------------------------------------------------------------------

def indice_a_triangulos(indices: list[int], topologia: str) -> list[tuple[int, int, int]]:
    """Convierte indices a triangulos segun la topologia.

    La tira sigue la convencion de Direct3D (el vertice impar invierte el orden),
    que es la que usa `gust_stuff` (`trianglestrip_to_list`) y la que produce
    los mismos triangulos que su `.ib` exportado.
    """
    if topologia == "trianglelist":
        return [(indices[i], indices[i + 1], indices[i + 2])
                for i in range(0, len(indices) - 2, 3)]
    if topologia == "trianglestrip":
        tris: list[tuple[int, int, int]] = []
        for i in range(len(indices) - 2):
            if i % 2 == 0:
                tris.append((indices[i], indices[i + 1], indices[i + 2]))
            else:
                tris.append((indices[i], indices[i + 2], indices[i + 1]))
        return tris
    return []


def geometria(g1m: dict) -> dict:
    """Vertices, indices y triangulos de todas las mallas de un G1M ya parseado."""
    gm = chunk(g1m, "GM1G") or chunk(g1m, "G1MG")
    if gm is None:
        raise FormatoG1M("el G1M no lleva chunk GM1G")
    g = parse_g1mg(gm["datos"])
    secs = {s["tipo"]: s for s in g["secciones"]}
    vbs = secs.get("VERTEX_BUFFERS", {}).get("buffers", [])
    ibs = secs.get("INDEX_BUFFER", {}).get("buffers", [])
    subs = secs.get("SUBMESH", {}).get("submeshes", [])
    mallas = []
    for i, sub in enumerate(subs):
        topo = TOPOLOGIA.get(sub["primitiva"], "?%d" % sub["primitiva"])
        ib = ibs[sub["ib_index"]] if sub["ib_index"] < len(ibs) else None
        indices: list[int] = []
        if ib is not None:
            ancho = ib["bits"] // 8
            raw = gm["datos"][ib["offset"]:ib["offset"] + ancho * ib["count"]]
            fmt = "<%d%s" % (ib["count"], "H" if ancho == 2 else "I")
            indices = list(struct.unpack(fmt, raw[:ancho * ib["count"]]))
            indices = indices[sub["ib_offset"]:sub["ib_offset"] + sub["index_count"]]
        tris = indice_a_triangulos(indices, topo)
        reales = [t for t in tris if len(set(t)) == 3]
        vb = vbs[sub["vb_index"]] if sub["vb_index"] < len(vbs) else None
        mallas.append({
            "submesh": i,
            "topologia": topo,
            "vertices": sub["vertex_count"],
            "vb_stride": vb["stride"] if vb else None,
            "vb_count": vb["count"] if vb else None,
            "indices": len(indices),
            "triangulos": len(tris),
            "triangulos_degenerados": len(tris) - len(reales),
            "triangulos_reales": len(reales),
            "conjunto_triangulos": sorted(tuple(sorted(t)) for t in reales),
            "secuencia_triangulos": [tuple(sorted(t)) for t in reales],
            "max_indice": max(indices) if indices else None,
        })
    return {"gm1g_version": g["version"], "secciones": [s["tipo"] for s in g["secciones"]],
            "mallas": mallas,
            "vertices": sum(m["vertices"] for m in mallas),
            "indices": sum(m["indices"] for m in mallas),
            "triangulos": sum(m["triangulos_reales"] for m in mallas)}


# ---------------------------------------------------------------------------
# G1T: cabecera y tabla de texturas
# ---------------------------------------------------------------------------

def parse_g1t(buf: bytes) -> dict:
    """Cabecera y tabla de un `.g1t` (textura) de KTGL.

    Cabecera de 28 B: magic | version ASCII | u32 tamano | u32 offset de tabla
    | u32 n texturas | u32 constante (24) | u32 extra.

    Si `offset_tabla == 28 + 4*n` hay ademas un array de `n` u32 de flags entre
    la cabecera y la tabla. Los offsets de la tabla son **relativos al inicio de
    la tabla**, no al fichero (medido: `tabla + offset[0]` cae justo donde acaba
    la tabla). Cada registro son 20 B (`<BBBBII`): mips | formato | (log2 ancho |
    log2 alto << 4) | reservado | flags | cabecera extendida, y detras los
    pixeles, cuyo tamano no se deduce del registro sin un catalogo de formatos
    (fuera del alcance de este lector).
    """
    if len(buf) < 28 or buf[:4] != MAGIC_G1T:
        raise FormatoG1M("no empieza por GT1G")
    version = buf[4:8].decode("ascii", "replace")
    tamano, tabla, n, constante, extra = struct.unpack_from("<5I", buf, 8)
    out = {"version": version, "tamano": tamano, "offset_tabla": tabla,
           "n_texturas": n, "constante": constante, "extra": extra,
           "flags": [], "texturas": []}
    if tabla == 28 + 4 * n:
        out["flags"] = list(struct.unpack_from("<%dI" % n, buf, 28))
    if n == 0 or tabla + 4 * n > len(buf):
        out["problemas"] = ["tabla de texturas fuera del fichero"]
        return out
    offsets = struct.unpack_from("<%dI" % n, buf, tabla)
    for i, rel in enumerate(offsets):
        p = tabla + rel
        if p + 20 > len(buf):
            out["texturas"].append({"i": i, "offset": p, "problemas": ["registro fuera"]})
            continue
        mips, fmt, wh, res, flags, ext = struct.unpack_from("<BBBBII", buf, p)
        out["texturas"].append({
            "i": i, "offset": p, "mips": mips >> 4, "formato": fmt,
            "ancho": 1 << (wh & 0xF), "alto": 1 << (wh >> 4),
            "reservado": res, "flags": flags, "cabecera_extra": ext,
        })
    return out


# ---------------------------------------------------------------------------
# Clasificacion de un blob del contenedor
# ---------------------------------------------------------------------------

def clasificar(blob: bytes) -> dict:
    """Que es este blob: textura, modelo (suelto o con envoltorio) o nada.

    El modelo del contenedor va detras de un envoltorio de 12 B
    (`u32 version=1 | u32 offset=12 | u32 tamano`), asi que el magic no esta en
    el byte 0. Mirar solo el offset 0 los pierde: es el falso negativo que este
    fichero evita.
    """
    if not blob:
        return {"tipo": "vacio"}
    if blob[:4] == MAGIC_G1T:
        return {"tipo": "g1t", "offset": 0}
    if blob[:4] == MAGIC_G1M:
        return {"tipo": "g1m", "offset": 0, "envoltorio": 0}
    for off in (4, 12, 16):
        if blob[off:off + 4] == MAGIC_G1M:
            env = blob[:off]
            return {"tipo": "g1m", "offset": off, "envoltorio": off,
                    "envoltorio_hex": env.hex()}
    return {"tipo": "otro"}


def problemas(buf: bytes, base: int = 0) -> list[str]:
    """Problemas estructurales de un G1M. Lista vacia = estructura valida."""
    try:
        g = parse_g1m(buf, base)
    except FormatoG1M as exc:
        return [str(exc)]
    fallos = list(g["problemas"])
    gm = chunk(g, "GM1G")
    if gm is None:
        fallos.append("falta el chunk GM1G")
        return fallos
    try:
        gmg = parse_g1mg(gm["datos"])
    except FormatoG1M as exc:
        fallos.append(str(exc))
        return fallos
    fallos.extend(gmg["problemas"])
    try:
        geo = geometria(g)
    except FormatoG1M as exc:
        fallos.append(str(exc))
        return fallos
    for m in geo["mallas"]:
        # El limite es el `vertex_count` del submesh, no el `count` de su buffer.
        # `vb_index` apunta a un conjunto de atributos, que es una lista de
        # buffers, y en varios modelos reales uno de esos buffers es un bloque
        # constante de un solo vertice (`count = 1`, 48 B de FOG/PSIZE/DEPTH que
        # gust_stuff repite por vertice). Con `vb_count` salian 4 falsos
        # positivos de 26 modelos extraidos de `.fdata` («referencia el vertice
        # 916 de 1»); con `vertices` los 26 pasan.
        if m["max_indice"] is not None and m["vertices"] and m["max_indice"] >= m["vertices"]:
            fallos.append("submesh %d referencia el vertice %d de %d"
                          % (m["submesh"], m["max_indice"], m["vertices"]))
    return fallos


def diferencias(a: bytes, b: bytes) -> list[dict]:
    """Tramos de bytes que difieren entre dos buffers (con la longitud aparte)."""
    tramos = []
    n = min(len(a), len(b))
    i = 0
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            tramos.append({"inicio": i, "fin": j, "bytes": j - i})
            i = j
        else:
            i += 1
    if len(a) != len(b):
        tramos.append({"inicio": n, "fin": max(len(a), len(b)),
                       "bytes": abs(len(a) - len(b)), "longitud": "a=%d b=%d" % (len(a), len(b))})
    return tramos

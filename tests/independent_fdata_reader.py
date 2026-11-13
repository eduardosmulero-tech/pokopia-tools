#!/usr/bin/env python3
"""Lector independiente de `.fdata` (PDRK/IDRK), para no validar con el mismo codigo.

Escrito aparte de `pokopia/fdata.py`: no lo importa y no reutiliza su codigo.
Usa `mmap` + `array` + indices explicitos, y recorre las entradas con su propia
aritmetica, para que una verificacion con este lector no sea "mi lector valida a
mi escritor".

Uso:
    python tests/independent_fdata_reader.py A.fdata
    python tests/independent_fdata_reader.py A.fdata --contra B.fdata
    python tests/independent_fdata_reader.py A.fdata --json detalle.json

Imprime un JSON con: cabecera, numero de entradas, tamano, offsets, y por entrada
el sha256 del payload decodificado (y del payload tal cual va en el fichero).
"""

import array
import hashlib
import json
import mmap
import os
import struct
import sys
import zlib

PDRK = b"PDRK0000"
IDRK = b"IDRK0000"
CABECERA = 16
CAB_ENTRADA = 48
ALINEA = 16


def sube(n, a=ALINEA):
    return ((n + a - 1) // a) * a


def recorre(mm):
    """[(offset, entry_size, cmp, unc, tipo, hash, ktid, flags, meta)]"""
    if bytes(mm[:8]) != PDRK:
        raise SystemExit("no empieza por PDRK0000")
    tam_cabecera = struct.unpack_from("<I", mm, 8)[0]
    if tam_cabecera < CABECERA:
        raise SystemExit("cabecera de %d B" % tam_cabecera)
    campos3 = struct.unpack_from("<I", mm, 12)[0]
    filas = []
    pos = tam_cabecera
    total = len(mm)
    while pos + CAB_ENTRADA <= total:
        if bytes(mm[pos:pos + 8]) != IDRK:
            raise SystemExit("en 0x%x no hay IDRK0000" % pos)
        entry_size, cmp_, unc = struct.unpack_from("<3Q", mm, pos + 8)
        tipo, nh, ktid, flags = struct.unpack_from("<4I", mm, pos + 32)
        meta = entry_size - cmp_ - CAB_ENTRADA
        if entry_size < CAB_ENTRADA or meta < 0:
            raise SystemExit("entrada en 0x%x con tamanos imposibles: %d/%d/%d"
                             % (pos, entry_size, cmp_, unc))
        if pos + entry_size > total:
            raise SystemExit("entrada en 0x%x acaba en %d y el fichero mide %d"
                             % (pos, pos + entry_size, total))
        filas.append((pos, entry_size, cmp_, unc, tipo, nh, ktid, flags, meta))
        pos = sube(pos + entry_size)
    return tam_cabecera, campos3, filas, pos


def payload(mm, fila):
    """Devuelve los bytes descomprimidos de una entrada (o los crudos)."""
    offset, entry_size, cmp_, unc, _tipo, _nh, _ktid, flags, meta = fila
    inicio = offset + CAB_ENTRADA + meta
    if cmp_ == unc:
        return bytes(mm[inicio:inicio + unc])
    cabecera_trozo = 4 if flags & 0x100000 else 10
    salida = bytearray()
    pos = inicio
    fin = inicio + cmp_
    while len(salida) < unc:
        if pos + cabecera_trozo > fin:
            raise SystemExit("sin cabecera de trozo en 0x%x" % pos)
        if cabecera_trozo == 4:
            zsize = struct.unpack_from("<I", mm, pos)[0]
        else:
            zsize = struct.unpack_from("<H", mm, pos)[0]
        pos += cabecera_trozo
        if pos + zsize > fin:
            raise SystemExit("trozo de %d B en 0x%x se sale" % (zsize, pos))
        salida += zlib.decompress(bytes(mm[pos:pos + zsize]))
        pos += zsize
    if len(salida) != unc:
        raise SystemExit("los trozos dan %d B y se declaran %d" % (len(salida), unc))
    return bytes(salida)


def huellas(path):
    f = open(path, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        tam_cabecera, campo3, filas, fin = recorre(mm)
        datos = []
        for fila in filas:
            offset, entry_size, cmp_, unc, _tipo, nh, _ktid, flags, meta = fila
            crudo = payload(mm, fila)
            tal_cual = bytes(mm[offset + CAB_ENTRADA + meta:
                                offset + CAB_ENTRADA + meta + cmp_])
            datos.append({
                "offset": offset,
                "name_hash": "0x%08x" % nh,
                "entry_size": entry_size,
                "compressed_size": cmp_,
                "uncompressed_size": unc,
                "metadata_size": meta,
                "flags": flags,
                "bytes": len(crudo),
                "sha256": hashlib.sha256(crudo).hexdigest(),
                "sha256_almacenado": hashlib.sha256(tal_cual).hexdigest(),
            })
        global_ = hashlib.sha256()
        for fila in datos:
            global_.update(("%d:%d:%s\n" % (fila["offset"], fila["bytes"],
                                            fila["sha256"])).encode())
        return {
            "fichero": os.path.basename(path),
            "tamano": len(mm),
            "cabecera": tam_cabecera,
            "campo3": campo3,
            "entradas": len(datos),
            "fin_de_la_ultima_alineada": fin,
            "cola": len(mm) - fin,
            "sha256_global": global_.hexdigest(),
            "detalle": datos,
        }
    finally:
        mm.close()
        f.close()


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    primero = huellas(argv[1])
    resumen = {k: v for k, v in primero.items() if k != "detalle"}
    print(json.dumps(resumen, indent=1))
    if "--json" in argv:
        destino = argv[argv.index("--json") + 1]
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(primero, fh)
        print("detalle en %s" % destino)
    if "--contra" in argv:
        k = argv.index("--contra")
        otro = huellas(argv[k + 1])
        a = {x["name_hash"]: x for x in primero["detalle"]}
        b = {x["name_hash"]: x for x in otro["detalle"]}
        distintas = [h for h in a
                     if h not in b or a[h]["sha256"] != b[h]["sha256"]]
        movidas = sum(1 for h in a if h in b and a[h]["offset"] != b[h]["offset"])
        print(json.dumps({
            "comparado_con": otro["fichero"],
            "entradas_a": len(a),
            "entradas_b": len(b),
            "mismos_name_hash": sorted(a) == sorted(b),
            "payloads_identicos": len(a) - len(distintas),
            "payloads_distintos": len(distintas),
            "primeros_distintos": distintas[:20],
            "entradas_movidas_de_offset": movidas,
            "mismo_tamano": primero["tamano"] == otro["tamano"],
            "sha256_global_igual": primero["sha256_global"] == otro["sha256_global"],
        }, indent=1))
        return 0 if not distintas and sorted(a) == sorted(b) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

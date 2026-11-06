#!/usr/bin/env python3
"""Lector independiente del contenedor LD_C0_R.BIN / LI_C0_R.IDX.

Escrito aparte de pkp_pack.py, sin importarlo y sin reutilizar su codigo, para
que C2 no sea "mi lector valida a mi escritor". Aqui se usa mmap + array en
lugar de bytes en RAM, y el recorrido de bloques se hace con aritmetica de
indices explicita.

Uso:
    python tests/independent_reader.py LI_C0_R.IDX LD_C0_R.BIN
    python tests/independent_reader.py A.IDX A.BIN --contra B.IDX B.BIN

Imprime un JSON con sha256 por entrada y un sha256 global del flujo de
longitudes+hashes, mas el recuento de entradas.
"""

import array
import hashlib
import json
import mmap
import os
import struct
import sys
import zlib

HEAD = 12
UNIT = 128


def align(n):
    return ((n + UNIT - 1) // UNIT) * UNIT


def lee_indice(path):
    crudo = open(path, "rb").read()
    if len(crudo) % 32:
        raise SystemExit("%s: el indice no cuadra a 32 bytes" % path)
    valores = array.array("q")
    valores.frombytes(crudo)
    if sys.byteorder != "little":
        valores.byteswap()
    return [tuple(valores[k:k + 4]) for k in range(0, len(valores), 4)]


def bloques(mm, entrada):
    """Devuelve la lista de trozos descomprimidos de una entrada comprimida."""
    off, raw, packed, flag = entrada
    if packed == 0:
        return []
    if flag == 0:
        return [bytes(mm[off:off + raw])]
    tam_bloque, cuantos, tam_real = struct.unpack("<III", mm[off:off + HEAD])
    if tam_real != raw:
        raise SystemExit("entrada en %d: tamano real %d != %d" % (off, tam_real, raw))
    tabla = array.array("I")
    tabla.frombytes(mm[off + HEAD:off + HEAD + 4 * cuantos])
    if sys.byteorder != "little":
        tabla.byteswap()
    cursor = align(HEAD + 4 * cuantos)
    trozos = []
    for k in range(cuantos):
        hueco = tabla[k]
        crudo = bytes(mm[off + cursor:off + cursor + hueco])
        esperado = min(tam_bloque, raw - k * tam_bloque)
        dato = None
        if hueco > 4 and len(crudo) > 4 and crudo[4] == 0x78:
            try:
                dato = zlib.decompress(crudo[4:])
            except zlib.error:
                dato = None
            if dato is not None and len(dato) != esperado:
                dato = None
        if dato is None:
            if hueco != esperado:
                raise SystemExit("entrada en %d bloque %d: hueco %d, esperado %d"
                                 % (off, k, hueco, esperado))
            dato = crudo
        trozos.append(dato)
        cursor = align(cursor + hueco)
    if cursor != packed:
        raise SystemExit("entrada en %d: el recorrido acaba en %d y no en %d"
                         % (off, cursor, packed))
    return trozos


def huellas(idx_path, bin_path):
    indice = lee_indice(idx_path)
    f = open(bin_path, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        filas = []
        total = 0
        for i, entrada in enumerate(indice):
            datos = b"".join(bloques(mm, entrada))
            if len(datos) != entrada[1]:
                raise SystemExit("entrada %d: %d bytes y el indice dice %d"
                                 % (i, len(datos), entrada[1]))
            total += len(datos)
            filas.append([i, len(datos), hashlib.sha256(datos).hexdigest()])
    finally:
        mm.close()
        f.close()
    global_ = hashlib.sha256()
    for fila in filas:
        global_.update(("%d:%d:%s\n" % tuple(fila)).encode())
    return {"fichero": os.path.basename(bin_path), "entradas": len(filas),
            "bytes": total, "sha256_global": global_.hexdigest(),
            "sha256_por_entrada": filas}


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    primero = huellas(argv[1], argv[2])
    print(json.dumps({k: v for k, v in primero.items() if k != "sha256_por_entrada"},
                     indent=1))
    if "--json" in argv:
        destino = argv[argv.index("--json") + 1]
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(primero, fh)
        print("detalle en %s" % destino)
    if "--contra" in argv:
        k = argv.index("--contra")
        otro = huellas(argv[k + 1], argv[k + 2])
        iguales = sum(1 for a, b in zip(primero["sha256_por_entrada"],
                                        otro["sha256_por_entrada"]) if a == b)
        distintos = [a[0] for a, b in zip(primero["sha256_por_entrada"],
                                          otro["sha256_por_entrada"]) if a != b]
        print(json.dumps({
            "comparado_con": otro["fichero"],
            "entradas_a": primero["entradas"],
            "entradas_b": otro["entradas"],
            "identicas": iguales,
            "distintas": len(distintos),
            "primeras_distintas": distintos[:20],
            "sha256_global_igual": primero["sha256_global"] == otro["sha256_global"],
        }, indent=1))
        return 0 if not distintos and primero["entradas"] == otro["entradas"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

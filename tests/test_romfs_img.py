"""Lee y parchea un RomFS.img (DMROMFS1) sin dump: la imagen se fabrica en el test.

Cubre lo que las herramientas de `tools/romfs/` prometen y es facil de romper:

* `img_inspect.py` saca nombre, offset y tamano de cada entrada (y los ordena como el
  arbol, no como el fichero);
* `img_patch.py` cambia una entrada sin mover las demas, y `--restore` deja el fichero
  **byte a byte** como estaba (sha256), que es la unica forma de que un parche sea
  reversible de verdad;
* `--out` no pisa una copia existente;
* escribir en el sitio sobre una ruta protegida (`PKP_PROTECTED`) se rechaza.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(RAIZ, "tools", "romfs")


def _cargar(nombre: str):
    """Carga tools/romfs/<nombre>.py registrandolo antes de ejecutarlo (dataclasses)."""
    ruta = os.path.join(TOOLS, nombre + ".py")
    spec = importlib.util.spec_from_file_location("romfs_" + nombre, ruta)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


inspect_mod = _cargar("img_inspect")
patch_mod = _cargar("img_patch")


def hacer_img(datos: dict[str, bytes]) -> bytes:
    """Imagen minima valida: raiz con a.txt y dir/b.txt, en anchura y ordenada por nombre."""
    nombres = ["", "a.txt", "dir", "b.txt"]
    # datos empaquetados detras de la cabecera
    posiciones: dict[str, tuple[int, int]] = {}
    cuerpo = b""
    for nombre in ("a.txt", "b.txt"):
        posiciones[nombre] = (32 + len(cuerpo), len(datos[nombre]))
        cuerpo += datos[nombre]
    entradas = [
        (1, 2, 0, 0, 0, 0),                                  # raiz: hijos 1..2
        (posiciones["a.txt"][0], posiciones["a.txt"][1], 0, 5, 1, 0),
        (3, 1, 0, 3, 0, 0),                                  # dir: hijo 3
        (posiciones["b.txt"][0], posiciones["b.txt"][1], 0, 5, 1, 0),
    ]
    pozo = b"a.txtdirb.txt"
    offsets = {"a.txt": 0, "dir": 5, "b.txt": 8}
    tabla = b""
    for nombre, ent in zip(nombres, entradas):
        a, b, _, _, typ, pad = ent
        nlen = len(nombre)
        tabla += struct.pack("<QQIHBB", a, b, offsets.get(nombre, 0) if nombre else 0, nlen, typ, pad)
    ioff = 32 + len(cuerpo)
    indice = tabla + pozo
    cabecera = b"DMROMFS1" + struct.pack("<QQQ", ioff, len(indice), len(entradas))
    return cabecera + cuerpo + indice


def escribir(tmp_path, nombre="RomFS.img") -> str:
    ruta = tmp_path / nombre
    ruta.write_bytes(hacer_img({"a.txt": b"original A", "b.txt": b"original B"}))
    return str(ruta)


def test_inspect_saca_nombre_offset_y_tamano(tmp_path):
    imagen = escribir(tmp_path)
    im = inspect_mod.Img(imagen)
    assert im.n == 4
    rutas = [(r, im.ent[k][0], im.ent[k][1], im.ent[k][4]) for r, k in im.walk()]
    assert rutas == [
        ("/a.txt", 32, len(b"original A"), 1),
        ("/dir", 3, 1, 0),
        ("/dir/b.txt", 32 + len(b"original A"), len(b"original B"), 1),
    ]
    assert im.read(1) == b"original A"


def test_patch_cambia_una_entrada_y_no_toca_las_demas(tmp_path):
    imagen = escribir(tmp_path)
    nuevo = tmp_path / "nuevo.bin"
    nuevo.write_bytes(b"PARCHEADO")
    antes = inspect_mod.Img(imagen)
    otra = antes.read(3)

    assert patch_mod.main([imagen, "a.txt", str(nuevo)]) == 0

    despues = inspect_mod.Img(imagen)
    assert despues.read(1) == b"PARCHEADO"
    assert despues.read(3) == otra, "la otra entrada no se mueve ni cambia"
    assert despues.size == antes.size + len(b"PARCHEADO")


def test_restore_devuelve_el_fichero_byte_a_byte(tmp_path):
    imagen = escribir(tmp_path)
    original = hashlib.sha256(open(imagen, "rb").read()).hexdigest()
    im = inspect_mod.Img(imagen)
    a, b = im.ent[1][0], im.ent[1][1]
    ioff, isz = im.ioff, im.isz

    nuevo = tmp_path / "nuevo.bin"
    nuevo.write_bytes(b"X" * 64)
    assert patch_mod.main([imagen, "a.txt", str(nuevo)]) == 0
    assert hashlib.sha256(open(imagen, "rb").read()).hexdigest() != original

    assert patch_mod.main([imagen, "--restore", "a.txt", "--ioff", str(ioff), "--isz", str(isz),
                           "--a", str(a), "--b", str(b)]) == 0
    assert hashlib.sha256(open(imagen, "rb").read()).hexdigest() == original


def test_patch_no_pisa_una_copia_que_ya_existe(tmp_path):
    imagen = escribir(tmp_path)
    copia = tmp_path / "copia.img"
    copia.write_bytes(b"no me toques")
    nuevo = tmp_path / "nuevo.bin"
    nuevo.write_bytes(b"z")
    with pytest.raises(SystemExit):
        patch_mod.main([imagen, "a.txt", str(nuevo), "--out", str(copia)])
    assert copia.read_bytes() == b"no me toques"


def test_escribir_en_el_sitio_sobre_una_ruta_protegida_se_rechaza(tmp_path, monkeypatch):
    imagen = escribir(tmp_path)
    monkeypatch.setenv("PKP_PROTECTED", str(tmp_path))
    nuevo = tmp_path / "nuevo.bin"
    nuevo.write_bytes(b"z")
    with pytest.raises(PermissionError):
        patch_mod.main([imagen, "a.txt", str(nuevo)])
    assert open(imagen, "rb").read() == hacer_img({"a.txt": b"original A", "b.txt": b"original B"})

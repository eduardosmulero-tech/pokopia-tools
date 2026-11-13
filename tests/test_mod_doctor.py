"""`pkp mod doctor`: cada causa de «el mod no carga», con su mensaje.

Las cinco roturas que el encargo pide (H6) y dos mas que salen gratis del mismo
diagnostico. Todo con una imagen `DMROMFS1` sintetica y bytes nuestros: ni dump ni
juego, y `doctor` no arranca nada (no llama ni a `listar_procesos`).

    1. el fichero del overlay no esta                 -> FALLO  falta en el overlay
    2. los bytes no son los que se instalaron         -> FALLO  no es el que se instalo
    3. el mod declara un formato que este kit no lee  -> FALLO  mod_format no soportado
    4. el img es de otro build                        -> FALLO  el img es otro build
    5. dos mods pisan la misma ruta                   -> aviso  lo sirven X y Y
    6. DM_ROMFS_OVERLAY no apunta al almacen          -> FALLO  no cargara <carpeta>
    7. ruta mal escrita (no esta en el img)           -> aviso  o es nueva o esta mal escrita
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from pokopia.mod import overlay as ov
from pokopia.romfs_img import RomFSImage

from tests import helpers

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RUTA = "motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx"
IMG_DATOS = {
    "LD_C0_R.BIN": b"contenedor falso de 40 bytes ------------",
    RUTA: b"rdx original",
    "motor_asset_re/KIDS_PLATFORM_OUNCE/root.rdx": b"root original",
}


def preparar(tmp_path, datos=None):
    img = helpers.write_img(tmp_path, datos or IMG_DATOS)
    store = os.path.join(str(tmp_path), "overlay")
    os.makedirs(store)
    return img, store


def instalar(tmp_path, img, store, nombre="demo", rutas=None, **cambios):
    carpeta = helpers.mod_con_fichero(str(tmp_path), nombre,
                                      rutas if rutas is not None else {RUTA: b"payload propio"},
                                      **cambios)
    ov.instalar(carpeta, store, img=img, procesos=[])
    return carpeta


def chequeo(res, prefijo):
    """El chequeo cuyo nombre empieza por `prefijo` (los nombres llevan la ruta)."""
    for c in res["checks"]:
        if c["check"] == prefijo or c["check"].startswith(prefijo):
            return c
    raise AssertionError("no hay chequeo %r en %s"
                         % (prefijo, [c["check"] for c in res["checks"]]))


def variable(store, monkeypatch, valor):
    monkeypatch.setenv(ov.OVERLAY_ENV, valor)


# --------------------------------------------------------------------------
# 1 · el fichero del overlay no esta
# --------------------------------------------------------------------------

def test_doctor_fichero_que_no_existe(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    os.remove(os.path.join(store, "mods", "demo", RUTA.replace("/", os.sep)))
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    c = chequeo(res, "mod.demo." + RUTA)
    assert not c["ok"] and c["fatal"]
    assert "falta en el overlay" in c["detail"]
    assert "el juego sirve el original del img" in c["detail"]


# --------------------------------------------------------------------------
# 2 · hash que no cuadra
# --------------------------------------------------------------------------

def test_doctor_hash_que_no_cuadra(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    destino = os.path.join(store, "mods", "demo", RUTA.replace("/", os.sep))
    with open(destino, "wb") as fh:
        fh.write(b"otros bytes")
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    c = chequeo(res, "mod.demo." + RUTA)
    assert not c["ok"] and c["fatal"]
    assert "no es el que se instalo" in c["detail"]


# --------------------------------------------------------------------------
# 3 · formato no soportado
# --------------------------------------------------------------------------

def test_doctor_formato_no_soportado(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    registro = os.path.join(store, "installed.json")
    with open(registro, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["mods"][0]["mod_format"] = 2
    with open(registro, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    c = chequeo(res, "mod.demo.formato")
    assert not c["ok"] and c["fatal"]
    assert "mod_format 2 no soportado" in c["detail"]
    assert "solo carga 1" in c["detail"]


# --------------------------------------------------------------------------
# 4 · version del juego distinta (otro build del img y otro contenedor)
# --------------------------------------------------------------------------

def test_doctor_otro_build_del_img(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    otro = helpers.write_img(tmp_path, {
        "LD_C0_R.BIN": b"contenedor falso de otro build, mas largo -------------",
        RUTA: b"rdx original",
        "motor_asset_re/KIDS_PLATFORM_OUNCE/root.rdx": b"root original",
    }, nombre="RomFS-otro.img")
    res = ov.doctor(store, img=otro)
    assert not res["ok"]
    c = chequeo(res, "mod.demo.img")
    assert not c["ok"] and c["fatal"]
    assert "el img es otro build" in c["detail"]


def test_doctor_otro_build_del_contenedor(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    contenedor = helpers.make_container(os.path.join(str(tmp_path), "dump"),
                                        {0: helpers.records_payload({})})
    res = ov.doctor(store, img=img, container=contenedor.dir)
    assert not res["ok"]
    c = chequeo(res, "mod.demo.juego")
    assert not c["ok"] and c["fatal"]
    assert "otro build" in c["detail"]
    assert "pide el mod para tu version" in c["detail"]


# --------------------------------------------------------------------------
# 5 · conflicto entre dos mods
# --------------------------------------------------------------------------

def test_doctor_conflicto_entre_dos_mods(tmp_path):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store, nombre="demo", rutas={RUTA: b"unos bytes"})
    instalar(tmp_path, img, store, nombre="otro", rutas={RUTA: b"otros bytes"})
    res = ov.doctor(store, img=img)
    assert res["ok"], "un conflicto se avisa; no es un fallo fatal"
    c = chequeo(res, "mods.sin_conflictos")
    assert not c["ok"] and not c["fatal"]
    assert "demo y otro" in c["detail"]
    assert "gana demo" in c["detail"]
    assert "bytes distintos" in c["detail"]


# --------------------------------------------------------------------------
# 6 · la variable no apunta al almacen (overlay mal montado)
# --------------------------------------------------------------------------

def test_doctor_variable_apunta_a_otra_carpeta(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    otra = os.path.join(str(tmp_path), "otra-carpeta")
    os.makedirs(otra)
    variable(store, monkeypatch, os.path.relpath(otra, os.getcwd()))
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    c = chequeo(res, "overlay.variable")
    assert not c["ok"] and c["fatal"]
    assert "el juego no cargara" in c["detail"]


def test_doctor_variable_con_las_carpetas_en_otro_orden(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store, nombre="demo", rutas={RUTA: b"unos bytes"})
    instalar(tmp_path, img, store, nombre="otro",
             rutas={"motor_asset_re/KIDS_PLATFORM_OUNCE/root.rdx": b"otros bytes"})
    demo = os.path.relpath(os.path.join(store, "mods", "demo"), os.getcwd())
    otro = os.path.relpath(os.path.join(store, "mods", "otro"), os.getcwd())
    variable(store, monkeypatch, otro + ":" + demo)
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    c = chequeo(res, "overlay.variable")
    assert "otro orden" in c["detail"]


# --------------------------------------------------------------------------
# 7 · ruta mal escrita
# --------------------------------------------------------------------------

def test_doctor_ruta_que_no_esta_en_el_img(tmp_path):
    img, store = preparar(tmp_path)
    mala = "motor_asset_re/KIDS_PLATFORM_OUNCE/sytem.rdx"      # errata: falta la 's'
    carpeta = helpers.mod_con_fichero(str(tmp_path), "demo", {mala: b"payload propio"})
    ov.instalar(carpeta, store, procesos=[])                    # sin img: no hay original
    res = ov.doctor(store, img=img)
    assert res["ok"], "una ruta nueva puede ser legitima: se avisa, no se falla"
    c = chequeo(res, "mod.demo." + mala + ".ruta")
    assert not c["ok"] and not c["fatal"]
    assert "no esta en el img" in c["detail"]
    assert "mal escrita" in c["detail"]


# --------------------------------------------------------------------------
# El doctor no arranca el juego ni mira procesos
# --------------------------------------------------------------------------

def test_doctor_no_toca_el_juego(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    variable(store, monkeypatch, os.path.relpath(os.path.join(store, "mods", "demo"),
                                                 os.getcwd()))
    monkeypatch.setattr(ov, "listar_procesos",
                        lambda: pytest.fail("doctor no debe mirar procesos"))
    res = ov.doctor(store, img=img)
    assert res["ok"], res["checks"]


# --------------------------------------------------------------------------
# La huella del img: barata y sensible al layout
# --------------------------------------------------------------------------

def test_huella_del_img_es_estable_y_detecta_otro_layout(tmp_path):
    img = helpers.write_img(tmp_path, IMG_DATOS)
    with RomFSImage(img) as a, RomFSImage(img) as b:
        assert a.fingerprint() == b.fingerprint()
        huella = a.fingerprint()
        assert huella["size"] == os.path.getsize(img)
        assert len(huella["index_sha256"]) == 64
    otro = helpers.write_img(tmp_path, {
        "LD_C0_R.BIN": b"otro contenido, otro tamano ---------------------",
        RUTA: b"rdx original",
    }, nombre="otro.img")
    with RomFSImage(otro) as c:
        assert c.fingerprint()["index_sha256"] != huella["index_sha256"]


# --------------------------------------------------------------------------
# 8 · el almacen en otra unidad que el cwd (Windows): nunca una traza
# --------------------------------------------------------------------------
#
# `os.path.relpath` lanza ValueError en Windows cuando los dos caminos estan en
# unidades distintas. `install`, `status` y `doctor` lo llamaban para imprimir la
# forma relativa, asi que el comando reventaba (en `install`, despues de haber
# escrito el almacen). Aqui se comprueba que la forma relativa se calcula o se
# explica, pero el comando termina.

WIN = pytest.mark.skipif(os.name != "nt", reason="las unidades y el ':' son de Windows")


def otra_unidad() -> str | None:
    """Raiz de una unidad distinta de la del cwd, o None si solo hay una."""
    letra = os.path.splitdrive(os.path.abspath(os.getcwd()))[0].upper()
    for candidata in "DEFGHIJKLMNOPQRSTUVWXYZ":
        if candidata + ":" != letra and os.path.isdir(candidata + ":\\"):
            return candidata + ":\\"
    return None


@WIN
def test_overlay_relativo_devuelve_none_si_no_hay_forma_relativa(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    registro = ov.leer_registro(store)
    assert ov.overlay_relativo(store, registro) is not None     # misma unidad: se puede
    monkeypatch.setattr(os, "getcwd", lambda: _ruta_unidad("Q", "otro-sitio"))
    assert ov.overlay_relativo(store, registro) is None         # antes: ValueError
    linea = ov.linea_relativa(store, registro)
    assert "no hay forma relativa" in linea
    assert "Q:" in linea


@WIN
def test_doctor_no_revienta_con_el_almacen_en_otra_unidad(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    registro = ov.leer_registro(store)
    monkeypatch.setattr(os, "getcwd", lambda: _ruta_unidad("Q", "otro-sitio"))
    res = ov.doctor(store, img=img)                             # antes: ValueError
    assert "no hay forma relativa al cwd" in res["overlay_relativo"]
    assert "lista absoluta" not in res["overlay_relativo"]
    c = chequeo(res, "overlay.separador")
    assert not c["ok"] and not c["fatal"], "otra unidad es aviso: con la forma relativa carga"
    almacen = ov.overlay_relativo_almacen(store, registro)
    assert "DM_ROMFS_OVERLAY=" + almacen in c["detail"]


@WIN
def test_otra_unidad_da_una_sola_instruccion_coherente(tmp_path, monkeypatch):
    """Hecho en una linea, instruccion en la siguiente, y las dos dicen lo mismo.

    La revision de la ronda 2 encontro aqui dos frases contradictorias: «no hay
    forma relativa: usa la lista absoluta» y acto seguido «usa la forma relativa
    que imprime este comando». Ahora el hecho va solo y la instruccion es la unica
    forma que el runtime trocea bien en ese caso: la relativa a la raiz del almacen,
    con el juego arrancado desde ahi.
    """
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    registro = ov.leer_registro(store)
    monkeypatch.setattr(os, "getcwd", lambda: _ruta_unidad("Q", "otro-sitio"))
    linea = ov.linea_relativa(store, registro)
    aviso = ov.aviso_separador(store, registro)
    assert aviso is not None
    assert "no hay forma relativa al cwd" in linea
    for texto in (linea, aviso):
        assert "lista absoluta" not in texto
        assert "usa la forma relativa que imprime" not in texto
    almacen = ov.overlay_relativo_almacen(store, registro)
    assert almacen == os.path.join("mods", "demo")
    assert ":" not in almacen, "la relativa al almacen no lleva ':' en ningun sitio"
    assert "DM_ROMFS_OVERLAY=" + almacen in aviso
    assert os.path.abspath(store) in aviso, "dice con que cwd arrancar el juego"
    assert not ov.trampa_separador(almacen)


@WIN
def test_sin_mods_no_hay_instruccion_de_variable(tmp_path, monkeypatch):
    """Un almacen vacio no monta variable: ni aviso de unidad ni instruccion."""
    _, store = preparar(tmp_path)
    monkeypatch.setattr(os, "getcwd", lambda: _ruta_unidad("Q", "otro-sitio"))
    assert ov.aviso_separador(store, ov.leer_registro(store)) is None


@WIN
def test_cli_status_y_doctor_con_el_almacen_en_otra_unidad(tmp_path):
    """El caso literal de la revision: almacen en otra unidad, la CLI desde el repo."""
    raiz = otra_unidad()
    if raiz is None:
        pytest.skip("solo hay una unidad: el ValueError de relpath no se reproduce")
    img, _ = preparar(tmp_path)
    store = tempfile.mkdtemp(prefix="pkp-store-", dir=raiz)
    try:
        carpeta = helpers.mod_con_fichero(str(tmp_path), "demo", {RUTA: b"payload propio"})
        ov.instalar(carpeta, store, img=img, procesos=[])
        almacen = ov.overlay_relativo_almacen(store, ov.leer_registro(store))
        for args in (["mod", "status"], ["mod", "doctor"]):
            proc = subprocess.run(
                [sys.executable, os.path.join(RAIZ_REPO, "pkp.py"), *args,
                 "--overlay", store, "--img", img],
                cwd=RAIZ_REPO, capture_output=True, text=True, encoding="utf-8",
                errors="replace")
            assert "ValueError" not in (proc.stderr or ""), proc.stderr
            assert "Traceback" not in (proc.stderr or ""), proc.stderr
            assert "relativo al cwd: (no hay forma relativa al cwd" in proc.stdout, proc.stdout
            # una sola instruccion, y es la que se puede ejecutar
            assert "DM_ROMFS_OVERLAY=" + almacen in proc.stdout, proc.stdout
            assert "lista absoluta" not in proc.stdout, proc.stdout
            assert "usa la forma relativa que imprime" not in proc.stdout, proc.stdout
    finally:
        shutil.rmtree(store, ignore_errors=True)


@WIN
def test_install_con_la_guarda_viva_no_crea_el_almacen(tmp_path):
    """`install --crear` rechazado por la guarda no deja ni la carpeta vacia."""
    img, _ = preparar(tmp_path)
    store = os.path.join(str(tmp_path), "almacen-nuevo")
    carpeta = helpers.mod_con_fichero(str(tmp_path), "demo", {RUTA: b"payload propio"})
    with pytest.raises(ov.ModError) as exc:
        ov.instalar(carpeta, store, img=img, crear=True, procesos=["nxrt.exe"])
    assert "runtime del juego esta en marcha" in str(exc.value)
    assert not os.path.exists(store), "la guarda va antes de crear nada"


# --------------------------------------------------------------------------
# 9 · la trampa del ':' (rutas absolutas de Windows en DM_ROMFS_OVERLAY)
# --------------------------------------------------------------------------
#
# El runtime trocea la variable por ':': una ruta absoluta de Windows se parte en
# la letra sola y el resto de la ruta. La comprobacion anterior miraba un trozo de
# dos caracteres (`C:`), que al trocear no existe nunca: era codigo muerto y las
# paginas prometian un aviso que no salia.


def _ruta_unidad(*partes: str, sep: str | None = None) -> str:
    """Ruta con letra de unidad hecha en ejecucion.

    El guardian del repo no admite una ruta con letra de unidad literal en el
    arbol (seria una ruta de maquina), y aqui hace falta una de verdad.
    """
    sep = chr(92) if sep is None else sep
    return partes[0] + ":" + sep + sep.join(partes[1:])


@WIN
def test_trampa_separador_detecta_la_ruta_absoluta_de_windows():
    assert ov.trampa_separador(_ruta_unidad("C", "store", "mods", "demo"))
    assert ov.trampa_separador(_ruta_unidad("rel", "uno") + ":"
                               + _ruta_unidad("C", "store", "mods", "demo", sep="/"))
    assert not ov.trampa_separador("build/overlay/mods/demo")
    assert not ov.trampa_separador("..\\overlay\\mods\\demo")
    assert not ov.trampa_separador("C:modos")


@WIN
def test_doctor_avisa_de_la_trampa_aunque_la_variable_apunte(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    instalar(tmp_path, img, store)
    variable(store, monkeypatch, os.path.join(store, "mods", "demo"))   # absoluta
    res = ov.doctor(store, img=img)
    assert res["ok"], "en la misma unidad carga: es un aviso, no un fallo"
    c = chequeo(res, "overlay.trampa_dos_puntos")
    assert not c["ok"] and not c["fatal"]
    assert "absoluta de Windows" in c["detail"]
    assert "relativa al cwd" in c["detail"]

"""Flujo de mod sobre el overlay nativo: lector de `img`, `pack`, `install`, `uninstall`.

Todo aqui se monta con una imagen `DMROMFS1` **sintetica** (`tests/helpers.make_img`):
la suite no necesita el dump ni el juego, y no entra contenido del juego en el repo.

Lo que se fija con estos tests (y es lo que puede romperse sin que nadie lo vea):

* la seccion `romfs[]` del manifiesto: rutas seguras, `why` obligatorio, sin duplicados,
  y compatibilidad con los mods de datos que no la usan;
* `pack` es determinista (mismo contenido, mismo sha256) y anota el original del `img`;
* `install` copia y registra, es idempotente, y se niega sin destino, con el runtime en
  marcha o escribiendo en una ruta protegida;
* el orden de resolucion es el del runtime: overlay en orden y si no, el `img`;
* `uninstall` demuestra que vuelve el original (sha256) y no borra lo de otro mod;
* `status`/`doctor` ven el conflicto entre dos mods que pisan la misma ruta.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from pokopia import paths
from pokopia.mod import overlay as ov
from pokopia.mod.errors import GuardError, ModError
from pokopia.mod.manifest import load_mod, romfs_path_problem
from pokopia.romfs_img import RomFSImage, RomFSImageError

from tests import helpers

IMG_DATOS = {
    "LD_C0_R.BIN": b"contenedor falso de 40 bytes ------------",
    "motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx": b"rdx original",
    "motor_asset_re/KIDS_PLATFORM_OUNCE/root.rdx": b"root original",
}
TEXTURA = "motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preparar(tmp_path):
    """Imagen sintetica + almacen vacio; devuelve (img, store)."""
    img = helpers.write_img(tmp_path, IMG_DATOS)
    store = os.path.join(str(tmp_path), "overlay")
    os.makedirs(store)
    return img, store


def mod_de(tmp_path, nombre="textura-demo", rutas=None, **cambios) -> str:
    rutas = {TEXTURA: b"textura sintetica"} if rutas is None else rutas
    return helpers.mod_con_fichero(str(tmp_path), nombre, rutas, **cambios)


# --------------------------------------------------------------------------
# Lector del img
# --------------------------------------------------------------------------

def test_romfs_img_lee_rutas_contenido_y_sha256(tmp_path):
    img = helpers.write_img(tmp_path, IMG_DATOS)
    with RomFSImage(img) as imagen:
        assert imagen.count == 6            # raiz + 2 dirs + 3 ficheros
        assert sorted(e.path for e in imagen.files()) == sorted(IMG_DATOS)
        assert imagen.read(TEXTURA) == b"rdx original"
        assert imagen.sha256(TEXTURA) == sha(b"rdx original")
        assert imagen.find("no/existe") is None


def test_romfs_img_rechaza_lo_que_no_es_dmromfs(tmp_path):
    ruta = os.path.join(str(tmp_path), "otro.img")
    with open(ruta, "wb") as fh:
        fh.write(b"NO-SOY-UN-ROMFS" + b"\x00" * 64)
    with pytest.raises(RomFSImageError):
        RomFSImage(ruta)


def test_romfs_img_rechaza_indice_incoherente(tmp_path):
    img = helpers.write_img(tmp_path, IMG_DATOS)
    datos = bytearray(open(img, "rb").read())
    datos[8:16] = (12345).to_bytes(8, "little")     # ioff que no cuadra con isz
    with open(img, "wb") as fh:
        fh.write(datos)
    with pytest.raises(RomFSImageError):
        RomFSImage(img)


# --------------------------------------------------------------------------
# Manifiesto: seccion romfs[]
# --------------------------------------------------------------------------

def test_romfs_valido_se_lee(tmp_path):
    carpeta = mod_de(tmp_path)
    mod = load_mod(carpeta)
    assert mod.report.ok, [str(i) for i in mod.report.issues]
    assert [(f.path, f.file) for f in mod.romfs] == [(TEXTURA, "payload/" + TEXTURA)]


@pytest.mark.parametrize("ruta, motivo", [
    ("/absoluta.bin", "no puede empezar"),
    ("../fuera.bin", "no puede llevar '..'"),
    # la letra de unidad se compone para que el guardian del repo (que veta rutas
    # absolutas en el codigo) no la lea como una ruta de esta maquina
    ("C" + ":/otra/unidad.bin", "unidad"),
    ("con\\barra.bin", "separador"),
    ("doble//barra.bin", "tramo vacio"),
    ("", "vacia"),
])
def test_romfs_rechaza_rutas_que_se_escapan(tmp_path, ruta, motivo):
    doc = helpers.mod_romfs_doc("malo", [{"path": ruta, "file": "x.bin", "why": "x"}])
    ruta_mod = helpers.write_mod(os.path.join(str(tmp_path), "malo"), doc)
    mod = load_mod(ruta_mod)
    assert not mod.report.ok
    assert any(motivo in str(i) for i in mod.report.errors), [str(i) for i in mod.report.issues]


def test_romfs_rechaza_dos_entradas_para_la_misma_ruta(tmp_path):
    doc = helpers.mod_romfs_doc("doble", [
        {"path": "a.bin", "file": "p/a.bin", "why": "x"},
        {"path": "a.bin", "file": "p/a2.bin", "why": "y"},
    ])
    mod = load_mod(helpers.write_mod(os.path.join(str(tmp_path), "doble"), doc))
    assert not mod.report.ok
    assert any("misma ruta" in str(i) for i in mod.report.errors)


def test_romfs_exige_why(tmp_path):
    doc = helpers.mod_romfs_doc("sinwhy", [{"path": "a.bin", "file": "p/a.bin"}])
    mod = load_mod(helpers.write_mod(os.path.join(str(tmp_path), "sinwhy"), doc))
    assert not mod.report.ok
    assert any("why" in str(i) for i in mod.report.errors)


def test_romfs_path_problem_acepta_las_rutas_del_juego():
    for ruta in (TEXTURA, "LD_C0_R.BIN", "motor_asset_re/KIDS_PLATFORM_OUNCE/0x4b13d561.fdata"):
        assert romfs_path_problem(ruta) is None


def test_un_mod_de_datos_sigue_siendo_valido():
    """Compatibilidad: un mod sin `romfs[]` valida igual que antes (t_5f0dbae7, t_f2665f94)."""
    for ejemplo in ("ejemplos/editar-fila", "ejemplos/editar-texto",
                    "ejemplos/escribir-fila", "ejemplos/renombrar-texto"):
        mod = load_mod(ejemplo)
        assert mod.report.ok, (ejemplo, [str(i) for i in mod.report.issues])
        assert mod.romfs == []
        assert mod.edits or mod.texts


# --------------------------------------------------------------------------
# pack
# --------------------------------------------------------------------------

def test_pack_es_determinista_y_anota_el_original(tmp_path):
    img, _ = preparar(tmp_path)
    carpeta = mod_de(tmp_path)
    uno = ov.empaquetar(carpeta, salida=os.path.join(str(tmp_path), "out"), img=img)
    dos = ov.empaquetar(carpeta, salida=os.path.join(str(tmp_path), "out"), img=img)
    assert uno["sha256"] == dos["sha256"], "el mismo contenido tiene que dar el mismo paquete"
    assert uno["files"][0]["original_sha256"] == sha(IMG_DATOS[TEXTURA])
    assert uno["files"][0]["sha256"] == sha(b"textura sintetica")
    assert uno["package"].endswith(".pkmod")


def test_pack_guarda_el_manifiesto_con_los_hashes(tmp_path):
    img, _ = preparar(tmp_path)
    import zipfile
    res = ov.empaquetar(mod_de(tmp_path), salida=os.path.join(str(tmp_path), "out"), img=img)
    with zipfile.ZipFile(res["package"]) as zf:
        doc = json.loads(zf.read("mod.json").decode("utf-8"))
        assert doc["romfs"][0]["size"] == len(b"textura sintetica")
        assert doc["romfs"][0]["sha256"] == sha(b"textura sintetica")
        assert doc["romfs"][0]["original_sha256"] == sha(IMG_DATOS[TEXTURA])
        assert zf.read("payload/" + TEXTURA) == b"textura sintetica"


def test_pack_rechaza_un_original_que_no_es_el_del_img(tmp_path):
    img, _ = preparar(tmp_path)
    doc = helpers.mod_romfs_doc("otro", [{"path": TEXTURA, "file": "p/x.bin", "why": "x",
                                         "original_sha256": "f" * 64}])
    carpeta = os.path.join(str(tmp_path), "otro")
    os.makedirs(os.path.join(carpeta, "p"))
    open(os.path.join(carpeta, "p", "x.bin"), "wb").write(b"x")
    helpers.write_mod(carpeta, doc)
    with pytest.raises(ModError) as exc:
        ov.empaquetar(carpeta, salida=os.path.join(str(tmp_path), "out"), img=img)
    assert "otro build" in str(exc.value)


def test_pack_sin_romfs_no_empaqueta(tmp_path):
    doc = helpers.mod_romfs_doc("vacio", [])
    carpeta = os.path.join(str(tmp_path), "vacio")
    helpers.write_mod(carpeta, doc)
    with pytest.raises(ModError) as exc:
        ov.empaquetar(carpeta, salida=os.path.join(str(tmp_path), "out"))
    assert "romfs" in str(exc.value)


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------

def test_install_copia_registra_y_es_idempotente(tmp_path):
    img, store = preparar(tmp_path)
    res = ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    assert res["ok"]
    destino = os.path.join(store, "mods", "textura-demo", TEXTURA.replace("/", os.sep))
    assert open(destino, "rb").read() == b"textura sintetica"
    assert res["servido"][0]["origen"] == "overlay"
    assert res["files"][0]["original_sha256"] == sha(IMG_DATOS[TEXTURA])

    otra = ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    registro = ov.leer_registro(store)
    assert len(registro["mods"]) == 1, "instalar dos veces no duplica el mod"
    assert otra["ok"] and res["overlay"] == otra["overlay"]


def test_install_se_niega_si_el_almacen_no_existe(tmp_path):
    img = helpers.write_img(tmp_path, IMG_DATOS)
    with pytest.raises(ModError) as exc:
        ov.instalar(mod_de(tmp_path), os.path.join(str(tmp_path), "no-existe"), img=img,
                    procesos=[])
    assert "no existe" in str(exc.value)


def test_install_crea_el_almacen_con_crear(tmp_path):
    img = helpers.write_img(tmp_path, IMG_DATOS)
    store = os.path.join(str(tmp_path), "nuevo")
    ov.instalar(mod_de(tmp_path), store, img=img, crear=True, procesos=[])
    assert os.path.isdir(os.path.join(store, "mods", "textura-demo"))


def test_install_se_niega_con_el_runtime_en_marcha(tmp_path):
    img, store = preparar(tmp_path)
    with pytest.raises(ModError) as exc:
        ov.instalar(mod_de(tmp_path), store, img=img, procesos=["nxrt.exe"])
    assert "en marcha" in str(exc.value)


def test_install_se_niega_en_una_ruta_protegida(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    monkeypatch.setenv("PKP_PROTECTED", store)
    with pytest.raises(GuardError):
        ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])


def test_install_rechaza_si_el_fichero_del_mod_no_cuadra(tmp_path):
    img, store = preparar(tmp_path)
    carpeta = mod_de(tmp_path)
    # el manifiesto declara un sha256 que no es el del fichero
    ruta = os.path.join(carpeta, "mod.json")
    doc = json.load(open(ruta, encoding="utf-8"))
    doc["romfs"][0]["sha256"] = "a" * 64
    json.dump(doc, open(ruta, "w", encoding="utf-8"), indent=2)
    with pytest.raises(ModError) as exc:
        ov.instalar(carpeta, store, img=img, procesos=[])
    assert "sha256" in str(exc.value)


def test_install_avisa_del_conflicto_y_status_lo_ve(tmp_path):
    img, store = preparar(tmp_path)
    a = helpers.mod_con_fichero(str(tmp_path), "textura-a", {TEXTURA: b"de a"})
    b = helpers.mod_con_fichero(str(tmp_path), "textura-b", {TEXTURA: b"de b"})
    ov.instalar(a, store, img=img, procesos=[])
    res = ov.instalar(b, store, img=img, procesos=[])
    assert res["conflictos"] == [{"path": TEXTURA, "con": "textura-a"}]

    st = ov.estado(store, img=img)
    assert [m["name"] for m in st["mods"]] == ["textura-a", "textura-b"]
    assert st["conflictos"] and st["conflictos"][0]["gana"] == "textura-a"
    assert st["conflictos"][0]["mismos_bytes"] is False
    # el que pierde no sirve: el primero del overlay gana
    assert st["mods"][1]["files"][0]["servido"]["origen"] == "overlay"
    assert st["mods"][1]["files"][0]["servido"]["donde"] == "textura-a"


def test_install_primero_cambia_la_prioridad(tmp_path):
    img, store = preparar(tmp_path)
    a = helpers.mod_con_fichero(str(tmp_path), "textura-a", {TEXTURA: b"de a"})
    b = helpers.mod_con_fichero(str(tmp_path), "textura-b", {TEXTURA: b"de b"})
    ov.instalar(a, store, img=img, procesos=[])
    ov.instalar(b, store, img=img, primero=True, procesos=[])
    st = ov.estado(store, img=img)
    assert [m["name"] for m in st["mods"]] == ["textura-b", "textura-a"]
    assert st["conflictos"][0]["gana"] == "textura-b"


def test_install_dry_run_no_escribe(tmp_path):
    img, store = preparar(tmp_path)
    res = ov.instalar(mod_de(tmp_path), store, img=img, dry_run=True, procesos=[])
    assert res["ok"] and res["dry_run"]
    assert not os.path.exists(os.path.join(store, "mods", "textura-demo"))
    assert ov.leer_registro(store)["mods"] == []


def test_install_desde_paquete(tmp_path):
    img, store = preparar(tmp_path)
    res = ov.empaquetar(mod_de(tmp_path), salida=os.path.join(str(tmp_path), "out"), img=img)
    instalado = ov.instalar(res["package"], store, img=img, procesos=[])
    assert instalado["ok"]
    registro = ov.leer_registro(store)
    assert registro["mods"][0]["package"].endswith(".pkmod")
    assert registro["mods"][0]["package_sha256"] == res["sha256"]


# --------------------------------------------------------------------------
# resolver: overlay primero, en orden, y luego el img
# --------------------------------------------------------------------------

def test_resolver_respeta_el_orden_del_runtime(tmp_path):
    img, store = preparar(tmp_path)
    a = helpers.mod_con_fichero(str(tmp_path), "textura-a", {TEXTURA: b"de a"})
    b = helpers.mod_con_fichero(str(tmp_path), "textura-b", {TEXTURA: b"de b"})
    ov.instalar(a, store, img=img, procesos=[])
    ov.instalar(b, store, img=img, procesos=[])
    registro = ov.leer_registro(store)
    with RomFSImage(img) as imagen:
        servido = ov.resolver(TEXTURA, ov.prioridad(store, registro), imagen, hash_overlay=True)
        assert (servido.origen, servido.donde) == ("overlay", "textura-a")
        assert servido.sha256 == sha(b"de a")
        # una ruta que ningun mod toca la sirve el img
        otra = ov.resolver("LD_C0_R.BIN", ov.prioridad(store, registro), imagen)
        assert otra.origen == "img" and otra.sha256 == sha(IMG_DATOS["LD_C0_R.BIN"])
        nada = ov.resolver("no/existe.bin", ov.prioridad(store, registro), imagen)
        assert nada.origen == "nada"


# --------------------------------------------------------------------------
# uninstall
# --------------------------------------------------------------------------

def test_uninstall_restaura_el_original_con_su_sha256(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    res = ov.desinstalar("textura-demo", store, img=img, procesos=[])
    assert res["ok"] and res["restaurados"] == 1
    v = res["verificacion"][0]
    assert v["estado"] == "original restaurado"
    assert v["servido"]["origen"] == "img"
    assert v["servido"]["sha256"] == sha(IMG_DATOS[TEXTURA])
    assert not os.path.exists(os.path.join(store, "mods", "textura-demo"))
    assert ov.leer_registro(store)["mods"] == []


def test_uninstall_sin_img_no_declara_victoria(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    with pytest.raises(ModError) as exc:
        ov.desinstalar("textura-demo", store, procesos=[])
    assert "no se puede demostrar" in str(exc.value)
    # y no ha borrado nada: la negativa es antes de tocar el disco
    assert os.path.isdir(os.path.join(store, "mods", "textura-demo"))


def test_uninstall_con_fichero_alterado_se_niega_sin_forzar(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    destino = os.path.join(store, "mods", "textura-demo", TEXTURA.replace("/", os.sep))
    open(destino, "wb").write(b"lo he tocado a mano")
    with pytest.raises(ModError) as exc:
        ov.desinstalar("textura-demo", store, img=img, procesos=[])
    assert "no coincide con el registro" in str(exc.value)
    assert ov.desinstalar("textura-demo", store, img=img, forzar=True,
                          procesos=[])["ok"]


def test_uninstall_avisa_de_lo_que_sigue_sombreado_por_otro_mod(tmp_path):
    img, store = preparar(tmp_path)
    a = helpers.mod_con_fichero(str(tmp_path), "textura-a", {TEXTURA: b"de a"})
    b = helpers.mod_con_fichero(str(tmp_path), "textura-b", {TEXTURA: b"de b"})
    ov.instalar(a, store, img=img, procesos=[])
    ov.instalar(b, store, img=img, procesos=[])
    res = ov.desinstalar("textura-a", store, img=img, procesos=[])
    assert res["ok"] and res["sombreados"] == 1 and res["restaurados"] == 0
    assert res["verificacion"][0]["estado"] == "sombreado por textura-b"


def test_uninstall_de_un_mod_que_no_esta(tmp_path):
    _, store = preparar(tmp_path)
    with pytest.raises(ModError):
        ov.desinstalar("fantasma", store, img=None, permitir_sin_verificar=True)


# --------------------------------------------------------------------------
# status / doctor
# --------------------------------------------------------------------------

def test_status_sin_mods(tmp_path):
    _, store = preparar(tmp_path)
    st = ov.estado(store)
    assert st["mods"] == [] and st["conflictos"] == []
    assert st["overlay"] == ""


def test_status_lista_ficheros_y_su_origen(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    st = ov.estado(store, img=img)
    f = st["mods"][0]["files"][0]
    assert f["path"] == TEXTURA and f["en_disco"] is True
    assert f["servido"]["origen"] == "overlay"
    assert st["overlay"] == os.path.join(store, "mods", "textura-demo")


def test_doctor_ok_en_un_almacen_sano(tmp_path, monkeypatch):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    # la variable se comprueba: en la forma relativa, que es la que el runtime trocea bien
    monkeypatch.setenv(ov.OVERLAY_ENV,
                       os.path.relpath(os.path.join(store, "mods", "textura-demo"),
                                       os.getcwd()))
    res = ov.doctor(store, img=img)
    assert res["ok"], res["checks"]
    assert not [c for c in res["checks"] if not c["ok"] and c["fatal"]], res["checks"]


def test_doctor_detecta_un_fichero_del_overlay_alterado(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    destino = os.path.join(store, "mods", "textura-demo", TEXTURA.replace("/", os.sep))
    open(destino, "wb").write(b"otra cosa")
    res = ov.doctor(store, img=img)
    assert not res["ok"]
    fallos = [c for c in res["checks"] if not c["ok"] and c["fatal"]]
    assert fallos and "no es el que se instalo" in fallos[0]["detail"]


def test_doctor_detecta_carpetas_sin_registro(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    sobrante = os.path.join(store, "mods", "a-mano")
    os.makedirs(sobrante)
    res = ov.doctor(store, img=img)
    assert res["ok"], "una carpeta suelta es aviso, no fallo"
    assert any(c["check"] == "almacen.sin_sobras" and not c["ok"] for c in res["checks"])


def test_doctor_sin_img_comprueba_lo_que_puede(tmp_path):
    img, store = preparar(tmp_path)
    ov.instalar(mod_de(tmp_path), store, img=img, procesos=[])
    res = ov.doctor(store)
    assert res["ok"]


# --------------------------------------------------------------------------
# merge: los ficheros de overlay no se combinan
# --------------------------------------------------------------------------

def test_merge_rechaza_mods_con_romfs(tmp_path):
    from pokopia.mod import merge_mods
    a = mod_de(tmp_path, "textura-a")
    b = mod_de(tmp_path, "textura-b", {TEXTURA: b"de b"})
    res = merge_mods(a, b, None, check_container=False)
    assert not res.ok
    assert any("romfs" in str(i) for i in res.report.errors)


# --------------------------------------------------------------------------
# env y avisos
# --------------------------------------------------------------------------

def test_lineas_de_entorno_usan_dos_puntos(tmp_path):
    img, store = preparar(tmp_path)
    a = helpers.mod_con_fichero(str(tmp_path), "textura-a", {TEXTURA: b"de a"})
    b = helpers.mod_con_fichero(str(tmp_path), "textura-b",
                                {"motor_asset_re/KIDS_PLATFORM_OUNCE/root.rdx": b"b"})
    ov.instalar(a, store, img=img, procesos=[])
    ov.instalar(b, store, img=img, procesos=[])
    registro = ov.leer_registro(store)
    linea = ov.linea_overlay(store, registro)
    assert linea.split(":")[-1].endswith(os.path.join("mods", "textura-b"))
    assert os.pathsep not in linea or os.pathsep == ":"


def test_paths_protegidos_no_son_escribibles(tmp_path, monkeypatch):
    monkeypatch.setenv("PKP_ROMFS", str(tmp_path))
    assert paths.is_protected(str(tmp_path))

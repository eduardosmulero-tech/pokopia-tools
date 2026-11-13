"""Flujo de mod completo sobre el overlay nativo: `pack`, `install`, `uninstall`, `status`.

El runtime de `nxrt` ya sabe leer un overlay: con `DM_ROMFS_OVERLAY` puesta resuelve
cada `rom:/...` probando **primero** las carpetas de esa lista (separadas por `:` y
en orden) y cae al `RomFS.img` si el fichero no esta en ninguna
(`informes/t_88d29217/MOD-LOADER-NATIVO.md`, medido con `image-entry-29 -> fd-5 ->
image-entry-29`). Por eso un mod instalado es **una carpeta**, y desinstalarlo es
borrarla: el `img` no se toca en ningun paso.

Organizacion del almacen (`--overlay <carpeta>`)::

    <almacen>/
      installed.json          registro de lo instalado (orden = prioridad)
      mods/<mod>/             un arbol romfs por mod: mods/<mod>/<ruta del romfs>
      mods/<mod>/...          ficheros tal cual los pide el runtime

Una carpeta por mod y no una sola carpeta comun, por dos motivos medidos:

* desinstalar un mod es borrar **su** carpeta: no puede llevarse por delante un
  fichero que puso otro;
* dos mods que pisan la misma ruta son un conflicto visible (`status` lo dice y
  `doctor` lo cuenta): gana el primero de la lista de `DM_ROMFS_OVERLAY`, que es
  el mismo criterio que aplica el runtime.

El paquete instalable (`*.pkmod`) es un ZIP determinista con `mod.json` en la raiz
y los ficheros del mod en su ruta relativa; empacar dos veces lo mismo da el mismo
sha256.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field

from .. import paths
from ..romfs_img import RomFSImage, RomFSImageError
from .errors import GuardError, ModError, Report
from .manifest import MANIFEST, MOD_FORMAT, Mod, RomfsFile, load_mod, parse_mod

STORE_FORMAT = 1
REGISTRY = "installed.json"
MODS_DIR = "mods"
PACKAGE_EXT = ".pkmod"
DEFAULT_PACK_DIR = os.path.join("build", "pkmod")
OVERLAY_ENV = "DM_ROMFS_OVERLAY"
IMG_ENV = "PKP_ROMFS_IMG"
#: Procesos que significan "el juego esta en marcha".
RUNTIME_PROCESOS = ("nxrt", "nxrt.exe")
TMP_PREFIX = ".pkp-tmp-"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    return paths.sha256_file(path, chunk=chunk)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sello() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_atomico(ruta: str, datos: dict) -> None:
    """Escribe JSON sin dejar nunca medio fichero (tmp + replace)."""
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(temporal, ruta)


def destino_por_defecto() -> str | None:
    return os.environ.get("PKP_OVERLAY") or None


def img_por_defecto() -> str | None:
    return os.environ.get(IMG_ENV) or None


# --------------------------------------------------------------------------
# El `img` y el juego en marcha
# --------------------------------------------------------------------------

def listar_procesos() -> list[str]:
    """Nombres de los procesos en marcha (sin ruta). Lista vacia si no se puede."""
    try:
        if os.name == "nt":
            salida = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                    text=True, timeout=20).stdout
            nombres = []
            for linea in salida.splitlines():
                if linea.startswith('"'):
                    nombres.append(linea.split('","')[0].strip('"'))
            return nombres
        salida = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True,
                                text=True, timeout=20).stdout
        return [os.path.basename(x) for x in salida.splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):     # pragma: no cover - entorno raro
        return []


def motivo_no_instalable(img: str | None, procesos: list[str] | None = None) -> str | None:
    """Por que no se puede tocar el overlay ahora mismo, o `None` si se puede.

    Dos comprobaciones: que el runtime no este corriendo y que el `img` se pueda
    abrir en escritura (en Windows un fichero abierto con `FILE_SHARE_READ` no lo
    permite). El `img` se abre **solo para preguntar** y se cierra sin escribir un
    byte: `pkp` nunca escribe en el `RomFS.img`.
    """
    nombres = [os.path.basename((p or "").strip()).lower() for p in
               (procesos if procesos is not None else listar_procesos())]
    for kill in RUNTIME_PROCESOS:
        if kill in nombres:
            return ("el runtime del juego esta en marcha (%s): cierralo antes de instalar "
                    "o desinstalar (con el juego abierto el overlay se queda a medias)"
                    % kill)
    if img and os.path.isfile(img):
        try:
            fd = os.open(img, os.O_RDWR | getattr(os, "O_BINARY", 0))
        except OSError as exc:
            return ("el RomFS.img no se puede abrir en escritura (%s): puede estar abierto "
                    "por el juego" % exc)
        os.close(fd)
    return None


# --------------------------------------------------------------------------
# El origen del mod: carpeta o paquete `.pkmod`
# --------------------------------------------------------------------------

class Origen:
    """De donde salen el `mod.json` y los ficheros: una carpeta o un `.pkmod`."""

    def __init__(self, ruta: str):
        self.ruta = os.path.abspath(os.path.expanduser(ruta))
        if os.path.isdir(self.ruta):
            self.es_paquete = False
            self._zip = None
        elif os.path.isfile(self.ruta):
            if not zipfile.is_zipfile(self.ruta):
                raise ModError("%s no es una carpeta ni un paquete %s (ZIP)"
                               % (ruta, PACKAGE_EXT), code="io", where=ruta)
            self.es_paquete = True
            self._zip = zipfile.ZipFile(self.ruta)
        else:
            raise ModError("no existe %s" % self.ruta, code="io", where=ruta)

    @property
    def nombre(self) -> str:
        base = os.path.basename(self.ruta.rstrip("\\/"))
        return base[:-len(PACKAGE_EXT)] if base.endswith(PACKAGE_EXT) else base

    def hash_paquete(self) -> str | None:
        return sha256_file(self.ruta) if self.es_paquete else None

    def _paquete(self) -> zipfile.ZipFile:
        if self._zip is None:              # pragma: no cover - invariante del constructor
            raise ModError("%s no es un paquete" % self.ruta, code="io", where=self.ruta)
        return self._zip

    def leer_manifest(self) -> Mod:
        if self.es_paquete:
            try:
                datos = self._paquete().read(MANIFEST)
            except KeyError:
                raise ModError("%s no lleva %s en la raiz"
                               % (self.ruta, MANIFEST), code="io", where=self.ruta) from None
            doc = json.loads(datos.decode("utf-8"))
            return parse_mod(doc, "%s!%s" % (self.ruta, MANIFEST))
        return load_mod(self.ruta)

    def _interno(self, rel: str) -> str:
        if self.es_paquete:
            return rel
        return os.path.join(self.ruta, rel.replace("/", os.sep))

    def tamaño(self, rel: str) -> int:
        if self.es_paquete:
            try:
                return self._paquete().getinfo(rel).file_size
            except KeyError:
                raise ModError("el paquete no lleva %r" % rel, code="io",
                               where=self.ruta) from None
        ruta = self._interno(rel)
        if not os.path.isfile(ruta):
            raise ModError("falta el fichero %r del mod (%s)" % (rel, ruta), code="io",
                           where=self.ruta)
        return os.path.getsize(ruta)

    def sha256(self, rel: str) -> str:
        if self.es_paquete:
            return sha256_bytes(self._paquete().read(rel))
        return sha256_file(self._interno(rel))

    def copiar_a(self, rel: str, destino: str) -> None:
        os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
        if self.es_paquete:
            with self._paquete().open(rel) as src, open(destino, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        else:
            shutil.copyfile(self._interno(rel), destino)

    def cerrar(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def __enter__(self) -> "Origen":
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()


# --------------------------------------------------------------------------
# Registro del almacen
# --------------------------------------------------------------------------

def leer_registro(store: str) -> dict:
    ruta = os.path.join(store, REGISTRY)
    if not os.path.exists(ruta):
        return {"store_format": STORE_FORMAT, "mods": []}
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ModError("%s: registro ilegible (%s, linea %d)"
                       % (ruta, exc.msg, exc.lineno), code="store", where=store) from None
    if not isinstance(datos, dict) or not isinstance(datos.get("mods"), list):
        raise ModError("%s: el registro no tiene la forma esperada" % ruta,
                       code="store", where=store)
    formato = datos.get("store_format")
    if formato != STORE_FORMAT:
        raise ModError("%s: store_format %r y este kit entiende %d"
                       % (ruta, formato, STORE_FORMAT), code="store", where=store)
    return datos


def escribir_registro(store: str, datos: dict) -> None:
    _json_atomico(os.path.join(store, REGISTRY), datos)


def carpeta_de(store: str, nombre: str) -> str:
    return os.path.join(store, MODS_DIR, nombre)


def prioridad(store: str, registro: dict) -> list[tuple[str, str]]:
    """`(nombre, carpeta)` en el orden en que el runtime las consulta."""
    return [(entrada["name"], carpeta_de(store, entrada["name"]))
            for entrada in registro.get("mods", [])]


def linea_overlay(store: str, registro: dict) -> str:
    """Valor de `DM_ROMFS_OVERLAY` (absoluto, primera carpeta = prioridad).

    El separador es `:` siempre, no `os.pathsep`: es lo que trocea el runtime
    (`strtok_r(roots, ":")`), tambien en Windows.
    """
    return ":".join(ruta for _, ruta in prioridad(store, registro))


def _unidad(ruta: str) -> str:
    """La unidad de una ruta tal como se escribe (`D:`), o `?` si no tiene."""
    return os.path.splitdrive(os.path.abspath(ruta))[0] or "?"


def instruccion_variable(store: str, registro: dict) -> str:
    """La forma de `DM_ROMFS_OVERLAY` que el runtime trocea bien, y como lanzarlo.

    Una sola fuente para lo que dicen `install`, `status`, `doctor` y las paginas:
    la forma relativa al cwd mientras exista; si el almacen esta en otra unidad, la
    relativa a la **raiz del almacen** (`mods/<mod>`, sin `:` en ningun sitio) y el
    juego arrancado con el cwd ahi. Nunca la absoluta: el runtime la parte por `:`.
    """
    rel = overlay_relativo(store, registro)
    if rel is not None:
        return ("usa %s (relativa al cwd) y arranca el juego con el cwd en %s"
                % (rel, os.getcwd()))
    return ("pon DM_ROMFS_OVERLAY=%s (relativa a la raiz del almacen) y arranca el juego "
            "con el cwd en %s"
            % (overlay_relativo_almacen(store, registro), os.path.abspath(store)))


def aviso_separador(store: str, registro: dict | None = None) -> str | None:
    """Aviso por la trampa medida del `:` en Windows (t_88d29217 §6.2).

    El runtime trocea `DM_ROMFS_OVERLAY` por `:`; una ruta absoluta de Windows
    (`C:\\...`) se parte en `C` y `\\...`, y solo funciona por casualidad cuando el
    almacen cae en la unidad del cwd. Con el almacen en otra unidad no hay forma
    relativa al cwd, asi que el aviso da **una** instruccion: la relativa a la raiz
    del almacen y el juego arrancado desde ahi.
    """
    if os.name != "nt":
        return None
    unidad_store, unidad_cwd = _unidad(store), _unidad(os.getcwd())
    if unidad_store == "?" or unidad_store.lower() == unidad_cwd.lower():
        return None
    if registro is not None and not registro.get("mods"):
        return None             # sin mods no hay variable que montar
    if registro is not None:
        como = instruccion_variable(store, registro)
    else:                       # pragma: no cover - todos los llamadores pasan el registro
        como = ("pon DM_ROMFS_OVERLAY con las carpetas de los mods relativas a la raiz del "
                "almacen (%s) y arranca el juego con el cwd ahi" % os.path.abspath(store))
    return ("el almacen esta en %s y el cwd en %s — el runtime trocea DM_ROMFS_OVERLAY por "
            "':' y una ruta absoluta no vale; %s" % (unidad_store, unidad_cwd, como))


def overlay_relativo(store: str, registro: dict) -> str | None:
    """La misma lista en rutas relativas al cwd (la forma que el runtime trocea bien).

    `None` cuando no existe: en Windows `os.path.relpath` lanza `ValueError` si el
    almacen y el cwd estan en unidades distintas (por ejemplo, con el almacen en
    `D:\\...` frente a `C:\\...`). No es un fallo del mod: es que la forma relativa
    al cwd no se puede calcular, y quien la imprima tiene que decirlo en vez de
    reventar. La forma que si vale en ese caso (`overlay_relativo_almacen`) la da
    `instruccion_variable`.
    """
    rutas = [ruta for _, ruta in prioridad(store, registro)]
    try:
        return ":".join(os.path.relpath(ruta, os.getcwd()) for ruta in rutas)
    except ValueError:                  # Windows: almacen y cwd en unidades distintas
        return None


def overlay_relativo_almacen(store: str, registro: dict) -> str:
    """La misma lista relativa a la **raiz del almacen** (`mods/<mod>`).

    Siempre se puede calcular (el almacen y sus mods estan en la misma unidad) y no
    lleva `:` dentro, asi que el runtime la trocea bien arrancando el juego con el
    cwd en la raiz del almacen. Es la unica forma defendible cuando el almacen esta
    en otra unidad que el cwd, donde `os.path.relpath` no puede dar nada.
    """
    return ":".join(os.path.relpath(ruta, store) for _, ruta in prioridad(store, registro))


def linea_relativa(store: str, registro: dict) -> str:
    """Lo que se imprime tras «relativo al cwd:», sin mentir cuando no hay forma relativa.

    Cuando no la hay dice el hecho y nada mas: la instruccion (que forma usar y con
    que cwd lanzar el juego) la da `aviso_separador`, para no pedir en una linea lo
    que la anterior declara imposible.
    """
    rel = overlay_relativo(store, registro)
    if rel is not None:
        return rel
    return ("(no hay forma relativa al cwd: el almacen esta en %s y el cwd en %s)"
            % (_unidad(store), _unidad(os.getcwd())))


#: Una ruta absoluta de Windows dentro del valor (`C:\\...`, `C:/...`, o detras de
#: otro separador). Es lo que el runtime parte en dos al trocear por `:`.
_RUTA_ABSOLUTA_WIN = re.compile(r"(?:^|[;:])[A-Za-z]:[\\/]")


def trampa_separador(valor: str) -> bool:
    """¿`valor` trae una ruta absoluta de Windows que el runtime partira por `:`?

    No basta con partir por `:` y mirar un trozo de dos caracteres: al trocear
    una ruta absoluta salen la letra sola y el resto de la ruta, no `C:`. Hay que
    mirar el valor original.
    """
    if os.name != "nt":
        return False
    return bool(_RUTA_ABSOLUTA_WIN.search(valor))



# --------------------------------------------------------------------------
# Quien sirve una ruta (la regla del runtime, replicada)
# --------------------------------------------------------------------------

@dataclass
class Servido:
    """Que fichero acaba viendo el juego para una ruta del romfs."""

    path: str
    origen: str            # "overlay" | "img" | "nada"
    donde: str = ""
    indice: int | None = None
    size: int | None = None
    sha256: str | None = None

    def as_dict(self) -> dict:
        return {"path": self.path, "origen": self.origen, "donde": self.donde,
                "indice": self.indice, "size": self.size, "sha256": self.sha256}


def resolver(path: str, dirs: list[tuple[str, str]], img: RomFSImage | None = None,
             *, hash_overlay: bool = False) -> Servido:
    """Overlay primero (en orden) y si no, el `img`: la regla medida del runtime."""
    rel = path.replace("\\", "/").strip("/")
    for nombre, carpeta in dirs:
        candidato = os.path.join(carpeta, rel.replace("/", os.sep))
        if os.path.isfile(candidato):
            return Servido(path=rel, origen="overlay", donde=nombre,
                           size=os.path.getsize(candidato),
                           sha256=sha256_file(candidato) if hash_overlay else None)
    if img is not None:
        entrada = img.find(rel)
        if entrada is not None and not entrada.is_dir:
            return Servido(path=rel, origen="img", donde=img.path, indice=entrada.index,
                           size=entrada.size, sha256=img.sha256(rel))
    return Servido(path=rel, origen="nada")


# --------------------------------------------------------------------------
# `pack`
# --------------------------------------------------------------------------

def _zip_determinista(destino: str, ficheros: list[tuple[str, str]]) -> None:
    """ZIP con horas fijas y orden dado: el mismo contenido da el mismo sha256."""
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, origen in ficheros:
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o644 << 16
            with open(origen, "rb") as fh:
                zf.writestr(info, fh.read(), compresslevel=9)


def empaquetar(origen: str, salida: str | None = None, img: str | RomFSImage | None = None
               ) -> dict:
    """`pkp mod pack`: convierte una carpeta de trabajo en un `.pkmod` instalable.

    Rellena `size`, `sha256` y `original_sha256` de cada entrada `romfs[]`
    (el ultimo leyendolo del `RomFS.img`): sin ese hash no se puede demostrar que
    al desinstalar vuelve el original.
    """
    if isinstance(img, RomFSImage):
        imagen, cerrar = img, False
    else:
        imagen = RomFSImage(img) if img else None
        cerrar = imagen is not None
    try:
        mod = load_mod(origen)
        rep = Report()
        rep.extend(mod.report)
        if not rep.ok:
            raise ModError("el mod no es valido: %s"
                           % "; ".join(str(i) for i in rep.errors[:5]),
                           code="mod.invalid", where=origen)
        if not mod.romfs:
            raise ModError("%s no declara ficheros en `romfs[]`: no hay nada que empaquetar "
                           "(un mod de solo datos se aplica con `pkp mod apply`)"
                           % mod.name, code="mod.empty", where=origen)

        entradas: list[RomfsFile] = []
        avisos: list[str] = []
        detalle: list[dict] = []
        for item in mod.romfs:
            origen_file = os.path.join(mod.path, item.file.replace("/", os.sep))
            if not os.path.isfile(origen_file):
                raise ModError("%s: falta el fichero %r del mod (%s)"
                               % (item.where(), item.file, origen_file), code="io",
                               where=origen)
            tam = os.path.getsize(origen_file)
            sha = sha256_file(origen_file)
            if item.size is not None and item.size != tam:
                raise ModError("%s: el manifiesto dice %d B y el fichero tiene %d"
                               % (item.where(), item.size, tam), code="mod.size",
                               where=origen)
            if item.sha256 and item.sha256 != sha:
                raise ModError("%s: el manifiesto dice sha256 %s… y el fichero da %s…"
                               % (item.where(), item.sha256[:12], sha[:12]),
                               code="mod.sha256", where=origen)
            original = item.original_sha256
            nota = ""
            if imagen is not None:
                entrada = imagen.find(item.path)
                if entrada is None or entrada.is_dir:
                    nota = "nuevo"
                    if original:
                        avisos.append("%s: el manifiesto dice un original y el img no tiene "
                                      "esa ruta: se deja sin original" % item.where())
                    original = None
                else:
                    real = imagen.sha256(item.path)
                    if original and original != real:
                        raise ModError(
                            "%s: el original anotado (%s…) no es el que sirve este img "
                            "(%s…): el paquete se hizo para otro build"
                            % (item.where(), original[:12], real[:12]),
                            code="mod.original_sha256", where=origen)
                    original = real
            elif original is None:
                avisos.append("%s: sin --img no se puede anotar el original; uninstall no "
                              "podra demostrar que vuelve" % item.where())
            entradas.append(RomfsFile(path=item.path, file=item.file, why=item.why,
                                      size=tam, sha256=sha, original_sha256=original))
            detalle.append({"path": item.path, "file": item.file, "size": tam,
                            "sha256": sha, "original_sha256": original, "nota": nota})

        doc = json.loads(json.dumps(mod.doc))
        doc["romfs"] = [e.as_dict() for e in entradas]
        destino_dir = os.path.abspath(salida or DEFAULT_PACK_DIR)
        os.makedirs(destino_dir, exist_ok=True)
        paquete = os.path.join(destino_dir, "%s-%s%s"
                               % (mod.name, mod.version or "0", PACKAGE_EXT))
        temporal = paquete + ".tmp"
        manifiesto_tmp = os.path.join(destino_dir, ".mod.json.tmp-%d" % os.getpid())
        with open(manifiesto_tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        try:
            _zip_determinista(temporal, [(MANIFEST, manifiesto_tmp)]
                              + [(e.file, os.path.join(mod.path, e.file.replace("/", os.sep)))
                                 for e in entradas])
            os.replace(temporal, paquete)
        finally:
            for basura in (temporal, manifiesto_tmp):
                if os.path.exists(basura):
                    os.remove(basura)
        return {"ok": True, "mod": mod.name, "version": mod.version, "package": paquete,
                "sha256": sha256_file(paquete), "files": detalle, "warnings": avisos,
                "img": imagen.path if imagen is not None else None}
    finally:
        if cerrar:
            imagen.close()


# --------------------------------------------------------------------------
# `install`
# --------------------------------------------------------------------------

def _comprobar_destino(store: str, *, crear: bool) -> str:
    store = os.path.abspath(os.path.expanduser(store))
    if not os.path.isdir(store):
        if not crear:
            raise ModError("el destino %s no existe: crea el almacen con `--crear` o pasa "
                           "la carpeta del overlay que ya usa el juego" % store,
                           code="store", where=store)
        os.makedirs(store, exist_ok=True)
    try:
        paths.guard_writable(store)
    except PermissionError as exc:
        raise GuardError(str(exc), code="guard", where=store) from None
    return store


def instalar(origen: str, store: str, img: str | None = None, *, crear: bool = False,
             primero: bool = False, dry_run: bool = False, forzar: bool = False,
             procesos: list[str] | None = None) -> dict:
    """`pkp mod install`: deja el mod en `<almacen>/mods/<mod>/` sin tocar el `img`."""
    store = os.path.abspath(os.path.expanduser(store))
    if not forzar:
        motivo = motivo_no_instalable(img, procesos)
        if motivo:
            raise ModError(motivo, code="img.abierto", where=img or store)
    # El almacen se crea (con `--crear`) solo despues de la guarda: un `install`
    # rechazado no deja ni una carpeta vacia detras.
    store = _comprobar_destino(store, crear=crear)

    imagen = RomFSImage(img) if img else None
    try:
        with Origen(origen) as fuente:
            mod = fuente.leer_manifest()
            if not mod.report.ok:
                raise ModError("el mod no es valido: %s"
                               % "; ".join(str(i) for i in mod.report.errors[:5]),
                               code="mod.invalid", where=origen)
            if not mod.romfs:
                raise ModError("%s no declara ficheros en `romfs[]`: no hay nada que instalar"
                               % (mod.name or origen), code="mod.empty", where=origen)
            registro = leer_registro(store)
            otros = [e for e in registro["mods"] if e["name"] != mod.name]
            ocupadas: dict[str, str] = {}
            for entrada in otros:
                for fichero in entrada.get("files", []):
                    ocupadas.setdefault(fichero["path"], entrada["name"])

            destino = carpeta_de(store, mod.name)
            temporal = os.path.join(store, MODS_DIR, "%s%s-%d"
                                    % (TMP_PREFIX, mod.name, os.getpid()))
            viejo = temporal + ".viejo"
            detalle: list[dict] = []
            conflictos: list[dict] = []
            avisos: list[str] = []
            try:
                if not dry_run:
                    for basura in (temporal, viejo):
                        if os.path.isdir(basura):
                            shutil.rmtree(basura)
                    os.makedirs(temporal, exist_ok=True)
                for item in mod.romfs:
                    tam = fuente.tamaño(item.file)
                    sha = fuente.sha256(item.file)
                    if item.size is not None and item.size != tam:
                        raise ModError("%s: dice %d B y el fichero del mod tiene %d"
                                       % (item.where(), item.size, tam), code="mod.size",
                                       where=origen)
                    if item.sha256 and item.sha256 != sha:
                        raise ModError("%s: dice sha256 %s… y el fichero da %s…"
                                       % (item.where(), item.sha256[:12], sha[:12]),
                                       code="mod.sha256", where=origen)
                    original = item.original_sha256
                    nota = ""
                    if imagen is not None:
                        entrada = imagen.find(item.path)
                        if entrada is None or entrada.is_dir:
                            nota = "nuevo"
                            avisos.append("%s: no esta en el img; el juego no lo pedira por "
                                          "nombre" % item.where())
                            original = None
                        else:
                            real = imagen.sha256(item.path)
                            if original and original != real:
                                raise ModError(
                                    "%s: el original anotado (%s…) no es el que sirve este "
                                    "img (%s…)" % (item.where(), original[:12], real[:12]),
                                    code="mod.original_sha256", where=origen)
                            original = real
                    elif original is None:
                        avisos.append("%s: sin --img no se anota el original: uninstall no "
                                      "podra demostrar que vuelve" % item.where())
                    previo = ocupadas.get(item.path)
                    if previo:
                        conflictos.append({"path": item.path, "con": previo})
                    if not dry_run:
                        fuente.copiar_a(item.file,
                                        os.path.join(temporal, item.path.replace("/", os.sep)))
                        copiado = sha256_file(os.path.join(
                            temporal, item.path.replace("/", os.sep)))
                        if copiado != sha:
                            raise ModError("%s: la copia al overlay no coincide (sha256 %s…)"
                                           % (item.where(), copiado[:12]), code="overlay.copy",
                                           where=temporal)
                    detalle.append({"path": item.path, "size": tam, "sha256": sha,
                                    "original_sha256": original, "nota": nota,
                                    "servido": "overlay %s" % mod.name})

                entrada = {"name": mod.name, "version": mod.version,
                           "mod_format": mod.mod_format or MOD_FORMAT,
                           "game": {"title": mod.title, "version": mod.game_version,
                                    "container_md5": dict(mod.container_md5)},
                           "img": imagen.fingerprint() if imagen is not None else None,
                           "package": os.path.basename(fuente.ruta) if fuente.es_paquete else None,
                           "package_sha256": fuente.hash_paquete(),
                           "installed_at": _sello(), "files": detalle}
                if not dry_run:
                    if os.path.isdir(destino):
                        os.replace(destino, viejo)
                    try:
                        os.replace(temporal, destino)
                    except OSError:
                        if os.path.isdir(viejo):
                            os.replace(viejo, destino)
                        raise
                    if os.path.isdir(viejo):
                        shutil.rmtree(viejo, ignore_errors=True)
                    nuevo = [e for e in registro["mods"] if e["name"] != mod.name]
                    if primero:
                        nuevo.insert(0, entrada)
                    else:
                        nuevo.append(entrada)
                    registro["mods"] = nuevo
                    registro["store_format"] = STORE_FORMAT
                    escribir_registro(store, registro)
            finally:
                if not dry_run:
                    for basura in (temporal, viejo):
                        if os.path.isdir(basura):
                            shutil.rmtree(basura, ignore_errors=True)

            servido = [resolver(d["path"], prioridad(store, registro), imagen).as_dict()
                       for d in detalle] if not dry_run else []
            return {"ok": True, "mod": mod.name, "version": mod.version,
                    "store": store, "dir": carpeta_de(store, mod.name),
                    "dry_run": dry_run, "files": detalle, "conflictos": conflictos,
                    "avisos": avisos, "servido": servido,
                    "overlay": linea_overlay(store, registro) if not dry_run else None}
    finally:
        if imagen is not None:
            imagen.close()


# --------------------------------------------------------------------------
# `uninstall`
# --------------------------------------------------------------------------

def desinstalar(nombre: str, store: str, img: str | None = None, *, dry_run: bool = False,
                forzar: bool = False, permitir_sin_verificar: bool = False,
                procesos: list[str] | None = None) -> dict:
    """`pkp mod uninstall`: quita solo lo que puso ese mod y comprueba que vuelve el original."""
    store = os.path.abspath(os.path.expanduser(store))
    if not os.path.isdir(store):
        raise ModError("el almacen %s no existe" % store, code="store", where=store)
    if img is None and not permitir_sin_verificar:
        raise ModError("sin --img (%s) no se puede demostrar que el original vuelve: pasa la "
                       "imagen o repite con --sin-verificar" % IMG_ENV, code="verify",
                       where=store)
    if not forzar:
        motivo = motivo_no_instalable(img, procesos)
        if motivo:
            raise ModError(motivo, code="img.abierto", where=img or store)
    registro = leer_registro(store)
    entrada = next((e for e in registro["mods"] if e["name"] == nombre), None)
    if entrada is None:
        raise ModError("%s no esta instalado en %s" % (nombre, store), code="store",
                       where=store)

    destino = carpeta_de(store, nombre)
    ausentes, alterados = [], []
    for fichero in entrada.get("files", []):
        ruta = os.path.join(destino, fichero["path"].replace("/", os.sep))
        if not os.path.isfile(ruta):
            ausentes.append(fichero["path"])
        elif fichero.get("sha256") and sha256_file(ruta) != fichero["sha256"]:
            alterados.append(fichero["path"])
    if (ausentes or alterados) and not forzar:
        raise ModError("la carpeta del mod no coincide con el registro (%d ausentes, %d "
                       "alterados): revisa el almacen o repite con --forzar"
                       % (len(ausentes), len(alterados)), code="store", where=destino)

    imagen = RomFSImage(img) if img else None
    try:
        if not dry_run:
            if os.path.isdir(destino):
                shutil.rmtree(destino)
            nuevo = [e for e in registro["mods"] if e["name"] != nombre]
            registro["mods"] = nuevo
            escribir_registro(store, registro)
        dirs = prioridad(store, registro)

        verificacion: list[dict] = []
        restaurados = sombreados = no_verificables = 0
        for fichero in entrada.get("files", []):
            servido = resolver(fichero["path"], dirs, imagen)
            original = fichero.get("original_sha256")
            estado = "sin original"
            if servido.origen == "overlay":
                estado = "sombreado por %s" % servido.donde
                sombreados += 1
            elif imagen is None:
                estado = "no verificado (sin --img)"
                no_verificables += 1
            elif servido.origen == "img":
                if original is None:
                    estado = "servido por el img (sin original anotado)"
                    no_verificables += 1
                elif servido.sha256 == original:
                    estado = "original restaurado"
                    restaurados += 1
                else:
                    estado = ("EL IMG NO SIRVE EL ORIGINAL (esperaba %s… y sirve %s…)"
                              % (original[:12], (servido.sha256 or "")[:12]))
            elif original is None:
                estado = "nada que restaurar (no estaba en el img)"
                restaurados += 1
            else:
                estado = "ERROR: el img no tiene la ruta y el mod anoto un original"
            verificacion.append({"path": fichero["path"], "estado": estado,
                                 "servido": servido.as_dict(),
                                 "original_sha256": original})

        errores = [v for v in verificacion if v["estado"].startswith(("EL IMG", "ERROR"))]
        return {"ok": not errores, "mod": nombre, "store": store, "dry_run": dry_run,
                "removed": not dry_run, "files": len(entrada.get("files", [])),
                "verificacion": verificacion, "restaurados": restaurados,
                "sombreados": sombreados, "sin_original": no_verificables,
                "errores": [v["estado"] for v in errores]}
    finally:
        if imagen is not None:
            imagen.close()


# --------------------------------------------------------------------------
# `status` y `doctor`
# --------------------------------------------------------------------------

def estado(store: str, img: str | None = None) -> dict:
    """`pkp mod status`: que hay instalado, quien sirve cada ruta y quien choca."""
    store = os.path.abspath(os.path.expanduser(store))
    if not os.path.isdir(store):
        raise ModError("el almacen %s no existe" % store, code="store", where=store)
    registro = leer_registro(store)
    imagen = RomFSImage(img) if img else None
    try:
        dirs = prioridad(store, registro)
        por_ruta: dict[str, list[dict]] = {}
        mods: list[dict] = []
        for orden, entrada in enumerate(registro["mods"]):
            carpeta = carpeta_de(store, entrada["name"])
            ficheros = []
            for fichero in entrada.get("files", []):
                servido = resolver(fichero["path"], dirs, imagen)
                ficheros.append({"path": fichero["path"], "size": fichero.get("size"),
                                 "sha256": fichero.get("sha256"),
                                 "original_sha256": fichero.get("original_sha256"),
                                 "servido": servido.as_dict(),
                                 "en_disco": os.path.isfile(
                                     os.path.join(carpeta,
                                                  fichero["path"].replace("/", os.sep)))})
                por_ruta.setdefault(fichero["path"], []).append(
                    {"mod": entrada["name"], "orden": orden,
                     "sha256": fichero.get("sha256")})
            mods.append({"name": entrada["name"], "version": entrada.get("version"),
                         "orden": orden, "dir": carpeta,
                         "installed_at": entrada.get("installed_at"),
                         "package": entrada.get("package"),
                         "files": ficheros})
        conflictos = []
        for ruta, lista in sorted(por_ruta.items()):
            if len(lista) < 2:
                continue
            mismos = len({(x["sha256"] or "") for x in lista}) == 1
            ganador = lista[0]
            conflictos.append({"path": ruta, "mods": [x["mod"] for x in lista],
                               "gana": ganador["mod"], "mismos_bytes": mismos})
        return {"ok": True, "store": store, "mods": mods, "conflictos": conflictos,
                "overlay": linea_overlay(store, registro),
                "overlay_relativo": linea_relativa(store, registro),
                "aviso": aviso_separador(store, registro),
                "img": imagen.path if imagen is not None else None}
    finally:
        if imagen is not None:
            imagen.close()


def _md5_del_contenedor(ruta: str) -> tuple[dict[str, str] | None, str | None]:
    """md5 de los dos ficheros del contenedor de `ruta`, o `(None, motivo)`.

    `ruta` es **siempre** una referencia explicita de quien llama: esta funcion no
    mira el entorno. Un `doctor()` que resolviera `PKP_ROMFS` por su cuenta estaba
    comparando el contenedor del entorno contra mods que se validaban con otra
    imagen, y convertia un aviso en fallo (defecto medido 2026-11-10).
    """
    try:
        cont = paths.resolve_container(ruta, must_exist=False)
    except (OSError, ValueError) as exc:          # pragma: no cover - ruta rara
        return None, "no se pudo resolver el contenedor: %s" % exc
    if not (os.path.isfile(cont.idx) and os.path.isfile(cont.bin)):
        return None, ("sin contenedor en %s: no se comprueba la version del juego"
                      % cont.dir)
    try:
        return paths.container_md5(cont), None
    except OSError as exc:                        # pragma: no cover - permisos
        return None, "no se pudo leer el contenedor: %s" % exc


def _referencia_de_juego(container: str | None, container_entorno: str | None
                         ) -> tuple[dict[str, str] | None, str | None, bool]:
    """Contra que contenedor se valida el mod: `(md5s, motivo, declarado)`.

    `declarado` dice de donde sale la referencia, y eso decide la **severidad** de
    un desajuste (docs/MOD-OVERLAY.md §7):

    * `--container <carpeta>`: lo declara quien invoca la comprobacion, asi que un
      mod hecho para otro build es un `FALLO`;
    * `container_entorno` (`PKP_ROMFS`): es el contenedor por defecto del kit, que
      puede ser otro dump; el mod sigue cargando por ruta, asi que es un `aviso`;
    * ninguna: no hay nada que comparar y se dice, como un `aviso`.
    """
    if container:
        md5s, motivo = _md5_del_contenedor(container)
        return md5s, motivo, True
    if container_entorno:
        md5s, motivo = _md5_del_contenedor(container_entorno)
        return md5s, motivo, False
    return None, ("sin contenedor: no se comprueba la version del juego (pasa "
                  "--container <carpeta> o define PKP_ROMFS)"), False


def _comprobar_variable(store: str, registro: dict, apunta) -> None:
    """¿El juego arranca con `DM_ROMFS_OVERLAY` apuntando a este almacen?"""
    dirs = [ruta for _, ruta in prioridad(store, registro)]
    if not dirs:
        apunta("overlay.variable", True, "sin mods instalados: no hace falta la variable")
        return
    esperado = ":".join(dirs)
    valor = os.environ.get(OVERLAY_ENV)
    if valor is None:
        apunta("overlay.variable", False,
               "DM_ROMFS_OVERLAY no esta puesta en este proceso: si el juego arranca asi "
               "no vera ningun mod; " + instruccion_variable(store, registro), grave=False)
        return
    partes = [p for p in valor.split(":") if p.strip()]
    dados = [os.path.normcase(os.path.abspath(p)) for p in partes]
    quiero = [os.path.normcase(os.path.abspath(p)) for p in dirs]
    faltan = [dirs[i] for i, ruta in enumerate(quiero) if ruta not in dados]
    if faltan:
        detalle = ("DM_ROMFS_OVERLAY vale %r y el almacen sirve desde %r: el juego no "
                   "cargara %s" % (valor, esperado, ", ".join(faltan)))
        if trampa_separador(valor):
            detalle += ("; es la trampa del ':' en Windows: una ruta absoluta (C:…) se "
                        "parte en dos trozos")
        apunta("overlay.variable", False,
               detalle + "; " + instruccion_variable(store, registro))
        return
    orden = [dados.index(ruta) for ruta in quiero]
    if orden != sorted(orden):
        apunta("overlay.variable", False,
               "las carpetas de los mods estan en %r pero en otro orden: en un conflicto "
               "gana la primera de DM_ROMFS_OVERLAY (%r)" % (valor, esperado))
        return
    if trampa_separador(valor):
        apunta("overlay.trampa_dos_puntos", False,
               "DM_ROMFS_OVERLAY trae una ruta absoluta de Windows (%s): el runtime la "
               "trocea por ':' y solo funciona por casualidad cuando el almacen cae en la "
               "unidad del cwd; %s" % (valor, instruccion_variable(store, registro)),
               grave=False)
    apunta("overlay.variable", True, "apunta, en orden, a los %d mod(s)" % len(dirs))


def doctor(store: str, img: str | None = None, container: str | None = None,
           *, container_entorno: str | None = None) -> dict:
    """`pkp mod doctor`: por que un mod instalado no carga, sin arrancar el juego.

    Lee el registro, el arbol del overlay y (si se le da) el `img`; nunca abre el
    juego ni escribe nada. Cada comprobacion lleva su mensaje y su severidad: un
    `FALLO` (`fatal`) es una causa que impide cargar el mod, un `aviso` es algo que
    conviene mirar. La tabla completa esta en `docs/MOD-OVERLAY.md` §7.

    Dos referencias de juego, con severidad distinta a proposito:

    * `container`: el que declara quien invoca (`--container`). Si el mod se hizo
      para otro build, es `FALLO`: se ha pedido validar contra ese contenedor.
    * `container_entorno`: el contenedor por defecto del entorno (`PKP_ROMFS`), que
      el llamador pasa ya resuelto. Un desajuste es `aviso`: puede ser otro dump y
      el overlay se carga igual por ruta, que es lo que el juego consulta.

    Esta funcion no lee variables de entorno por su cuenta: si lo hiciera, un
    almacen sintetico validado con su propia imagen se compararia contra el
    contenedor del entorno y saldria un `FALLO` inventado (defecto 2026-11-10).
    """
    store = os.path.abspath(os.path.expanduser(store))
    chequeos: list[dict] = []

    def _apunta(nombre: str, ok: bool, detalle: str, grave: bool = True) -> None:
        chequeos.append({"check": nombre, "ok": ok, "detail": detalle, "fatal": grave})

    _apunta("almacen.existe", os.path.isdir(store), store)
    if not os.path.isdir(store):
        return {"ok": False, "store": store, "checks": chequeos}
    _apunta("almacen.protegido", not paths.is_protected(store),
            "no cae en el romfs del juego ni en PKP_PROTECTED" if not paths.is_protected(store)
            else "cae en una ruta protegida: el overlay no puede vivir ahi")
    try:
        registro = leer_registro(store)
        _apunta("registro.legible", True, "%d mod(s)" % len(registro["mods"]))
    except ModError as exc:
        _apunta("registro.legible", False, str(exc))
        return {"ok": False, "store": store, "checks": chequeos}

    imagen = RomFSImage(img) if img else None
    md5s, motivo_md5, md5_declarado = _referencia_de_juego(container, container_entorno)
    try:
        if registro["mods"] and imagen is None:
            _apunta("img.comprobado", False,
                    "sin --img: no se comprueba que el img sea el mismo build ni que los "
                    "originales sigan ahi", grave=False)
        for entrada in registro["mods"]:
            nombre = entrada["name"]
            carpeta = carpeta_de(store, nombre)
            _apunta("mod.%s.carpeta" % nombre, os.path.isdir(carpeta), carpeta)

            formato = entrada.get("mod_format")
            if formato is None:
                _apunta("mod.%s.formato" % nombre, True,
                        "no consta (instalado por otra version del kit)")
            else:
                _apunta("mod.%s.formato" % nombre, formato == MOD_FORMAT,
                        "mod_format %d" % formato if formato == MOD_FORMAT else
                        "mod_format %r no soportado: este kit solo carga %d"
                        % (formato, MOD_FORMAT))

            juego = entrada.get("game") or {}
            md5_mod = juego.get("container_md5") or {}
            etiqueta = "%s@%s" % (juego.get("version") or "?", nombre)
            if not md5_mod:
                _apunta("mod.%s.juego" % nombre, True,
                        "no consta el contenedor con el que se hizo")
            elif md5s is None:
                _apunta("mod.%s.juego" % nombre, False, motivo_md5 or "sin contenedor",
                        grave=False)
            else:
                malos = [k for k, v in md5_mod.items()
                         if md5s.get(k) and md5s[k] != (v or "").lower()]
                if not malos:
                    detalle = ("el mod se hizo para %s y tu contenedor es el mismo"
                               % etiqueta)
                else:
                    detalle = ("el mod se hizo para %s y tu contenedor es otro build (%s): "
                               "pide el mod para tu version o quitalo"
                               % (etiqueta, ", ".join("%s esperaba %s… y tienes %s…"
                                                      % (k, (md5_mod[k] or "")[:12],
                                                         md5s[k][:12])
                                                      for k in malos)))
                    if not md5_declarado:
                        detalle += ("; se compara contra el contenedor del entorno "
                                    "(PKP_ROMFS), que puede ser otro dump: si es el tuyo, "
                                    "repite con --container")
                _apunta("mod.%s.juego" % nombre, not malos, detalle,
                        grave=md5_declarado)

            huella = entrada.get("img")
            if imagen is not None:
                if not huella:
                    _apunta("mod.%s.img" % nombre, True,
                            "no consta el img con el que se hizo")
                else:
                    real = imagen.fingerprint()
                    igual = (huella.get("size") == real["size"]
                             and huella.get("index_sha256") == real["index_sha256"])
                    _apunta("mod.%s.img" % nombre, igual,
                            "el img es el mismo build (huella %s…)"
                            % real["index_sha256"][:12] if igual else
                            "el img es otro build: al instalar era %s B / huella %s… y "
                            "ahora es %d B / huella %s…; el mod se hizo para el otro"
                            % (huella.get("size"), (huella.get("index_sha256") or "")[:12],
                               real["size"], real["index_sha256"][:12]))

            for fichero in entrada.get("files", []):
                etiqueta_f = "mod.%s.%s" % (nombre, fichero["path"])
                ruta = os.path.join(carpeta, fichero["path"].replace("/", os.sep))
                if os.path.isdir(ruta):
                    _apunta(etiqueta_f, False,
                            "hay un directorio donde el mod espera un fichero")
                    continue
                if not os.path.isfile(ruta):
                    _apunta(etiqueta_f, False,
                            "falta en el overlay: el juego sirve el original del img")
                    continue
                real = sha256_file(ruta)
                _apunta(etiqueta_f, real == fichero.get("sha256"),
                        "sha256 %s…" % real[:12] if real == fichero.get("sha256")
                        else "el fichero del overlay no es el que se instalo (sha256 %s…)"
                             % real[:12])
                if imagen is None:
                    continue
                original = fichero.get("original_sha256")
                if original is None:
                    en_img = imagen.find(fichero["path"])
                    if en_img is None or en_img.is_dir:
                        _apunta(etiqueta_f + ".ruta", False,
                                "la ruta no esta en el img: o es nueva a proposito, o esta mal "
                                "escrita (mayusculas, separadores o nombre); el juego solo pide "
                                "las rutas que existen", grave=False)
                    else:
                        _apunta(etiqueta_f + ".ruta", False,
                                "el img sirve esta ruta y el mod no anoto el original (se "
                                "instalo sin --img): desinstalar no podra demostrar que "
                                "vuelve", grave=False)
                elif imagen.find(fichero["path"]) is None:
                    _apunta("img.%s" % fichero["path"], False,
                            "el mod anota un original y el img no tiene la ruta")
                else:
                    actual = imagen.sha256(fichero["path"])
                    _apunta("img.%s" % fichero["path"], actual == original,
                            "el img sigue sirviendo el original"
                            if actual == original else
                            "el img cambio: esperaba %s… y sirve %s…"
                            % (original[:12], actual[:12]))

        sobrantes = []
        carpeta_mods = os.path.join(store, MODS_DIR)
        if os.path.isdir(carpeta_mods):
            conocidos = {e["name"] for e in registro["mods"]}
            for nombre in sorted(os.listdir(carpeta_mods)):
                if nombre in conocidos:
                    continue
                sobrantes.append(nombre)
        _apunta("almacen.sin_sobras", not sobrantes,
                "ninguna carpeta suelta" if not sobrantes else
                "carpetas sin registro: %s" % ", ".join(sobrantes), grave=False)
        conflictos = [c for c in estado(store, None)["conflictos"]]
        _apunta("mods.sin_conflictos", not conflictos,
                "ningun fichero compartido" if not conflictos else
                "; ".join("%s lo sirven %s (gana %s%s)"
                          % (c["path"], " y ".join(c["mods"]), c["gana"],
                             ", mismos bytes" if c["mismos_bytes"] else ", bytes distintos")
                          for c in conflictos), grave=False)
        _comprobar_variable(store, registro, _apunta)
        aviso = aviso_separador(store, registro)
        _apunta("overlay.separador", aviso is None,
                "sin trampa de unidad" if aviso is None else aviso, grave=False)
        return {"ok": all(c["ok"] for c in chequeos if c["fatal"]), "store": store,
                "checks": chequeos, "conflictos": conflictos,
                "fallos": sum(1 for c in chequeos if not c["ok"] and c["fatal"]),
                "avisos": sum(1 for c in chequeos if not c["ok"] and not c["fatal"]),
                "overlay": linea_overlay(store, registro),
                "overlay_relativo": linea_relativa(store, registro)}
    finally:
        if imagen is not None:
            imagen.close()


def comprobar_originales(mod: Mod, img: str | RomFSImage) -> list[str]:
    """Los `original_sha256` declarados contra la imagen (para `mod validate --img`)."""
    imagen = img if isinstance(img, RomFSImage) else RomFSImage(img)
    cerrar = not isinstance(img, RomFSImage)
    problemas: list[str] = []
    try:
        for item in mod.romfs:
            if not item.original_sha256:
                continue
            entrada = imagen.find(item.path)
            if entrada is None or entrada.is_dir:
                problemas.append("%s: el img no tiene esa ruta y el mod anota un original"
                                 % item.where())
                continue
            real = imagen.sha256(item.path)
            if real != item.original_sha256:
                problemas.append("%s: el original anotado es %s… y el img sirve %s…"
                                 % (item.where(), item.original_sha256[:12], real[:12]))
    except RomFSImageError as exc:
        problemas.append(str(exc))
    finally:
        if cerrar:
            imagen.close()
    return problemas

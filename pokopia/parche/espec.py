"""Carga y validacion del parche de ejecutable (`*.parche.json`).

Contrato (D-020: la definicion del parche es **texto**, no un binario opaco):

    parche_format, nombre, version, descripcion,
    juego{titulo, version, fichero, tamano, md5, sha256, build_id},
    ediciones[{segmento, offset, esperado, nuevo, motivo}],
    reversion

Reglas duras, y el motivo de cada una:

- `juego.sha256` identifica el ejecutable **exacto** sobre el que se midio. Un
  parche atado a un sha256 deja de valer con la siguiente build del juego o del
  port, y eso tiene que verse antes de aplicarlo: el aplicador se niega si no casa.
- `esperado` son los bytes que hay hoy. Si no estan, el parche no es para este
  binario y no se escribe nada. Nunca se aplica "a ciegas" por offset.
- `esperado` y `nuevo` miden lo mismo y son distintos; todo en hexadecimal en
  minusculas, sin prefijos, para que el fichero se pueda revisar y comparar.
- `motivo` es obligatorio: cada byte cambiado dice que hace y por que.
- `reversion` es obligatoria: D-020 exige que el parche diga como se deshace.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .errors import ParcheError, UsageError
from .imagen import SEGMENTOS

PARCHE_FORMAT = 1
NOMBRE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HEX_RE = re.compile(r"^(?:[0-9a-f]{2})+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MD5_RE = re.compile(r"^[0-9a-f]{32}$")
BUILD_ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
TITULO_RE = re.compile(r"^[0-9A-F]{16}$")

CLAVES_TOP = {"parche_format", "nombre", "version", "descripcion", "juego", "ediciones",
              "reversion"}
CLAVES_JUEGO = {"titulo", "version", "fichero", "tamano", "md5", "sha256", "build_id"}
CLAVES_EDICION = {"segmento", "offset", "esperado", "nuevo", "motivo",
                  "instruccion_esperada", "instruccion_nueva"}


@dataclass(frozen=True)
class Edicion:
    """Una escritura declarada: en `segmento+offset` debe haber `esperado`."""

    segmento: str
    offset: int
    esperado: bytes
    nuevo: bytes
    motivo: str
    instruccion_esperada: str = ""
    instruccion_nueva: str = ""

    @property
    def tam(self) -> int:
        return len(self.nuevo)


@dataclass(frozen=True)
class Juego:
    titulo: str
    version: str
    fichero: str
    tamano: int
    md5: str
    sha256: str
    build_id: str


@dataclass(frozen=True)
class Espec:
    nombre: str
    version: str
    descripcion: str
    juego: Juego
    ediciones: tuple[Edicion, ...]
    reversion: str
    ruta: str = ""

    def pares_ips(self) -> list[tuple[int, bytes]]:
        """`[(offset_modulo, bytes_nuevos)]` en el orden declarado."""
        return [(e.offset, e.nuevo) for e in self.ediciones]

    def tabla(self) -> list[str]:
        """Definicion del parche en texto llano, para pegar en el informe."""
        lineas = [
            "parche   : %s %s" % (self.nombre, self.version),
            "juego    : %s  version %s  (%s)" % (self.juego.titulo, self.juego.version,
                                                 self.juego.fichero),
            "sha256   : %s" % self.juego.sha256,
            "md5      : %s  tamano %d B" % (self.juego.md5, self.juego.tamano),
            "build id : %s" % self.juego.build_id,
            "",
            "%-6s %-12s %-18s %-18s %s" % ("seg", "offset", "esperado", "nuevo", "que hace"),
        ]
        for e in self.ediciones:
            lineas.append("%-6s %#012x %-18s %-18s %s"
                          % (e.segmento, e.offset, e.esperado.hex(), e.nuevo.hex(), e.motivo))
            if e.instruccion_esperada or e.instruccion_nueva:
                lineas.append("%-6s %-12s %-18s %-18s"
                              % ("", "", e.instruccion_esperada, e.instruccion_nueva))
        lineas += ["", "reversion: %s" % self.reversion]
        return lineas


def cargar(ruta: str) -> Espec:
    """Lee y valida un `*.parche.json`. No toca el binario."""
    if not os.path.isfile(ruta):
        raise UsageError("no existe el parche: %s" % ruta, code="fichero")
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            bruto = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ParcheError("json invalido: %s" % exc, code="json", where=ruta) from exc
    return validar(bruto, ruta=ruta)


def validar(bruto, *, ruta: str = "") -> Espec:
    """Valida el diccionario ya cargado y devuelve la `Espec`."""
    if not isinstance(bruto, dict):
        raise ParcheError("la raiz tiene que ser un objeto json", code="formato", where=ruta)
    _solo_claves(bruto, CLAVES_TOP, "raiz", ruta)
    if bruto.get("parche_format") != PARCHE_FORMAT:
        raise ParcheError("parche_format %r: esta version entiende %d"
                          % (bruto.get("parche_format"), PARCHE_FORMAT),
                          code="formato", where=ruta)

    nombre = _texto(bruto, "nombre", ruta)
    if not NOMBRE_RE.match(nombre):
        raise ParcheError("nombre %r: minusculas, digitos y ._- (max 64)" % nombre,
                          code="formato", where=ruta)
    version = _texto(bruto, "version", ruta)
    descripcion = _texto(bruto, "descripcion", ruta)
    reversion = _texto(bruto, "reversion", ruta)

    juego = _juego(bruto.get("juego"), ruta)
    ediciones = _ediciones(bruto.get("ediciones"), ruta)
    return Espec(nombre=nombre, version=version, descripcion=descripcion, juego=juego,
                 ediciones=ediciones, reversion=reversion, ruta=ruta)


def _juego(bruto, ruta: str) -> Juego:
    if not isinstance(bruto, dict):
        raise ParcheError("falta el objeto `juego`", code="formato", where=ruta)
    _solo_claves(bruto, CLAVES_JUEGO, "juego", ruta)
    titulo = _texto(bruto, "titulo", ruta, donde="juego")
    if not TITULO_RE.match(titulo):
        raise ParcheError("juego.titulo %r: 16 hex en mayusculas (title id)" % titulo,
                          code="formato", where=ruta)
    fichero = _texto(bruto, "fichero", ruta, donde="juego")
    tamano = bruto.get("tamano")
    if not isinstance(tamano, int) or isinstance(tamano, bool) or tamano <= 0:
        raise ParcheError("juego.tamano tiene que ser un entero positivo", code="formato",
                          where=ruta)
    md5 = _texto(bruto, "md5", ruta, donde="juego")
    if not MD5_RE.match(md5):
        raise ParcheError("juego.md5 %r: 32 hex en minusculas" % md5, code="formato", where=ruta)
    sha = _texto(bruto, "sha256", ruta, donde="juego")
    if not SHA256_RE.match(sha):
        raise ParcheError("juego.sha256 %r: 64 hex en minusculas" % sha, code="formato",
                          where=ruta)
    build = _texto(bruto, "build_id", ruta, donde="juego")
    if not BUILD_ID_RE.match(build):
        raise ParcheError("juego.build_id %r: 32-64 hex en minusculas" % build, code="formato",
                          where=ruta)
    return Juego(titulo=titulo, version=_texto(bruto, "version", ruta, donde="juego"),
                 fichero=fichero, tamano=tamano, md5=md5, sha256=sha, build_id=build)


def _ediciones(bruto, ruta: str) -> tuple[Edicion, ...]:
    if not isinstance(bruto, list) or not bruto:
        raise ParcheError("`ediciones` tiene que ser una lista con al menos una", code="formato",
                          where=ruta)
    out: list[Edicion] = []
    vistos: set[tuple[str, int]] = set()
    for i, e in enumerate(bruto):
        donde = "ediciones[%d]" % i
        if not isinstance(e, dict):
            raise ParcheError("%s: tiene que ser un objeto" % donde, code="formato", where=ruta)
        _solo_claves(e, CLAVES_EDICION, donde, ruta)
        segmento = _texto(e, "segmento", ruta, donde=donde)
        if segmento not in SEGMENTOS:
            raise ParcheError("%s.segmento %r: uno de %s" % (donde, segmento, list(SEGMENTOS)),
                              code="formato", where=ruta)
        offset = _offset(e.get("offset"), donde, ruta)
        esperado = _hex(e, "esperado", donde, ruta)
        nuevo = _hex(e, "nuevo", donde, ruta)
        if len(esperado) != len(nuevo):
            raise ParcheError("%s: esperado %d B y nuevo %d B; tienen que medir lo mismo"
                              % (donde, len(esperado), len(nuevo)), code="formato", where=ruta)
        if esperado == nuevo:
            raise ParcheError("%s: `esperado` y `nuevo` son iguales, no cambia nada" % donde,
                              code="formato", where=ruta)
        motivo = _texto(e, "motivo", ruta, donde=donde)
        if len(motivo) < 12:
            raise ParcheError("%s.motivo: explica que hace el cambio (min 12 caracteres)" % donde,
                              code="formato", where=ruta)
        clave = (segmento, offset)
        if clave in vistos:
            raise ParcheError("%s: %s+%#x ya estaba editado" % (donde, segmento, offset),
                              code="formato", where=ruta)
        vistos.add(clave)
        out.append(Edicion(segmento=segmento, offset=offset, esperado=esperado, nuevo=nuevo,
                           motivo=motivo,
                           instruccion_esperada=_opcional(e, "instruccion_esperada"),
                           instruccion_nueva=_opcional(e, "instruccion_nueva")))
    return tuple(out)


def _solo_claves(bruto: dict, permitidas: set[str], donde: str, ruta: str) -> None:
    sobran = sorted(set(bruto) - permitidas)
    if sobran:
        raise ParcheError("%s: claves que no entiendo: %s" % (donde, ", ".join(sobran)),
                          code="formato", where=ruta)
    faltan = sorted(permitidas - set(bruto) - {"instruccion_esperada", "instruccion_nueva"})
    if faltan:
        raise ParcheError("%s: faltan claves: %s" % (donde, ", ".join(faltan)),
                          code="formato", where=ruta)


def _texto(bruto: dict, clave: str, ruta: str, donde: str = "") -> str:
    valor = bruto.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise ParcheError("%s%s: texto no vacio obligatorio"
                          % ((donde + ".") if donde else "", clave),
                          code="formato", where=ruta)
    return valor.strip()


def _opcional(bruto: dict, clave: str) -> str:
    valor = bruto.get(clave, "")
    return valor.strip() if isinstance(valor, str) else ""


def _offset(valor, donde: str, ruta: str) -> int:
    if isinstance(valor, int) and not isinstance(valor, bool):
        if valor < 0:
            raise ParcheError("%s.offset negativo" % donde, code="formato", where=ruta)
        return valor
    if isinstance(valor, str):
        texto = valor.strip().lower()
        try:
            n = int(texto, 16) if texto.startswith("0x") else int(texto, 0)
        except ValueError as exc:
            raise ParcheError("%s.offset %r no es un entero" % (donde, valor),
                              code="formato", where=ruta) from exc
        if n < 0:
            raise ParcheError("%s.offset negativo" % donde, code="formato", where=ruta)
        return n
    raise ParcheError("%s.offset: entero o cadena hex (\"0x...\")" % donde, code="formato",
                      where=ruta)


def _hex(bruto: dict, clave: str, donde: str, ruta: str) -> bytes:
    valor = bruto.get(clave)
    if not isinstance(valor, str):
        raise ParcheError("%s.%s: cadena hexadecimal" % (donde, clave), code="formato",
                          where=ruta)
    texto = valor.strip().lower()
    if texto.startswith("0x"):
        texto = texto[2:]
    if not HEX_RE.match(texto):
        raise ParcheError("%s.%s %r: hex en minusculas de longitud par (4 B = 8 caracteres)"
                          % (donde, clave, valor), code="formato", where=ruta)
    return bytes.fromhex(texto)

"""Parche de ejecutable: esquema del `*.parche.json`, IPS32 y aplicacion/reversion.

Todo se prueba sobre un **NSO sintetico** (cabecera de 0x100 B + tres segmentos de
pocos bytes), sin tocar el dump ni el ejecutable del juego: los tests tienen que
poder correr en cualquier maquina.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct

import pytest

from pokopia import parche
from pokopia.parche import espec as espec_mod
from pokopia.parche import imagen as imagen_mod
from pokopia.parche import ips as ips_mod

BUILD_ID = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"


# --------------------------------------------------------------------------
# NSO sintetico
# --------------------------------------------------------------------------

def lz4_literales(datos: bytes) -> bytes:
    """Bloque LZ4 valido solo con literales (sin matches), para probar la lectura."""
    n = len(datos)
    out = bytearray([min(n, 15) << 4])
    resto = n - 15
    if resto > 0:
        while resto >= 255:
            out.append(255)
            resto -= 255
        out.append(resto)
    out += datos
    return bytes(out)


def nso_sintetico(segmentos: dict[str, bytes] | None = None,
                  comprimir: tuple[str, ...] = (), base: int = 0) -> bytes:
    """Construye un NSO0 con los segmentos dados (text, rodata, data)."""
    if segmentos is None:
        segmentos = {"text": bytes(range(0x40)), "rodata": b"RO" * 8, "data": b"DA" * 4}
    cab = bytearray(0x100)
    cab[0:4] = b"NSO0"
    struct.pack_into("<I", cab, 0x04, 0)
    cab[0x40:0x60] = bytes.fromhex(BUILD_ID)
    cuerpo = b""
    off = 0x100
    ubicacion = {"text": base, "rodata": base + 0x1000, "data": base + 0x2000}
    flags = 0
    for i, nombre in enumerate(imagen_mod.SEGMENTOS):
        datos = segmentos[nombre]
        crudo = lz4_literales(datos) if nombre in comprimir else datos
        if nombre in comprimir:
            flags |= 1 << i
        struct.pack_into("<IIII", cab, 0x10 + i * 0x10, off + len(cuerpo), ubicacion[nombre],
                         len(datos), 0)
        struct.pack_into("<I", cab, 0x60 + i * 4, len(crudo))
        cab[0xA0 + i * 0x20:0xC0 + i * 0x20] = hashlib.sha256(datos).digest()
        cuerpo += crudo
    struct.pack_into("<I", cab, 0x0C, flags)
    return bytes(cab) + cuerpo


def _espec(bruto_binario: bytes, ediciones: list[dict], **cambios) -> dict:
    """Documento de parche coherente con un binario dado."""
    doc = {
        "parche_format": 1,
        "nombre": "prueba-parche",
        "version": "0.1.0",
        "descripcion": "parche de prueba sobre un NSO sintetico",
        "juego": {
            "titulo": "0400A3A01EE4C000",
            "version": "2.0.1a",
            "fichero": "exefs/main",
            "tamano": len(bruto_binario),
            "md5": hashlib.md5(bruto_binario).hexdigest(),  # noqa: S324 - identificador
            "sha256": hashlib.sha256(bruto_binario).hexdigest(),
            "build_id": BUILD_ID,
        },
        "ediciones": ediciones,
        "reversion": "borrar el .ips y la imagen parcheada (tools/parche.py revertir)",
    }
    doc.update(cambios)
    return doc


def _edicion(esperado: bytes, nuevo: bytes, offset: int = 0x10,
             segmento: str = "text") -> dict:
    return {"segmento": segmento, "offset": hex(offset), "esperado": esperado.hex(),
            "nuevo": nuevo.hex(), "motivo": "cambia cuatro bytes para la prueba"}


# --------------------------------------------------------------------------
# Imagen del modulo
# --------------------------------------------------------------------------

def test_cabecera_rechaza_magia():
    with pytest.raises(parche.ParcheError) as exc:
        imagen_mod.leer_cabecera(b"XXXX" + bytes(0xFC))
    assert "NSO0" in str(exc.value)


def test_imagen_coloca_segmentos_en_su_base(tmp_path):
    bruto = nso_sintetico(base=0x1000)
    ruta = tmp_path / "main"
    ruta.write_bytes(bruto)
    imagen, cab = imagen_mod.leer(str(ruta))
    assert cab.build_id == BUILD_ID
    assert len(imagen) == imagen_mod.CABECERA + 0x3000 + 8
    # text empieza en base 0x1000 -> offset en la imagen 0x100 + 0x1000
    assert imagen[0x100 + 0x1000:0x100 + 0x1004] == bytes(range(4))


def test_imagen_descomprime_segmentos(tmp_path):
    bruto = nso_sintetico(comprimir=("text", "data"))
    ruta = tmp_path / "main"
    ruta.write_bytes(bruto)
    imagen, _cab = imagen_mod.leer(str(ruta))
    assert imagen[0x100:0x104] == bytes(range(4))
    assert imagen[0x100 + 0x2000:0x100 + 0x2004] == b"DADA"


def test_lz4_rechaza_bloque_corrupto():
    with pytest.raises(parche.ParcheError):
        imagen_mod.descomprimir_lz4(b"\x00\x00\x00", 8)


# --------------------------------------------------------------------------
# IPS32
# --------------------------------------------------------------------------

def test_ips32_reproduce_el_ejemplo_documentado():
    """offset_modulo 0x02749490 -> registro 0x02749590 (cabecera de 0x100 B)."""
    datos = ips_mod.construir([(0x02749490, b"\xaa")])
    assert datos == b"IPS32" + bytes.fromhex("02749590" "0001" "aa") + b"EEOF"


def test_ips32_ida_y_vuelta():
    datos = ips_mod.construir([(0x10, b"\x1f\x20\x03\xd5"), (0x20, b"\x00\x01")])
    assert ips_mod.leer(datos) == [(0x110, b"\x1f\x20\x03\xd5"), (0x120, b"\x00\x01")]


def test_ips32_rechaza_edicion_vacia():
    with pytest.raises(parche.ParcheError):
        ips_mod.construir([(0x10, b"")])


# --------------------------------------------------------------------------
# Esquema
# --------------------------------------------------------------------------

def test_esquema_minimo_valido(tmp_path):
    bruto = nso_sintetico()
    doc = _espec(bruto, [_edicion(bruto[0x100 + 0x10:0x100 + 0x14], b"\x1f\x20\x03\xd5")])
    espec = espec_mod.validar(doc)
    assert espec.nombre == "prueba-parche"
    assert espec.pares_ips() == [(0x10, b"\x1f\x20\x03\xd5")]


@pytest.mark.parametrize("cambio, aguja", [
    ({"parche_format": 2}, "parche_format"),
    ({"nombre": "Mayusculas"}, "nombre"),
    ({"reversion": "  "}, "reversion"),
    ({"ediciones": []}, "ediciones"),
])
def test_esquema_rechaza_campos(cambio, aguja):
    bruto = nso_sintetico()
    doc = _espec(bruto, [_edicion(bruto[0x110:0x114], b"\x1f\x20\x03\xd5")])
    doc.update(cambio)
    with pytest.raises(parche.ParcheError) as exc:
        espec_mod.validar(doc)
    assert aguja in str(exc.value).lower() or aguja in str(exc.value)


def test_esquema_rechaza_clave_sobrante():
    bruto = nso_sintetico()
    doc = _espec(bruto, [_edicion(bruto[0x110:0x114], b"\x1f\x20\x03\xd5")])
    doc["comentario"] = "no"
    with pytest.raises(parche.ParcheError) as exc:
        espec_mod.validar(doc)
    assert "comentario" in str(exc.value)


def test_esquema_rechaza_esperado_igual_a_nuevo():
    bruto = nso_sintetico()
    iguales = bruto[0x110:0x114]
    doc = _espec(bruto, [_edicion(iguales, iguales)])
    with pytest.raises(parche.ParcheError) as exc:
        espec_mod.validar(doc)
    assert "iguales" in str(exc.value)


def test_esquema_rechaza_tamanos_distintos():
    bruto = nso_sintetico()
    doc = _espec(bruto, [_edicion(bruto[0x110:0x114], b"\x1f\x20")])
    with pytest.raises(parche.ParcheError) as exc:
        espec_mod.validar(doc)
    assert "medir lo mismo" in str(exc.value)


def test_esquema_rechaza_dos_ediciones_en_el_mismo_sitio():
    bruto = nso_sintetico()
    esperado = bruto[0x110:0x114]
    doc = _espec(bruto, [_edicion(esperado, b"\x1f\x20\x03\xd5"),
                         _edicion(esperado, b"\x00\x00\x00\x00")])
    with pytest.raises(parche.ParcheError) as exc:
        espec_mod.validar(doc)
    assert "ya estaba editado" in str(exc.value)


# --------------------------------------------------------------------------
# Comprobar / aplicar / revertir
# --------------------------------------------------------------------------

def _preparar(tmp_path, comprimir=()):
    bruto = nso_sintetico(comprimir=comprimir)
    original = tmp_path / "orig" / "main"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(bruto)
    esperado = bruto[0x100 + 0x10:0x100 + 0x14] if not comprimir else bytes(range(0x10, 0x14))
    doc = _espec(bruto, [_edicion(esperado, b"\x1f\x20\x03\xd5")])
    ruta_espec = tmp_path / "p.parche.json"
    ruta_espec.write_text(json.dumps(doc), encoding="utf-8")
    return str(original), parche.cargar(str(ruta_espec)), bruto


def test_comprobar_no_escribe_y_ve_los_bytes(tmp_path):
    binario, espec, bruto = _preparar(tmp_path)
    informe = parche.comprobar(binario, espec)
    assert informe["identidad"]["sha256"] == hashlib.sha256(bruto).hexdigest()
    assert [c["ok"] for c in informe["ediciones"]] == [True]
    assert sorted(os.listdir(tmp_path)) == ["orig", "p.parche.json"]


def test_sha256_distinto_se_niega_sin_escribir(tmp_path):
    binario, espec, _bruto = _preparar(tmp_path)
    otro = tmp_path / "otro" / "main"
    otro.parent.mkdir()
    otro.write_bytes(nso_sintetico({"text": b"\xff" * 0x40, "rodata": b"", "data": b""}))
    salida = tmp_path / "out"
    with pytest.raises(parche.IdentidadError) as exc:
        parche.aplicar(str(otro), espec, str(salida))
    assert exc.value.exit_code == 3
    assert not salida.exists()
    # y el original del que se copio el parche sigue intacto
    assert hashlib.sha256(open(binario, "rb").read()).hexdigest() == espec.juego.sha256


def test_bytes_esperados_distintos_se_niegan(tmp_path):
    binario, espec, _bruto = _preparar(tmp_path)
    malo = parche.Espec(nombre=espec.nombre, version=espec.version,
                        descripcion=espec.descripcion, juego=espec.juego,
                        ediciones=(parche.Edicion(segmento="text", offset=0x10,
                                                  esperado=b"\xde\xad\xbe\xef",
                                                  nuevo=b"\x1f\x20\x03\xd5",
                                                  motivo="bytes que no estan"),),
                        reversion=espec.reversion)
    salida = tmp_path / "out"
    with pytest.raises(parche.BytesError) as exc:
        parche.comprobar(binario, malo)
    assert exc.value.exit_code == 4
    assert "deadbeef" in str(exc.value)
    assert not salida.exists()


@pytest.mark.parametrize("comprimir", [(), ("text",)])
def test_aplicar_y_revertir_deja_todo_como_estaba(tmp_path, comprimir):
    binario, espec, bruto = _preparar(tmp_path, comprimir=comprimir)
    salida = tmp_path / "out"

    antes = hashlib.sha256(open(binario, "rb").read()).hexdigest()
    informe = parche.aplicar(binario, espec, salida)

    assert informe["imagen"]["sha256_antes"] != informe["imagen"]["sha256_despues"]
    assert os.path.isfile(os.path.join(str(salida), "imagen.original"))
    assert os.path.isfile(os.path.join(str(salida), "imagen.parcheada"))
    ruta_ips = os.path.join(str(salida), BUILD_ID + ".ips")
    assert os.path.isfile(ruta_ips)

    parcheada = open(os.path.join(str(salida), "imagen.parcheada"), "rb").read()
    original = open(os.path.join(str(salida), "imagen.original"), "rb").read()
    distintos = [i for i in range(len(original)) if original[i] != parcheada[i]]
    assert distintos == [0x110, 0x111, 0x112, 0x113]
    assert parcheada[0x110:0x114] == b"\x1f\x20\x03\xd5"
    # el .ips apunta al offset de la imagen, no al del modulo
    assert ips_mod.leer(open(ruta_ips, "rb").read()) == [(0x110, b"\x1f\x20\x03\xd5")]

    rev = parche.revertir(binario, espec, salida)
    assert rev["revertido"] is True
    assert rev["sha256_imagen"] == informe["imagen"]["sha256_antes"]
    assert not os.path.isfile(ruta_ips)
    assert not os.path.isfile(os.path.join(str(salida), "imagen.parcheada"))
    # el ejecutable original nunca se ha tocado
    assert hashlib.sha256(open(binario, "rb").read()).hexdigest() == antes == espec.juego.sha256


def test_aplicar_no_escribe_junto_al_original(tmp_path):
    binario, espec, _bruto = _preparar(tmp_path)
    salida = os.path.join(os.path.dirname(binario), "out")
    with pytest.raises(parche.GuardError):
        parche.aplicar(binario, espec, salida)
    assert not os.path.exists(salida)


def test_offset_fuera_del_segmento_se_rechaza(tmp_path):
    bruto = nso_sintetico()
    doc = _espec(bruto, [_edicion(b"\x00\x00\x00\x00", b"\x01\x00\x00\x00", offset=0x3E)])
    ruta = tmp_path / "main"
    ruta.write_bytes(bruto)
    espec = espec_mod.validar(doc)
    with pytest.raises(parche.ParcheError) as exc:
        parche.comprobar(str(ruta), espec)
    assert "se sale del segmento" in str(exc.value)


def test_mostrar_define_el_parche_en_texto(tmp_path):
    _binario, espec, _bruto = _preparar(tmp_path)
    texto = "\n".join(espec.tabla())
    assert "sha256" in texto and "esperado" in texto and "nuevo" in texto
    assert "reversion" in texto
    assert espec.juego.sha256 in texto


@pytest.mark.skipif(
    not os.path.isdir(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "parches")),
    reason="parches/ no viaja en el paquete (lista blanca)",
)
def test_los_parches_del_repo_cargan():
    """Todo `parches/*.parche.json` del repo tiene que cumplir el contrato."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    carpeta = os.path.join(raiz, "parches")
    ficheros = sorted(f for f in os.listdir(carpeta) if f.endswith(".parche.json"))
    assert ficheros, "el repo no declara ningun parche"
    for fichero in ficheros:
        espec = parche.cargar(os.path.join(carpeta, fichero))
        assert espec.ediciones, fichero
        assert espec.juego.sha256 and espec.reversion
        # el .ips se emite y se vuelve a leer: los bytes son los del texto
        datos = ips_mod.construir(espec.pares_ips())
        assert ips_mod.leer(datos) == [(ips_mod.BASE_IMAGEN + e.offset, e.nuevo)
                                       for e in espec.ediciones]


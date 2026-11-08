#!/usr/bin/env python3
"""Codec de texturas: PNG y BCn. Backend opcional, cargado bajo demanda.

El parseo del `.g1t` (`pokopia/g1t.py`) es stdlib puro. Para **ver** y **repintar**
los pixeles hace falta un decodificador/compilador de BC, y escribir uno a mano
esta fuera de alcance: se usan librerias existentes.

    numpy         -> reordenar tiles (rapido)
    imagecodecs   -> decodifica BC1/BC3/BC4/BC5/BC6H/BC7 (lib `bcdec`) y PNG
    etcpak        -> compila BC1/BC3/BC4/BC5/BC7 (sin BC6H)

Se instalan a mano (no hay extra declarado en `pyproject.toml`):

    uv pip install numpy imagecodecs etcpak

Sin ellas, `pkp tex list` y `pkp tex inject --same` siguen funcionando (no tocan
pixeles), y `extract`/`inject --png` fallan con un mensaje que dice que falta.
"""

from __future__ import annotations

from typing import Any

from .g1t import Format, format_of, retile, tile_map, untile

#: Codigos que se pueden decodificar (imagecodecs.BCN) y compilar (etcpak).
DECODABLE = {0x10, 0x12, 0x3C, 0x3D, 0x59, 0x5B, 0x5F, 0x60, 0x62, 0x63, 0x64, 0x65, 0x66}
RAW_RGBA8 = {0x01, 0x0A}
RAW_OTHER = {0x0B, 0x0C, 0x0D}

#: Nombre de `imagecodecs.BCN.FORMAT` -> canales utiles.
_BCN = {0x60: ("BC1", 4), 0x10: ("BC1", 4), 0x3C: ("BC1", 4), 0x3D: ("BC1", 4),
        0x59: ("BC1", 4), 0x62: ("BC3", 4), 0x12: ("BC3", 4), 0x5B: ("BC3", 4),
        0x63: ("BC4", 1), 0x64: ("BC5", 2), 0x65: ("BC6HU", 3),
        0x66: ("BC7", 4), 0x5F: ("BC7", 4)}

#: Codigo -> funcion de `etcpak` que compila ese formato.
_ETCPAK = {0x60: "compress_bc1", 0x62: "compress_bc3", 0x63: "compress_bc4",
           0x64: "compress_bc5", 0x66: "compress_bc7", 0x10: "compress_bc1",
           0x12: "compress_bc3", 0x59: "compress_bc1", 0x5B: "compress_bc3",
           0x5F: "compress_bc7"}

#: Todo lo que `etcpak` sabe compilar (BC6H no tiene codificador: ese 0,15 % no se escribe).
ENCODABLE_BC = frozenset(_ETCPAK)


class TextureBackendMissing(RuntimeError):
    """Falta numpy/imagecodecs/etcpak. La CLI lo traduce a exit 2."""

    exit_code = 2


class TextureFormatError(RuntimeError):
    """El formato no se puede leer o escribir con el backend disponible."""

    exit_code = 1


def _np() -> Any:
    try:
        import numpy
    except ImportError:  # pragma: no cover - depende del entorno
        raise TextureBackendMissing(
            "falta numpy: instala el extra de texturas\n"
            "  uv pip install -e \".[textures]\"") from None
    return numpy


def _ic() -> Any:
    try:
        import imagecodecs
    except ImportError:  # pragma: no cover - depende del entorno
        raise TextureBackendMissing(
            "falta imagecodecs (decodificador BC y PNG): instala el extra de texturas\n"
            "  uv pip install -e \".[textures]\"") from None
    return imagecodecs


def _etcpak() -> Any:
    try:
        import etcpak
    except ImportError:  # pragma: no cover - depende del entorno
        raise TextureBackendMissing(
            "falta etcpak (compilador BC): instala el extra de texturas\n"
            "  uv pip install -e \".[textures]\"") from None
    return etcpak


def backend_status() -> dict[str, bool]:
    """Que piezas del backend estan disponibles en este interprete."""
    estado = {}
    for nombre in ("numpy", "imagecodecs", "etcpak"):
        try:
            __import__(nombre)
            estado[nombre] = True
        except Exception:  # noqa: BLE001 - solo se informa
            estado[nombre] = False
    return estado


def decodable(code: int) -> bool:
    return code in DECODABLE or code in RAW_RGBA8 or code in RAW_OTHER


def encodable(code: int) -> bool:
    """True si hay compilador para ese formato (lo que se puede reinyectar)."""
    return code in ENCODABLE_BC or code in RAW_RGBA8 or code in RAW_OTHER


def _untile_np(payload: bytes, width: int, height: int, fmt: Format) -> bytes:
    np = _np()
    idx = np.asarray(tile_map(width, height, fmt), dtype=np.int64)
    b = fmt.block
    a = np.frombuffer(payload, np.uint8)[: idx.size * b].reshape(-1, b)
    return a[idx].reshape(-1).tobytes()


def decode_rgba(payload: bytes, width: int, height: int, fmt: Format):
    """Decodifica un nivel de mip a un array (alto, ancho, 4) uint8 en RGBA."""
    np = _np()
    if not decodable(fmt.code):
        raise TextureFormatError(
            "formato %s (0x%02x): no hay decodificador disponible" % (fmt.name, fmt.code))
    crudo = _untile_np(payload, width, height, fmt) if fmt.swizzled else payload
    if fmt.code in _BCN:
        ic = _ic()
        nombre, canales = _BCN[fmt.code]
        forma = (height, width) if canales == 1 else (height, width, canales)
        datos = np.asarray(ic.bcn_decode(crudo, getattr(ic.BCN.FORMAT, nombre),
                                         shape=forma))
        if canales == 1:
            datos = np.dstack([datos, datos, datos, np.full_like(datos, 255)])
        elif canales == 2:
            datos = np.dstack([datos[..., 0], datos[..., 1],
                               np.zeros_like(datos[..., 0]),
                               np.full_like(datos[..., 0], 255)])
        elif canales == 3:
            datos = np.dstack([datos[..., 0], datos[..., 1], datos[..., 2],
                               np.full_like(datos[..., 0], 255)])
        return np.ascontiguousarray(datos.astype(np.uint8))
    a = np.frombuffer(crudo, np.uint8).reshape(height, width, fmt.block)
    if fmt.code == 0x0A:      # BGRA
        return np.ascontiguousarray(a[..., [2, 1, 0, 3]])
    if fmt.code == 0x01:      # RGBA
        return np.ascontiguousarray(a)
    if fmt.code == 0x0B:      # R32F
        return _float_a_rgba(a.view(np.float32)[..., 0])
    if fmt.code == 0x0C:      # RG8
        dos = a.reshape(height, width, 2)
        return np.dstack([dos[..., 0], dos[..., 1], np.zeros_like(dos[..., 0]),
                          np.full_like(dos[..., 0], 255)])
    if fmt.code == 0x0D:      # RGBA32F
        return _float_a_rgba(a.view(np.float32))
    raise TextureFormatError("formato %s: decodificador no escrito" % fmt.name)


def _float_a_rgba(flotantes):
    np = _np()
    x = np.clip(flotantes.astype(np.float32), 0.0, 1.0) * 255.0
    x = x.astype(np.uint8)
    if x.ndim == 2:
        return np.dstack([x, x, x, np.full_like(x, 255)])
    return np.ascontiguousarray(x)


def encode_rgba(img, width: int, height: int, fmt: Format) -> bytes:
    """Compila un array RGBA a los bytes del nivel de mip, en orden de fichero."""
    np = _np()
    if img.shape[:2] != (height, width):
        raise TextureFormatError(
            "la imagen mide %dx%d y la textura %dx%d"
            % (img.shape[1], img.shape[0], width, height))
    if not encodable(fmt.code):
        raise TextureFormatError(
            "formato %s (0x%02x): no hay compilador disponible" % (fmt.name, fmt.code))
    if fmt.code in _ETCPAK:
        ep = _etcpak()
        funcion = getattr(ep, _ETCPAK[fmt.code])
        crudo = funcion(np.ascontiguousarray(img, dtype=np.uint8).tobytes(),
                        width, height)
    elif fmt.code == 0x01:
        crudo = np.ascontiguousarray(img, dtype=np.uint8).tobytes()
    elif fmt.code == 0x0A:
        crudo = np.ascontiguousarray(img[..., [2, 1, 0, 3]], dtype=np.uint8).tobytes()
    elif fmt.code == 0x0B:
        crudo = (img[..., 0].astype(np.float32) / 255.0).tobytes()
    elif fmt.code == 0x0C:
        crudo = np.ascontiguousarray(img[..., :2], dtype=np.uint8).tobytes()
    elif fmt.code == 0x0D:
        crudo = (np.ascontiguousarray(img, dtype=np.uint8).astype(np.float32)
                 / 255.0).tobytes()
    else:  # pragma: no cover - cubierto por `encodable`
        raise TextureFormatError("formato %s: compilador no escrito" % fmt.name)
    esperado = fmt.size(width, height)
    if len(crudo) != esperado:
        raise TextureFormatError(
            "el compilador de %s devolvio %d B y se esperaban %d"
            % (fmt.name, len(crudo), esperado))
    return retile(crudo, width, height, fmt) if fmt.swizzled else crudo


def png_encode(img) -> bytes:
    """PNG RGBA8 (sin perdida) a partir del array."""
    return _ic().png_encode(_np().ascontiguousarray(img, dtype=_np().uint8))


def png_decode(datos: bytes):
    """PNG -> array (alto, ancho, 4) uint8."""
    np = _np()
    img = np.asarray(_ic().png_decode(datos))
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = np.dstack([img, img, img, np.full_like(img, 255)])
    elif img.shape[2] == 3:
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    return np.ascontiguousarray(img)


__all__ = [
    "DECODABLE",
    "ENCODABLE_BC",
    "RAW_OTHER",
    "RAW_RGBA8",
    "TextureBackendMissing",
    "TextureFormatError",
    "backend_status",
    "decodable",
    "decode_rgba",
    "encode_rgba",
    "encodable",
    "png_decode",
    "png_encode",
]

"""Blowfish: vectores de prueba publicos y vuelta ida/vuelta.

Los vectores son los de Eric Young que publica el propio autor del algoritmo
(`vectors-2.txt`), 16 rondas, ECB, sin relleno. Si las cajas derivadas de pi no
coinciden con las de Blowfish, el primer vector ya falla.
"""

from __future__ import annotations

import pytest

from pokopia.blowfish import BLOQUE, Blowfish, BlowfishError

#: (clave en hex, texto claro en hex, texto cifrado en hex) de `vectors-2.txt`.
VECTORES = [
    ("0000000000000000", "0000000000000000", "4EF997456198DD78"),
    ("FFFFFFFFFFFFFFFF", "FFFFFFFFFFFFFFFF", "51866FD5B85ECB8A"),
    ("3000000000000000", "1000000000000001", "7D856F9A613063F2"),
    ("1111111111111111", "1111111111111111", "2466DD878B963C9D"),
    ("0123456789ABCDEF", "1111111111111111", "61F9C3802281B096"),
    ("FEDCBA9876543210", "0123456789ABCDEF", "0ACEAB0FC6A0A28D"),
    ("0123456789ABCDEF", "0000000000000000", "245946885754369A"),
]


@pytest.mark.parametrize("clave,claro,cifrado", VECTORES)
def test_vectores_publicos(clave: str, claro: str, cifrado: str) -> None:
    bf = Blowfish(bytes.fromhex(clave))
    assert bf.cifra_bloque(bytes.fromhex(claro)).hex().upper() == cifrado
    assert bf.descifra_bloque(bytes.fromhex(cifrado)).hex().upper() == claro


def test_ida_y_vuelta_de_un_bloque_y_de_un_flujo() -> None:
    bf = Blowfish(bytes.fromhex("b83b9a3ad48a0b"))   # la clave del dump
    bloque = bytes(range(8))
    assert bf.descifra_bloque(bf.cifra_bloque(bloque)) == bloque
    flujo = bytes(range(64))
    assert bf.descifra(bf.cifra(flujo)) == flujo


def test_el_relleno_cifrado_es_el_mismo_bloque_para_todos_los_ceros() -> None:
    """ECB: el relleno de una ranura es el cifrado de 8 ceros, repetido."""
    bf = Blowfish(bytes.fromhex("b83b9a3ad48a0b"))
    relleno = bf.cifra_relleno_cero(b"KA1A0000", 8 * 4)
    cero = bf.cifra_bloque(bytes(BLOQUE))
    assert relleno == bf.cifra(b"KA1A0000") + cero * 3
    assert bf.descifra(relleno) == b"KA1A0000" + bytes(BLOQUE * 3)


def test_longitudes_y_claves_que_no_valen() -> None:
    with pytest.raises(BlowfishError):
        Blowfish(b"\x00\x01\x02")            # 3 B: por debajo del minimo
    with pytest.raises(BlowfishError):
        Blowfish(bytes(57))                  # 57 B: por encima del maximo
    with pytest.raises(BlowfishError):
        Blowfish(bytes(8)).cifra(b"\x00" * 7)
    with pytest.raises(BlowfishError):
        Blowfish(bytes(8)).cifra_relleno_cero(b"\x00" * 16, 8)

"""Blowfish ECB (cifrado y descifrado) con las cajas derivadas de pi.

Blowfish es un cifrador simetrico de bloque de 64 bits que Koei Tecmo usa para
guardar los datos de cada pista dentro de los `.srst` (ver `docs/AUDIO-SRST.md`).
Es ECB: cada bloque de 8 B se cifra por separado y el mismo texto claro da
siempre el mismo texto cifrado, asi que una pista se puede reescribir en su
sitio sin tocar nada mas.

Las cajas P y S de Blowfish son, por definicion del algoritmo, los primeros
4.168 digitos hexadecimales de la parte fraccionaria de pi. Aqui se **calculan**
con la formula de Machin en aritmetica entera (no se copia ninguna tabla de
nadie):

    pi = 16*atan(1/5) - 4*atan(1/239)

Se valida contra las cuatro primeras constantes conocidas del algoritmo
(0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344) y contra los vectores de
prueba publicos de Eric Young (`tests/test_blowfish.py`): si algo no cuadra, el
modulo falla en vez de devolver basura.

Punto que hay que respetar o el descifrado devuelve ruido sin dar error: la
clave se expande **byte a byte y en ciclo**, con el periodo de su longitud real.
Con una clave de 7 B (la de este dump) leida como palabras de 32 bits las tablas
salen distintas y no falla nada.
"""

from __future__ import annotations

PALABRAS = 18 + 4 * 256          # P (18) + S0..S3 (4 x 256)
BITS = PALABRAS * 32

#: Tamano de bloque de Blowfish, en bytes.
BLOQUE = 8

#: Claves fuera de este rango no son validas para Blowfish.
CLAVE_MIN = 4
CLAVE_MAX = 56

_M = 0xFFFFFFFF


def _atan_inv(x: int, uno: int) -> int:
    """atan(1/x) en punto fijo con `uno` = 1.0."""
    total = termino = uno // x
    x2 = x * x
    n = 1
    while termino:
        termino //= x2
        n += 2
        if (n // 2) % 2:
            total -= termino // n
        else:
            total += termino // n
    return total


def _digitos_pi(palabras: int = PALABRAS) -> list[int]:
    bits = palabras * 32 + 64
    uno = 1 << bits
    pi = 16 * _atan_inv(5, uno) - 4 * _atan_inv(239, uno)
    frac = pi - 3 * uno
    salida = []
    for i in range(palabras):
        desplazamiento = bits - 32 * (i + 1)
        salida.append((frac >> desplazamiento) & 0xFFFFFFFF)
    return salida


_D = _digitos_pi()
P_INIT = _D[:18]
S_INIT = [_D[18 + 256 * i:18 + 256 * (i + 1)] for i in range(4)]

assert P_INIT[:4] == [0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344], \
    "las constantes de pi no cuadran con Blowfish: %s" % ([hex(v) for v in P_INIT[:4]])


class BlowfishError(ValueError):
    """Clave o bloque con un tamano que Blowfish no admite."""


class Blowfish:
    """Blowfish ECB con la expansion de clave estandar."""

    def __init__(self, clave: bytes) -> None:
        if not CLAVE_MIN <= len(clave) <= CLAVE_MAX:
            raise BlowfishError("clave de %d B fuera de %d..%d"
                                % (len(clave), CLAVE_MIN, CLAVE_MAX))
        self.clave = bytes(clave)
        self.p = list(P_INIT)
        self.s = [list(caja) for caja in S_INIT]
        self._expande(clave)

    def _expande(self, clave: bytes) -> None:
        palabras = []
        for i in range(18):
            valor = 0
            for k in range(4):
                valor = (valor << 8) | clave[(i * 4 + k) % len(clave)]
            palabras.append(valor)
        for i in range(18):
            self.p[i] ^= palabras[i]
        l = r = 0
        for i in range(0, 18, 2):
            l, r = self._cifra(l, r)
            self.p[i], self.p[i + 1] = l, r
        for caja in self.s:
            for i in range(0, 256, 2):
                l, r = self._cifra(l, r)
                caja[i], caja[i + 1] = l, r

    def _f(self, x: int) -> int:
        s = self.s
        return ((((s[0][(x >> 24) & 0xFF] + s[1][(x >> 16) & 0xFF]) & _M)
                 ^ s[2][(x >> 8) & 0xFF]) + s[3][x & 0xFF]) & _M

    def _cifra(self, l: int, r: int) -> tuple[int, int]:
        p = self.p
        for i in range(16):
            l ^= p[i]
            r ^= self._f(l)
            l, r = r, l
        l, r = r, l
        r ^= p[16]
        l ^= p[17]
        return l & _M, r & _M

    def _descifra(self, l: int, r: int) -> tuple[int, int]:
        p = self.p
        for i in range(17, 1, -1):
            l ^= p[i]
            r ^= self._f(l)
            l, r = r, l
        l, r = r, l
        r ^= p[1]
        l ^= p[0]
        return l & _M, r & _M

    def cifra_bloque(self, bloque: bytes) -> bytes:
        """Cifra 8 B."""
        if len(bloque) != BLOQUE:
            raise BlowfishError("bloque de %d B (Blowfish es de %d)"
                                % (len(bloque), BLOQUE))
        l = int.from_bytes(bloque[:4], "big")
        r = int.from_bytes(bloque[4:], "big")
        l, r = self._cifra(l, r)
        return l.to_bytes(4, "big") + r.to_bytes(4, "big")

    def descifra_bloque(self, bloque: bytes) -> bytes:
        """Descifra 8 B."""
        if len(bloque) != BLOQUE:
            raise BlowfishError("bloque de %d B (Blowfish es de %d)"
                                % (len(bloque), BLOQUE))
        l = int.from_bytes(bloque[:4], "big")
        r = int.from_bytes(bloque[4:], "big")
        l, r = self._descifra(l, r)
        return l.to_bytes(4, "big") + r.to_bytes(4, "big")

    def cifra(self, datos: bytes) -> bytes:
        """Cifra `datos` en ECB; la longitud tiene que ser multiplo de 8."""
        if len(datos) % BLOQUE:
            raise BlowfishError("longitud %d no multiplo de %d"
                                % (len(datos), BLOQUE))
        salida = bytearray(len(datos))
        for i in range(0, len(datos), BLOQUE):
            salida[i:i + BLOQUE] = self.cifra_bloque(datos[i:i + BLOQUE])
        return bytes(salida)

    def descifra(self, datos: bytes) -> bytes:
        """Descifra `datos` en ECB; la longitud tiene que ser multiplo de 8."""
        if len(datos) % BLOQUE:
            raise BlowfishError("longitud %d no multiplo de %d"
                                % (len(datos), BLOQUE))
        salida = bytearray(len(datos))
        for i in range(0, len(datos), BLOQUE):
            salida[i:i + BLOQUE] = self.descifra_bloque(datos[i:i + BLOQUE])
        return bytes(salida)

    def cifra_relleno_cero(self, datos: bytes, total: int) -> bytes:
        """Cifra `datos` y rellena con ceros **cifrados** hasta `total` bytes.

        ECB cifra cada bloque igual, asi que el relleno es el cifrado de 8 ceros
        repetido: no hace falta cifrar megas de nada para respetar el tamano de
        la ranura de una pista. `datos` se completa con ceros hasta el bloque de
        8 (es lo que hace el juego: el ultimo frame de 516 B de una pista
        estereo deja 4 B sueltos).
        """
        if total < len(datos) or total % BLOQUE:
            raise BlowfishError("total %d B para %d B de datos (multiplo de %d)"
                                % (total, len(datos), BLOQUE))
        completo = datos + bytes(-len(datos) % BLOQUE)
        cifrado = self.cifra(completo)
        if len(cifrado) == total:
            return cifrado
        cero = self.cifra_bloque(bytes(BLOQUE))
        resto = total - len(cifrado)
        if resto % BLOQUE:
            raise BlowfishError("el relleno (%d B) no es multiplo de %d"
                                % (resto, BLOQUE))
        return cifrado + cero * (resto // BLOQUE)


__all__ = ["BLOQUE", "Blowfish", "BlowfishError", "CLAVE_MAX", "CLAVE_MIN"]

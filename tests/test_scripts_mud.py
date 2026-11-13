"""`tools/scripts_mud.py`: los scripts `LCSK` (tipo `kscl`), con datos sinteticos.

Ningun fixture del juego: el `.fdata`, el `kscl`, el `kidsobjdb` que enlaza y el
`kidstask` se construyen aqui byte a byte con el mismo layout medido en el dump,
para que la suite corra sin el dump.

Los cuatro casos que sostienen los numeros del informe:

* un LCSK cuyo `+0x08` no es su tamano se **detecta**, no se da por bueno;
* la prueba reina es un negativo de verdad: el mismo needle encuentra
  `kids::` en un LCSK que lo lleva (control positivo dentro de la suite);
* el enlace objdb -> script se resuelve por el par `0x15be61ad` y solo por el;
* `kidstask` se recorre mientras los registros casen, y se dice si cubre el fichero.

Y una prueba contra el dump real, que se salta con motivo si no esta.
"""

from __future__ import annotations

import json
import os
import struct
import zlib

import pytest

from pokopia import fdata, paths
from tools import scripts_mud as sm

KSCL = sm.KSCL_KTID
KIDSOBJDB = sm.KIDSOBJDB_KTID
KIDSTASK = sm.KIDSTASK_KTID
G1T = 0xAFBEC60C


# ---------------------------------------------------------------------------
# Constructores
# ---------------------------------------------------------------------------

def lcsk(pool=(), *, firma=b"LCSK2600", recuento=None, tamano=None,
         cadenas_dentro=(), bloques=1) -> bytes:
    """Un LCSK sintetico con las cuatro reglas medidas en los 361 del dump.

    - cabecera de 0x50 B: firma 8 B, u32 tamano (= fichero), u32 recuento;
    - `recuento == bloques de nivel superior + 1` (el ultimo no llega a encadenar);
    - cada bloque empieza por su `u32` de tamano total, firma incluida;
    - el ultimo bloque declara 4 B mas de los que quedan en el fichero.

    `cadenas_dentro` mete cadenas crudas (para el control positivo de la prueba
    reina) y `pool` las mete como piscina `[u32 len][bytes]`.
    `tamano` permite mentir en +0x08 a proposito.
    """
    cuerpo = bytearray()
    for _ in range(bloques):
        cuerpo += struct.pack("<III", 12, 1, 0)
    carga = bytearray(b"".join(c + b"\x00" for c in cadenas_dentro))
    carga += b"".join(struct.pack("<I", len(c)) + c for c in pool)
    while len(carga) % 4:
        carga += b"\x00"
    # el ultimo bloque declara 8 B mas que su carga: 4 del campo + 4 que no estan
    cuerpo += struct.pack("<I", len(carga) + 8) + bytes(carga)
    datos = bytearray(b"\x00" * 0x50)
    datos += bytes(cuerpo)
    n = (bloques + 1) if recuento is None else recuento
    struct.pack_into("<II", datos, 8, (len(datos) if tamano is None else tamano), n)
    datos[0:8] = firma
    return bytes(datos)


def trocear(payload: bytes, tam: int = 0x4000) -> bytes:
    salida = bytearray()
    for inicio in range(0, len(payload), tam):
        comprimido = zlib.compress(payload[inicio:inicio + tam])
        salida += struct.pack("<HQ", len(comprimido), 0)
        salida += comprimido
    return bytes(salida)


def entrada_fdata(payload: bytes, ktid: int = KSCL, name_hash: int = 0x11223344) -> bytes:
    datos = trocear(payload)
    entry_size = fdata.ENTRY_HEADER_SIZE + len(datos)
    return (fdata.IDRK_MAGIC
            + struct.pack("<3Q", entry_size, len(datos), len(payload))
            + struct.pack("<4I", 0, name_hash, ktid, 0)
            + datos)


def escribir_fdata(ruta: str, entradas: list[bytes]) -> str:
    buf = bytearray(fdata.PDRK_MAGIC + struct.pack("<2I", fdata.FDATA_HEADER_SIZE, 0))
    for blob in entradas:
        buf += blob
        if len(buf) % fdata.ENTRY_ALIGN:
            buf += b"\x00" * (fdata.ENTRY_ALIGN - len(buf) % fdata.ENTRY_ALIGN)
    with open(ruta, "wb") as fh:
        fh.write(bytes(buf))
    return ruta


def objdb(registros: list[bytes]) -> bytes:
    """Base `_DOK0000` con los registros dados. Cabecera de 28 B como en el dump."""
    cabecera = (b"_DOK0000" + struct.pack("<III", 28, 24, len(registros))
                + b"\x00" * 8)
    return cabecera + b"".join(registros)


def registro_objdb(ident: int, type_hash: int, pares) -> bytes:
    """Un registro `IDOK0000`; `pares` = lista de (kind, hash, valores)."""
    trios = b"".join(struct.pack("<III", kind, len(valores), clave)
                     for kind, clave, valores in pares)
    carga = b"".join(struct.pack("<I", v) for _, _, valores in pares for v in valores)
    cuerpo = trios + carga
    return (b"IDOK0000"
            + struct.pack("<IIII", 24 + len(cuerpo), ident, type_hash, len(pares))
            + cuerpo)


def kidstask(payload_registros: list[bytes]) -> bytes:
    """`_TGK0000` con la cabecera medida: 32 B y la cadena de registros `INGK0000`."""
    total = 32 + sum(len(r) for r in payload_registros)
    return (b"_TGK0000"
            + struct.pack("<IIIIII", 32, 24, len(payload_registros), 0, 0, total)
            + b"".join(payload_registros))


def registro_ingk(ident: int, relleno: bytes = b"") -> bytes:
    """Un registro `INGK0000`: el u32 de +0x08 es el total del registro, firma incluida."""
    cuerpo = struct.pack("<IIII", ident, 0, 0, 0) + relleno
    while (12 + len(cuerpo)) % 4:
        cuerpo += b"\x00"
    return b"INGK0000" + struct.pack("<I", 12 + len(cuerpo)) + cuerpo


def romfs(tmp_path, entradas_por_fichero: dict[str, list[bytes]]):
    """Carpeta con los `.fdata` dados, con la forma del romfs real."""
    base = tmp_path / "romfs"
    (base / "motor_asset_re" / "KIDS_PLATFORM_OUNCE").mkdir(parents=True, exist_ok=True)
    for nombre, entradas in entradas_por_fichero.items():
        escribir_fdata(str(base / "motor_asset_re" / "KIDS_PLATFORM_OUNCE" / nombre),
                       entradas)
    return str(base)


# ---------------------------------------------------------------------------
# Formato del LCSK
# ---------------------------------------------------------------------------

def test_cabecera_campos_medidos():
    datos = lcsk(pool=[b"0500_prt_x"], recuento=7)
    cab = sm.cabecera_lcsk(datos)
    assert cab["firma"] == "LCSK2600"
    assert cab["version"] == "2600"
    assert cab["tamano_declarado"] == len(datos)
    assert cab["tamano_casa"] is True
    assert cab["recuento"] == 7


def test_cabecera_que_miente_se_ve():
    """Si `+0x08` no es el tamano, hay que verlo: es la senal de payload truncado."""
    datos = lcsk(tamano=9999)
    cab = sm.cabecera_lcsk(datos)
    assert cab["tamano_casa"] is False
    assert cab["tamano_declarado"] == 9999
    assert cab["tamano_real"] == len(datos)


def test_cabecera_corta_falla():
    with pytest.raises(ValueError):
        sm.cabecera_lcsk(b"LCSK")


def test_piscina_de_cadenas_es_contigua():
    """La piscina medida es `[u32 len][bytes]` sin relleno entre cadenas."""
    pool = [b"0000_prt_square_w", b"0500_prt_okurimono_BG_0", b"Null_All"]
    datos = lcsk(pool=pool)
    tramo = sm.piscina_cadenas(datos)
    assert tramo, "no se encontro la piscina"
    assert len(tramo) >= 2
    # cada campo len va seguido de exactamente sus bytes y la siguiente empieza justo despues
    for campo, ln, inicio in tramo:
        assert datos[inicio:inicio + ln] in pool
    for (_, ln, inicio), (siguiente, _, _) in zip(tramo, tramo[1:]):
        assert inicio + ln == siguiente


def test_bloques_superiores_avanzan_y_no_se_pasan():
    datos = lcsk(pool=[b"abc"])
    inicios = sm.bloques_superiores(datos)
    assert inicios[0] == sm.LCSK_CABECERA_FIJA
    assert inicios == sorted(inicios)
    assert all(a < b for a, b in zip(inicios, inicios[1:]))
    assert max(inicios) <= len(datos)


def test_cadenas_solo_ascii_imprimible():
    datos = lcsk(cadenas_dentro=[b"hola_mundo"], pool=[b"otra_cosa"])
    textos = [c for _, c in sm.cadenas_lcsk(datos)]
    assert b"hola_mundo" in textos
    assert b"otra_cosa" in textos


# ---------------------------------------------------------------------------
# Prueba reina, con su control positivo
# ---------------------------------------------------------------------------

def test_rey_negativo_cuando_no_hay_nombres(tmp_path):
    base = romfs(tmp_path, {"0xaa.fdata": [entrada_fdata(lcsk(pool=[b"0500_prt_x"]))]})
    doc = sm.rey(base)
    assert doc["kscl"] == 1
    assert doc["kscl_con_agujas"] == 0


def test_rey_positivo_cuando_el_script_lleva_el_nombre(tmp_path):
    """El control positivo: si el needle no cazara esto, el 0 del dump no valdria."""
    dentro = [b"kids::placeable::level::ExecuteBehaviorByObjectHash"]
    base = romfs(tmp_path, {"0xaa.fdata": [entrada_fdata(lcsk(cadenas_dentro=dentro))]})
    doc = sm.rey(base)
    assert doc["kscl_con_agujas"] == 1
    assert doc["detalle"][0]["agujas"]["kids::"] == 1


def test_rey_control_positivo_sobre_rodata(tmp_path):
    rodata = tmp_path / "rodata.bin"
    rodata.write_bytes(b"\x00" * 100 + b"mud::debug::assert\x00kids::placeable::Attach\x00")
    base = romfs(tmp_path, {"0xaa.fdata": [entrada_fdata(lcsk())]})
    doc = sm.rey(base, str(rodata))
    assert doc["control_positivo"]["ocurrencias"]["kids::"] == 1
    assert doc["control_positivo"]["ocurrencias"]["mud::"] == 1
    assert doc["kscl_con_agujas"] == 0


# ---------------------------------------------------------------------------
# Recuento y enlace
# ---------------------------------------------------------------------------

def test_count_cuenta_por_fichero_y_no_confunde_un_falso_positivo(tmp_path, capsys):
    bueno = lcsk(pool=[b"x_1"])
    falso = b"ASRS" + b"\x00" * 8 + b"\x01LCSK\x02" + b"\x00" * 8
    base = romfs(tmp_path, {
        "0xa.fdata": [entrada_fdata(bueno, name_hash=1), entrada_fdata(bueno, name_hash=2)],
        "0xb.fdata": [entrada_fdata(falso, ktid=0xBBD39F2D, name_hash=3)],
    })
    assert sm.main(["count", base, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["por_fichero"] == {"0xa.fdata": 2, "0xb.fdata": 1}
    assert doc["por_tipo"] == {"kscl": 2, "srsa": 1}
    assert doc["con_firma"] == 3
    # el que no empieza por LCSK queda marcado aparte, no se cuenta como script
    assert [f["name_hash"] for f in doc["firma_fuera_del_offset_0"]] == ["0x00000003"]


def test_count_el_falso_positivo_sale_marcado(tmp_path, capsys):
    falso = b"ASRS" + b"\x00" * 8 + b"\x01LCSK\x02"
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(falso, ktid=0xBBD39F2D, name_hash=3)]})
    assert sm.main(["count", base]) == 0
    texto = capsys.readouterr().out
    assert "FUERA del offset 0" in texto


def test_refs_resuelve_el_par_del_script(tmp_path):
    script = 0xDEADBEEF
    base = romfs(tmp_path, {
        "0xa.fdata": [entrada_fdata(lcsk(pool=[b"x"]), name_hash=script)],
    })
    # la objdb va en su propio fdata
    escribir_fdata(
        os.path.join(base, "motor_asset_re", "KIDS_PLATFORM_OUNCE", "0xb.fdata"),
        [entrada_fdata(
            objdb([registro_objdb(1, sm.REGISTRO_ESCENA,
                                  [(5, sm.PAR_SCRIPT, [script]),
                                   (5, 0x11111111, [0x22222222])])]),
            ktid=KIDSOBJDB, name_hash=0xABCDEF01)])
    doc = sm.refs(base)
    assert doc["enlaces"] == 1
    assert doc["kscl_enlazados"] == 1
    assert doc["kscl_sin_enlace"] == []
    assert doc["detalle"][0]["par"] == "0x15be61ad"
    assert doc["detalle"][0]["kscl"] == "0xdeadbeef"
    assert doc["type_hash_de_registro"] == {"0x63336873": 1}


def test_refs_no_confunde_otro_hash_con_un_script(tmp_path):
    base = romfs(tmp_path, {
        "0xa.fdata": [entrada_fdata(lcsk(), name_hash=0xAAAA0001)],
    })
    escribir_fdata(
        os.path.join(base, "motor_asset_re", "KIDS_PLATFORM_OUNCE", "0xb.fdata"),
        [entrada_fdata(objdb([registro_objdb(1, sm.REGISTRO_ESCENA,
                                             [(5, sm.PAR_SCRIPT, [0xAAAA0002])])]),
                       ktid=KIDSOBJDB, name_hash=0xABCDEF01)])
    doc = sm.refs(base)
    assert doc["enlaces"] == 0
    assert doc["kscl_sin_enlace"] == ["0xaaaa0001"]


# ---------------------------------------------------------------------------
# kidstask
# ---------------------------------------------------------------------------

def test_kidstask_recorre_la_cadena_y_dice_si_cubre(tmp_path):
    base = romfs(tmp_path, {
        "0xa.fdata": [entrada_fdata(kidstask([registro_ingk(1),
                                              registro_ingk(2, b"\x11" * 8)]),
                                    ktid=KIDSTASK, name_hash=0xBD13A52E)],
    })
    doc = sm.kidstask(base)
    assert doc["cabecera"]["firma"] == "_TGK0000"
    assert doc["cabecera"]["cabecera_tamano"] == 32
    assert doc["cabecera"]["cabecera_de_registro"] == 24
    assert doc["cabecera"]["recuento"] == 2
    assert len(doc["registros"]) == 2
    assert doc["cubre_el_fichero"] is True
    assert doc["recuento_casa"] is True


def test_kidstask_marcado_cuando_no_cubre(tmp_path):
    """Con basura detras del ultimo registro, `cubre` es False y no se inventa nada."""
    datos = kidstask([registro_ingk(1)]) + b"\x00" * 8
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(datos, ktid=KIDSTASK,
                                                        name_hash=0xBD13A52E)]})
    doc = sm.kidstask(base)
    assert doc["cubre_el_fichero"] is False


def test_kidstask_se_niega_si_hay_mas_de_una(tmp_path):
    """Dos entradas `kidstask` no se resuelven a la callada: el dump tiene una."""
    base = romfs(tmp_path, {"0xa.fdata": [
        entrada_fdata(kidstask([registro_ingk(1)]), ktid=KIDSTASK, name_hash=1),
        entrada_fdata(kidstask([registro_ingk(2)]), ktid=KIDSTASK, name_hash=2)]})
    with pytest.raises(SystemExit) as exc:
        sm.kidstask(base)
    assert "mas de una entrada kidstask" in str(exc.value)


# ---------------------------------------------------------------------------
# Forma de las cadenas
# ---------------------------------------------------------------------------

def test_cadenas_clasifica_por_forma_sin_volcar_contenido(tmp_path, capsys):
    """Las cuatro formas se distinguen y el `::` de relleno no pasa por binding."""
    script = lcsk(pool=[b"0000_prt_x", b"hide", b"ABC_1", b";:::::"])
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(script, name_hash=0xCAFEBABE)]})
    doc = sm.cadenas_por_forma(base)
    assert doc["kscl"] == 1
    assert doc["por_forma"]["id_asset"]["cadenas"] == 1
    assert doc["por_forma"]["clip"]["cadenas"] >= 1
    assert doc["por_forma"]["otro"]["cadenas"] >= 1
    assert doc["por_forma"]["ruido"]["cadenas"] >= 1
    assert sum(d["cadenas"] for d in doc["por_forma"].values()) == doc["cadenas"]
    assert len(doc["con_dos_puntos"]) == 1
    assert doc["con_dos_puntos"][0]["name_hash"] == "0xcafebabe"

    assert sm.main(["cadenas", base]) == 0
    salida = capsys.readouterr().out
    assert "id_asset" in salida and "ruido" in salida
    # no vuelca el contenido de las cadenas
    assert "0000_prt_x" not in salida and "hide" not in salida


# ---------------------------------------------------------------------------
# Contenedores y firmas
# ---------------------------------------------------------------------------

def test_contenedores_reparte_entradas_y_scripts(tmp_path):
    """Los `.fdata` de un `MountPoint_N` cuentan en su montaje, no en la raiz."""
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(lcsk(), name_hash=1),
                                          entrada_fdata(lcsk(), name_hash=2)]})
    sub = os.path.join(base, "motor_asset_re", "KIDS_PLATFORM_OUNCE", "MountPoint_1")
    os.makedirs(sub, exist_ok=True)
    escribir_fdata(os.path.join(sub, "0xb.fdata"), [entrada_fdata(lcsk(), name_hash=3)])

    doc = sm.contenedores(base)
    assert doc["ficheros"] == 2
    assert doc["entradas"] == 3
    assert doc["scripts"] == 3
    assert doc["por_contenedor"]["."]["scripts"] == 2
    assert doc["por_contenedor"]["MountPoint_1"]["scripts"] == 1
    assert doc["por_contenedor"]["MountPoint_1"]["detalle"][0]["fichero"].endswith(
        "MountPoint_1/0xb.fdata")
    assert sm.main(["contenedores", base]) == 0


def test_magics_no_confunde_el_layout_publico_con_estos_ficheros(tmp_path):
    """Mismo magic `LCSK`, payload distinto: el `KSLT` del layout se ve y se cuenta."""
    layout = b"LCSK2600" + struct.pack("<II", 24, 1) + b"KSLT" + b"\x00" * 8
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(lcsk(), name_hash=1),
                                          entrada_fdata(layout, name_hash=2)]})
    doc = sm.magics(base)
    assert doc["ficheros"] == 2
    assert doc["firma_en_0x00"] == {"LCSK2600": 2}
    assert doc["firmas_conocidas_dentro"]["KSLT"] == 1
    # solo el LCSK de verdad aporta bloques de nivel superior
    assert doc["firma_de_bloque"] == {"(sin firma ascii)": {"bloques": 1, "ficheros": 1}}
    assert sm.main(["magics", base]) == 0


def test_magics_de_un_tipo_sin_entradas_falla(tmp_path):
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(lcsk(), name_hash=1)]})
    with pytest.raises(SystemExit) as exc:
        sm.main(["magics", base, "--tipo", "no-existe"])
    assert "no hay entradas de tipo" in str(exc.value)


# ---------------------------------------------------------------------------
# Anatomia, list y dump por CLI
# ---------------------------------------------------------------------------

def test_anatomia_invariantes(tmp_path):
    pequeno = lcsk(pool=[b"a"])
    grande = lcsk(pool=[b"b" * 20, b"c" * 30])
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(pequeno, name_hash=1),
                                          entrada_fdata(grande, name_hash=2)]})
    doc = sm.anatomias(base)
    assert doc["invariantes"]["entradas_kscl"] == 2
    assert doc["invariantes"]["tamano_casa"] == 2
    assert doc["min"]["bytes"] == len(pequeno)
    assert doc["max"]["bytes"] == len(grande)


def test_list_y_dump_por_cli(tmp_path, capsys):
    script = lcsk()
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(script, name_hash=0xCAFEBABE)]})
    assert sm.main(["list", base]) == 0
    salida = capsys.readouterr().out
    assert "0xcafebabe" in salida and "LCSK2600" in salida

    assert sm.main(["dump", base, "0xcafebabe"]) == 0
    volcado = capsys.readouterr().out
    assert "LCSK2600" in volcado and "cabecera" in volcado
    assert "tamano=%d" % len(script) in volcado


def test_dump_de_un_hash_que_no_existe_sale_con_error(tmp_path):
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(lcsk())]})
    with pytest.raises(SystemExit):
        sm.buscar_entrada(base, 0x12345678)


def test_selftest_en_verde(tmp_path, capsys):
    base = romfs(tmp_path, {
        "0xa.fdata": [entrada_fdata(lcsk(pool=[b"x"]), name_hash=1),
                      entrada_fdata(kidstask([registro_ingk(1)]), ktid=KIDSTASK,
                                    name_hash=0xBD13A52E)],
    })
    assert sm.main(["selftest", base]) == 0
    assert "todo cuadra" in capsys.readouterr().out


def test_nada_se_escribe_en_el_romfs(tmp_path):
    """El dump es de solo lectura: tras los comandos, los bytes son los mismos."""
    base = romfs(tmp_path, {"0xa.fdata": [entrada_fdata(lcsk(), name_hash=1)]})
    ruta = os.path.join(base, "motor_asset_re", "KIDS_PLATFORM_OUNCE", "0xa.fdata")
    antes = paths.md5_file(ruta)
    sm.main(["count", base])
    sm.main(["list", base])
    sm.main(["anatomia", base])
    sm.main(["rey", base])
    assert paths.md5_file(ruta) == antes


# ---------------------------------------------------------------------------
# Contra el dump real (se salta con motivo si no esta)
# ---------------------------------------------------------------------------

ROMFS_REAL = paths.configured_romfs()
HAY_DUMP = os.path.isdir(ROMFS_REAL) and any(
    nombre.endswith(".fdata")
    for _, _, ficheros in os.walk(ROMFS_REAL) for nombre in ficheros)


@pytest.fixture(scope="module")
def dump_romfs() -> str:
    if not HAY_DUMP:
        pytest.skip("sin dump del juego (exporta PKP_ROMFS)")
    return ROMFS_REAL

def test_dump_real_lcsk_361(dump_romfs):
    doc = sm.anatomias(dump_romfs)
    inv = doc["invariantes"]
    assert inv["entradas_kscl"] == 361
    assert inv["tamano_casa"] == 361
    assert inv["firmas"] == {"LCSK2600": 360, "LCSK1600": 1}
    assert inv["recuentos"] == {5: 28, 6: 14, 7: 319}
    assert inv["recuento_igual_bloques_mas_uno"] == 361
    assert inv["ultimo_bloque_4_de_mas"] == 361
    assert (inv["min_bytes"], inv["max_bytes"]) == (484, 109680)
    assert inv["suma_bytes"] == 3742924


def test_dump_real_rey_sin_nombres(dump_romfs):
    doc = sm.rey(dump_romfs)
    assert doc["kscl"] == 361
    assert doc["kscl_con_agujas"] == 0


def test_dump_real_kidstask(dump_romfs):
    doc = sm.kidstask(dump_romfs)
    assert doc["bytes"] == 3868
    assert doc["cabecera"]["firma"] == "_TGK0000"
    assert doc["cabecera"]["recuento"] == 33
    assert doc["cubre_el_fichero"] is True


def test_dump_real_enlaces(dump_romfs):
    doc = sm.refs(dump_romfs)
    assert doc["kscl"] == 361
    assert doc["enlaces"] == 361
    assert doc["kscl_enlazados"] == 361
    assert doc["kscl_sin_enlace"] == []
    assert doc["type_hash_de_registro"] == {"0x63336873": 361}
    assert doc["par_del_script"] == {"0x15be61ad": 361}


def test_dump_real_contenedores(dump_romfs):
    """Los 361 se reparten 351 / 5 / 5 y en cada montaje los lleva un solo fichero."""
    doc = sm.contenedores(dump_romfs)
    assert doc["ficheros"] == 24
    assert doc["entradas"] == 79710
    assert doc["scripts"] == 361
    assert doc["por_contenedor"]["."]["scripts"] == 351
    assert doc["por_contenedor"]["MountPoint_1"]["scripts"] == 5
    assert doc["por_contenedor"]["MountPoint_2"]["scripts"] == 5
    assert len(doc["por_contenedor"]["MountPoint_1"]["detalle"]) == 1
    assert len(doc["por_contenedor"]["MountPoint_2"]["detalle"]) == 1


def test_dump_real_magics_sin_kslt(dump_romfs):
    """Misma firma que el KSCL de layout publico, pero sin su subchunk `KSLT`."""
    doc = sm.magics(dump_romfs)
    assert doc["ficheros"] == 361
    assert doc["firmas_conocidas_dentro"]["KSLT"] == 0
    assert doc["firmas_conocidas_dentro"]["GSTK"] == 0
    assert doc["bloques_de_nivel_superior"] == 2096
    assert list(doc["firma_de_bloque"]) == ["(sin firma ascii)"]

"""Ida y vuelta del contenedor: la capa de formato sigue siendo identica.

Los tests con el dump real se saltan si no esta; el barrido completo de las
12.298 entradas (recomprimir todo) se activa con PKP_FULL=1.
"""

from __future__ import annotations

import hashlib
import os
import struct

import pytest

from pokopia import paths
from pokopia.container import (
    DEFAULT_BLOCK_SIZE,
    ENTRY_ALIGN,
    StockZlibCompressor,
    compare_payloads,
    entry_block_size,
    get_compressor,
    index_to_bytes,
    pack_entry,
    read_container,
    read_index,
    roundtrip,
    unpack_entry,
    verify,
    write_container,
)
from tests.helpers import make_container, read_payload, records_payload, records_spec

#: RomFS configurado (`PKP_ROMFS` o `./romfs`): los tests con dump real se saltan
#: si no esta. El kit ya no lleva la ruta de ninguna maquina dentro.
ROM = paths.configured_romfs()
IDX = os.path.join(ROM, paths.IDX_NAME)
BIN = os.path.join(ROM, paths.BIN_NAME)
HAY_DUMP = os.path.isfile(IDX) and os.path.isfile(BIN)
necesita_dump = pytest.mark.skipif(not HAY_DUMP, reason="sin dump del juego")


def _compresor_stock():
    comp = get_compressor("auto")
    if isinstance(comp, StockZlibCompressor):
        return comp
    return None


# --------------------------------------------------------------------------
# Sinteticos: no necesitan el dump
# --------------------------------------------------------------------------

def test_ida_y_vuelta_sintetica(tmp_path):
    payload = records_payload({0: b"\x11\x22", 3: b"\x33" * 20})
    cont = make_container(str(tmp_path / "c"), {0: payload, 1: b"x" * 5000})
    entries, data = read_container(cont.idx, cont.bin)
    assert len(entries) == 2
    assert unpack_entry(data, entries[0]) == payload
    assert unpack_entry(data, entries[1]) == b"x" * 5000
    assert verify(cont.idx, cont.bin, verbose=False)["problems"] == []


def test_write_container_sin_cambios_es_identico(tmp_path):
    payload = records_payload({1: b"\x07" * 8})
    cont = make_container(str(tmp_path / "c"), {0: payload, 1: b"y" * 300})
    out_idx = str(tmp_path / "o.IDX")
    out_bin = str(tmp_path / "o.BIN")
    write_container(cont.idx, cont.bin, out_idx, out_bin, replace={})
    assert open(cont.idx, "rb").read() == open(out_idx, "rb").read()
    assert open(cont.bin, "rb").read() == open(out_bin, "rb").read()


def test_write_container_solo_cambia_la_entrada_sustituida(tmp_path):
    cont = make_container(str(tmp_path / "c"), {0: b"a" * 100, 1: b"b" * 200,
                                                2: b"c" * 50})
    nuevo = b"Z" * 200
    out_idx = str(tmp_path / "o.IDX")
    out_bin = str(tmp_path / "o.BIN")
    write_container(cont.idx, cont.bin, out_idx, out_bin, replace={1: nuevo})
    comp = compare_payloads(cont.idx, cont.bin, out_idx, out_bin)
    assert comp["errors"] == []
    assert comp["different"] == [1]
    assert comp["different_count"] == 1
    assert comp["identical"] == 2
    assert read_payload(paths.Container(str(tmp_path), out_idx, out_bin), 1) == nuevo


# --------------------------------------------------------------------------
# Contenedor real (solo lectura)
# --------------------------------------------------------------------------

@necesita_dump
def test_indice_del_dump():
    entries = read_index(IDX)
    assert len(entries) == 12298
    assert sum(1 for e in entries if e.flag == 0) == 4169
    assert sum(1 for e in entries if e.flag == 1) == 8129
    assert sum(e.raw_size for e in entries) == 548327864
    assert sum(e.packed_size for e in entries) == 246615606


@necesita_dump
def test_verify_sin_problemas():
    res = verify(IDX, BIN, verbose=False)
    assert res["problems"] == []
    assert res["blocks_comp"] == 8834
    assert res["blocks_raw"] == 19


@necesita_dump
def test_reempaquetado_de_la_muestra_es_byte_a_byte():
    comp = _compresor_stock()
    if comp is None:
        pytest.skip("hace falta una zlib stock (identidad byte a byte)")
    entries, bin_data = read_container(IDX, BIN)
    muestra = [0, 1, 40, 41, 42, 44, 983, 4645, 4646, 4650, 5589, 5879,
               10022, 10220, 11596, 12297]
    for i in muestra:
        ent = entries[i]
        blob = unpack_entry(bin_data, ent, index=i)
        packed, flag = pack_entry(blob, flag=ent.flag,
                                  block_size=entry_block_size(bin_data, ent),
                                  compressor=comp,
                                  empty_header=bool(ent.raw_size == 0 and ent.packed_size > 0))
        assert flag == ent.flag, "#%d cambia de flag" % i
        assert packed == bin_data[ent.offset:ent.offset + ent.packed_size], \
            "#%d no reempaqueta identica" % i


@necesita_dump
@pytest.mark.skipif(not os.environ.get("PKP_FULL"),
                    reason="barrido completo: define PKP_FULL=1")
def test_roundtrip_completo_12298(tmp_path):
    comp = _compresor_stock()
    if comp is None:
        pytest.skip("hace falta una zlib stock (identidad byte a byte)")
    res = roundtrip(IDX,
                    BIN,
                    str(tmp_path / "o.IDX"), str(tmp_path / "o.BIN"),
                    comp, verbose=False)
    assert res["entries"] == 12298
    assert res["distintas"] == 0
    assert res["entradas_reempaquetadas_identicas"] == 12298
    assert res["bin_identico"] and res["idx_identico"]
    assert hashlib.md5(open(str(tmp_path / "o.BIN"), "rb").read()).hexdigest() == \
        "358a672d506ce2b0399149ede64a6760"

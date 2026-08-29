#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import struct
import zlib
from pathlib import Path

KNOWN0_BITS = 0x3F71970A
KNOWN0 = struct.unpack('<f', struct.pack('<I', KNOWN0_BITS))[0]
KNOWN1 = -3.5759213
TENSOR_FLOAT_OFFSETS = [0, 53261, 110101, 166941, 172716]


def find_model(exe: Path) -> Path:
    hits = list(exe.parent.rglob('eXtremeGammon v2.dat'))
    if not hits:
        raise RuntimeError('official v2.dat not found')
    return hits[0]


def decode_streams(data: bytes):
    streams = []
    rest = data
    base = 0
    while rest:
        if len(rest) < 2 or rest[0] != 0x78:
            break
        d = zlib.decompressobj()
        try:
            out = d.decompress(rest) + d.flush()
        except zlib.error:
            break
        consumed = len(rest) - len(d.unused_data)
        if consumed <= 0:
            break
        streams.append((base, consumed, out))
        base += consumed
        rest = d.unused_data
    return streams, base, rest


def scan_pair(blob: bytes):
    pat = struct.pack('<I', KNOWN0_BITS)
    hits = []
    p = 0
    while True:
        j = blob.find(pat, p)
        if j < 0:
            break
        if j + 8 <= len(blob):
            v1 = struct.unpack_from('<f', blob, j + 4)[0]
            if math.isfinite(v1) and abs(v1 - KNOWN1) <= 2e-4:
                hits.append((j, v1))
        p = j + 1
    return hits


def floats_at(blob: bytes, base: int, foff: int, n=8):
    off = base + 4 * foff
    if off < 0 or off + 4*n > len(blob):
        return None
    return struct.unpack_from('<' + 'f'*n, blob, off)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xg-exe', type=Path, required=True)
    ap.add_argument('--outdir', type=Path, required=True)
    a = ap.parse_args()
    a.outdir.mkdir(parents=True, exist_ok=True)

    model = find_model(a.xg_exe)
    data = model.read_bytes()
    streams, consumed, trailing = decode_streams(data)

    lines = [
        f'MODEL={model}',
        f'COMPRESSED_SIZE={len(data)}',
        f'COMPRESSED_SHA256={hashlib.sha256(data).hexdigest()}',
        f'ZLIB_STREAMS={len(streams)}',
        f'ZLIB_CONSUMED={consumed}',
        f'TRAILING_SIZE={len(trailing)}',
    ]
    map_lines = ['stream\tfile_offset\tcompressed_bytes\tdecoded_bytes\tdecoded_sha256\tknown_pair_hits']
    pair_lines = ['stream\tdecoded_offset\tv0\tv1']

    for si, (file_off, clen, out) in enumerate(streams):
        hits = scan_pair(out)
        map_lines.append(
            f'{si}\t{file_off}\t{clen}\t{len(out)}\t{hashlib.sha256(out).hexdigest()}\t{len(hits)}'
        )
        lines.append(f'STREAM_{si}_DECODED_SIZE={len(out)}')
        lines.append(f'STREAM_{si}_PAIR_HITS={len(hits)}')
        for off, v1 in hits[:20]:
            pair_lines.append(f'{si}\t{off}\t{KNOWN0:.9g}\t{v1:.9g}')

        # If the proven first pair is present, treat that position as the
        # historical decoded float-payload base and inspect all inferred tensor starts.
        if hits:
            base = hits[0][0]
            tensor_lines = ['tensor\tfloat_offset\tbyte_offset\tvalues']
            for ti, foff in enumerate(TENSOR_FLOAT_OFFSETS):
                vals = floats_at(out, base, foff)
                if vals is None:
                    tensor_lines.append(f'{ti}\t{foff}\t{base+4*foff}\tOUT_OF_RANGE')
                else:
                    tensor_lines.append(
                        f'{ti}\t{foff}\t{base+4*foff}\t' + ','.join(f'{v:.9g}' for v in vals)
                    )
            (a.outdir / f'r64-stream-{si}-tensor-starts.tsv').write_text('\n'.join(tensor_lines)+'\n', encoding='utf-8')

    (a.outdir/'r64-summary.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (a.outdir/'r64-stream-map.tsv').write_text('\n'.join(map_lines)+'\n', encoding='utf-8')
    (a.outdir/'r64-known-pair-hits.tsv').write_text('\n'.join(pair_lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))
    print('\n'.join(map_lines))
    print('\n'.join(pair_lines[:30]))
    return 0 if streams else 2


if __name__ == '__main__':
    raise SystemExit(main())

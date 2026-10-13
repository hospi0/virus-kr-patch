# -*- coding: utf-8 -*-
r"""Duck TrueMotion 1 AVI 읽기 — RIFF 덩어리·프레임(00dc)·소리(01wb)·idx1, 프레임 머리 풀기(ffmpeg truemotion1.c 와 같은 규칙).
  python tools/tm1avi.py <파일.AVI>   → 머리 요약
"""
import struct, sys, collections


def chunks(b, off, end):
    while off + 8 <= end:
        cid = b[off:off + 4]; sz, = struct.unpack_from('<I', b, off + 4)
        yield cid, off, sz
        off += 8 + sz + (sz & 1)


def walk(b):
    """[(fourcc, 데이터 오프셋, 크기, 경로)] — LIST 는 안으로"""
    out = []
    def rec(off, end, path):
        for cid, o, sz in chunks(b, off, end):
            if cid in (b'LIST', b'RIFF'):
                typ = b[o + 8:o + 12]
                rec(o + 12, o + 8 + sz, path + [typ])
            else:
                out.append((cid, o + 8, sz, tuple(path)))
    rec(0, len(b), [])
    return out


def header(fr):
    """프레임 머리 → dict (ffmpeg truemotion1_decode_header)"""
    hs = ((fr[0] >> 5) | (fr[0] << 3)) & 0x7f
    hb = bytes(fr[i] ^ fr[i + 1] for i in range(1, hs))
    h = dict(header_size=hs, compression=hb[0], deltaset=hb[1], vectable=hb[2],
             ysize=struct.unpack_from('<H', hb, 3)[0], xsize=struct.unpack_from('<H', hb, 5)[0],
             checksum=struct.unpack_from('<H', hb, 7)[0], version=hb[9] if len(hb) > 9 else 0,
             header_type=hb[10] if len(hb) > 10 else 0, flags=hb[11] if len(hb) > 11 else 0,
             control=hb[12] if len(hb) > 12 else 0, raw=hb)
    return h


def main():
    b = open(sys.argv[1], 'rb').read()
    ch = walk(b)
    c = collections.Counter(x[0] for x in ch)
    print(dict(c))
    vids = [x for x in ch if x[0][2:] in (b'dc', b'db')]
    hs = collections.Counter()
    for k, (cid, o, sz, p) in enumerate(vids):
        if sz == 0:
            hs['(빈 프레임)'] += 1; continue
        h = header(b[o:o + sz])
        key = (h['header_size'], h['compression'], h['deltaset'], h['vectable'], h['xsize'], h['ysize'], h['version'], h['header_type'], h['flags'])
        hs[key] += 1
        if k < 3:
            print(k, sz, {kk: v for kk, v in h.items() if kk != 'raw'}, h['raw'].hex())
    print('(머리크기, 압축, 델타, 벡터표, 가로, 세로, 버전, 머리종류, 플래그) 분포:')
    for k, v in hs.most_common():
        print(' ', k, v)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
r"""RetroArch 압축 세이브 스테이트(#RZIPv1#) 풀기.
  머리 = «#RZIPv\x01#» 8B + u32 덩어리 크기 + u64 전체 크기, 그 뒤 [u32 압축 크기 + zlib] 반복.
  python tools/rzip.py <in.state> <out.bin>
"""
import struct, sys, zlib


def unpack(b):
    assert b[:8] == b'#RZIPv\x01#', '머리 아님'
    csz, total = struct.unpack_from('<IQ', b, 8)
    off = 20; out = bytearray()
    while off < len(b):
        n, = struct.unpack_from('<I', b, off); off += 4
        out += zlib.decompress(b[off:off + n]); off += n
    assert len(out) == total, (len(out), total)
    return bytes(out)


if __name__ == '__main__':
    d = unpack(open(sys.argv[1], 'rb').read())
    open(sys.argv[2], 'wb').write(d)
    print(len(d))

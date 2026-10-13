# -*- coding: utf-8 -*-
r"""메드나펜(새턴) 스테이트(풀린 것) → 구역·변수 목록, 변수 꺼내기.
  구역 = 이름 32B + u32 크기, 그 안 변수 = 길이 바이트 + 이름 + u32 크기 + 데이터.
  ★WorkRAM·VRAM 은 u16 호스트(리틀) 순서 → swap16() 으로 뒤집어야 원래 바이트.
  python tools/mdfnstate.py <state.bin> [구역/변수 …]   (인수 없으면 목록)
"""
import struct, sys


def sections(d):
    off = 0x20 if d[:8] == b'MDFNSVST' else d.find(b'MDFNSVST') + 0x20
    out = {}
    while off + 36 <= len(d):
        name = d[off:off + 32].split(b'\0')[0].decode('latin1')
        size, = struct.unpack_from('<I', d, off + 32)
        if not name or size > len(d):
            break
        body = d[off + 36:off + 36 + size]
        vars_ = {}; p = 0
        while p < len(body):
            ln = body[p]; vn = body[p + 1:p + 1 + ln].decode('latin1', 'replace'); p += 1 + ln
            vs, = struct.unpack_from('<I', body, p); p += 4
            vars_[vn] = body[p:p + vs]; p += vs
        out[name] = vars_
        off += 36 + size
    return out


def swap16(b):
    a = bytearray(b); a[0::2], a[1::2] = b[1::2], b[0::2]; return bytes(a)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    d = open(sys.argv[1], 'rb').read()
    s = sections(d)
    for k, v in s.items():
        print(k, ' '.join('%s(%d)' % (n, len(x)) for n, x in list(v.items())[:40]))

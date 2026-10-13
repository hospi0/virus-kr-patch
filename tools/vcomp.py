# -*- coding: utf-8 -*-
r"""VIRUS 압축(1ST_READ 0x06033E44 해제기) — 머리 = [방식 1B][풀린 크기 3B BE] + 자료.
  방식 0 = 그대로 · 방식 1 = LZSS: 깃발 바이트 LSB 먼저, 1 = 글자 하나, 0 = 참조 2B [b1 b2]:
  길이 = (b1>>4)+2, 고리 위치 = ((b1&15)<<8)|b2 (4KB 고리, 쓰기 위치 0 부터, 처음 내용 0).
  방식 2‥4 ⏳미해독.
  묶음 파일(SKANS 등) = [u32 크기][자료] 반복 → entries()
"""
import struct


def entries(b):
    out = []; p = 0
    while p + 4 <= len(b):
        n, = struct.unpack_from('>I', b, p)
        if n == 0 or p + 4 + n > len(b):
            break
        out.append(b[p + 4:p + 4 + n]); p += 4 + n
    return out


def decompress(d):
    meth = d[0]; size = int.from_bytes(d[1:4], 'big'); src = d[4:]
    if meth == 0:
        return src[:size]
    assert meth == 1, '방식 %d 미해독' % meth
    ring = bytearray(4096); w = 0; out = bytearray(); i = 0
    while len(out) < size:
        flags = src[i]; i += 1
        for k in range(8):
            if len(out) >= size:
                break
            if flags >> k & 1:
                c = src[i]; i += 1
                out.append(c); ring[w] = c; w = (w + 1) & 0xFFF
            else:
                b1, b2 = src[i], src[i + 1]; i += 2
                n = (b1 >> 4) + 2; r = ((b1 & 15) << 8) | b2
                for _ in range(n):
                    c = ring[r]; r = (r + 1) & 0xFFF
                    out.append(c); ring[w] = c; w = (w + 1) & 0xFFF
    return bytes(out[:size])


def compress(data):
    """방식 1 LZSS 압축(탐욕, 해시 사슬). 고리 쓰기 위치 0 부터·처음 내용 0 — decompress 와 왕복 일치."""
    out = bytearray([1]) + len(data).to_bytes(3, 'big')
    n = len(data); i = 0
    heads = {}
    while i < n:
        flag_pos = len(out); out.append(0); flags = 0
        for k in range(8):
            if i >= n:
                break
            best_len = 0; best_pos = 0
            key = data[i:i + 2]
            for j in reversed(heads.get(key, [])[-64:]):
                if i - j > 4096 - 18:
                    break
                L = 0
                while L < 17 and i + L < n and data[j + L] == data[i + L]:
                    L += 1
                if L > best_len:
                    best_len, best_pos = L, j
                    if L == 17:
                        break
            if best_len >= 2:
                r = best_pos & 0xFFF
                out += bytes([((best_len - 2) << 4) | (r >> 8), r & 0xFF])
                for t in range(best_len):
                    heads.setdefault(data[i + t:i + t + 2], []).append(i + t)
                i += best_len
            else:
                flags |= 1 << k
                out.append(data[i]); heads.setdefault(key, []).append(i); i += 1
        out[flag_pos] = flags
    return bytes(out)


def compress_opt(data):
    """최적 분할(글자 9비트·참조 17비트 DP) — 원본 압축기보다 작거나 비슷."""
    n = len(data); heads = {}; best = [(0, 0)] * n
    for i in range(n):
        key = data[i:i + 2]; bl = 0; bp = 0
        for j in reversed(heads.get(key, [])[-128:]):
            if i - j > 4096 - 18:
                break
            L = 0
            while L < 17 and i + L < n and data[j + L] == data[i + L]:
                L += 1
            if L > bl:
                bl, bp = L, j
                if L == 17:
                    break
        best[i] = (bl, bp)
        heads.setdefault(key, []).append(i)
    cost = [0] * (n + 1); choice = [0] * n
    for i in range(n - 1, -1, -1):
        c = 9 + cost[i + 1]; ch = 1
        bl, bp = best[i]
        for L in range(2, bl + 1):
            cc = 17 + cost[i + L]
            if cc < c:
                c, ch = cc, L
        cost[i] = c; choice[i] = ch
    out = bytearray([1]) + n.to_bytes(3, 'big')
    i = 0
    while i < n:
        fp = len(out); out.append(0); flags = 0
        for k in range(8):
            if i >= n:
                break
            L = choice[i]
            if L == 1:
                flags |= 1 << k; out.append(data[i]); i += 1
            else:
                r = best[i][1] & 0xFFF
                out += bytes([((L - 2) << 4) | (r >> 8), r & 0xFF]); i += L
        out[fp] = flags
    return bytes(out)

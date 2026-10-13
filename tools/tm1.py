# -*- coding: utf-8 -*-
r"""Duck TrueMotion 1 (24비트 RGB24H) — 디코더(ffmpeg libavcodec/truemotion1.c 그대로 옮김) + AVI 읽기 (2026-10-03)
  표 = work/tm1/truemotion1data.h(ffmpeg) 에서 읽는다. 동영상 자막용 인코더의 기준(docs/00 «TrueMotion 1 인코더»).
  python tools/tm1.py check OPENING [n]   → ffmpeg 디코드(work/movie/op_raw.rgb 등)와 앞 n 프레임 비트 대조
"""
import os, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'work', 'tm1ref', 'truemotion1data.h')   # 카오스 시드 tools/tm1.py 복사(2026-10-13) — 표 위치만 VIRUS 것

FLAG_SPRITE, FLAG_KEYFRAME, FLAG_INTERFRAME = 32, 16, 8
# 압축 번호 → (알고리즘, block_width, block_height, block_type)  알고리즘 0 NOP · 1 16V · 2 16H · 3 24H
COMP = [(0, 0, 0, 0), (1, 4, 4, 3), (2, 4, 4, 3), (1, 4, 2, 2), (2, 4, 2, 2), (1, 2, 4, 1), (2, 2, 4, 1), (1, 2, 2, 0), (2, 2, 2, 0),
        (0, 4, 4, 3), (3, 4, 4, 3), (0, 4, 2, 2), (3, 4, 2, 2), (0, 2, 4, 1), (3, 2, 4, 1), (0, 2, 2, 0), (3, 2, 2, 0)]
BLOCK_2x2, BLOCK_2x4, BLOCK_4x2, BLOCK_4x4 = 0, 1, 2, 3
M32 = 0xFFFFFFFF


def _tables():
    src = open(DATA, encoding='utf-8').read()
    arr = {}
    for m in re.finditer(r'static const (?:int16_t|uint8_t) (\w+)\[\d*\] = \{(.*?)\};', src, re.S):
        arr[m.group(1)] = [int(x, 0) for x in re.findall(r'-?0x[0-9a-fA-F]+|-?\d+', m.group(2))]
    ydts = [arr['ydt1'], arr['ydt2'], arr['ydt3'], arr['ydt4']]
    fat_ydts = [arr['fat_ydt3'], arr['fat_ydt3'], arr['fat_ydt3'], arr['fat_ydt4']]
    cdts = [arr['cdt1'], arr['cdt1'], arr['cdt2'], arr['cdt3']]
    fat_cdts = [arr['fat_cdt2'], arr['fat_cdt2'], arr['fat_cdt2'], arr['fat_ydt4']]
    vecs = [arr['pc_tbl2'], arr['pc_tbl3'], arr['pc_tbl4']]
    return ydts, fat_ydts, cdts, fat_cdts, vecs


YDTS, FAT_YDTS, CDTS, FAT_CDTS, VECS = _tables()


def delta_tables(ds):
    """deltaset → (ydt, cdt, fat_ydt, fat_cdt) — skinny ydt 는 lsb 버리고 /2(ffmpeg 그대로, C 정수 나눗셈 = 0 쪽 버림)"""
    ydt = []
    for v in YDTS[ds]:
        v &= 0xFFFE
        v = v - 0x10000 if v & 0x8000 else v
        ydt.append(int(v / 2))
    return ydt, list(CDTS[ds]), list(FAT_YDTS[ds]), list(FAT_CDTS[ds])


def codebook(vectable, compression, header_type):
    """색인(0‥255) → 델타쌍 목록 [(p1, p2), …] (Tunstall 코드북)"""
    vt = VECS[0] if (compression & 1) and header_type else VECS[vectable - 1]
    out = []; k = 0
    for i in range(256):
        n = vt[k] // 2; k += 1
        out.append([(vt[k + j] >> 4, vt[k + j] & 15) for j in range(n)]); k += n
    return out


def y15(p1, p2, t):
    lo = t[p1]; lo += lo * 32 + lo * 1024
    hi = t[p2]; hi += hi * 32 + hi * 1024
    return (lo + hi * 65536) * 2


def c15(p1, p2, t):
    lo = t[p2] + t[p1] * 1024
    return (lo + lo * 65536) * 2


def y24(p1, p2, t):
    return ((t[p1] + t[p2] * 256 + t[p2] * 65536) * 2)


def c24(p1, p2, t):
    return ((t[p2] + t[p1] * 65536) * 2)


class Tables:
    def __init__(self, ds, vectable, compression, header_type):
        ydt, cdt, fydt, fcdt = delta_tables(ds)
        cb = codebook(vectable, compression, header_type)
        self.cb = cb
        self.bits16 = COMP[compression][0] in (1, 2)
        z = [0] * 1024
        self.y, self.c, self.fy, self.fc = z[:], z[:], z[:], z[:]
        for i, ent in enumerate(cb):
            for j, (p1, p2) in enumerate(ent):
                last = 1 if j == len(ent) - 1 else 0
                yf, cf = (y15, c15) if self.bits16 else (y24, c24)
                self.y[i * 4 + j] = (yf(p1, p2, ydt) & 0xFFFFFFFE) | last
                self.c[i * 4 + j] = (cf(p1, p2, cdt) & 0xFFFFFFFE) | last
                self.fy[i * 4 + j] = (y24(p1, p2, fydt) & 0xFFFFFFFE) | last
                self.fc[i * 4 + j] = (c24(p1, p2, fcdt) & 0xFFFFFFFE) | last


def header(buf):
    hs = ((buf[0] >> 5) | (buf[0] << 3)) & 0x7F
    hb = bytes(buf[i] ^ buf[i + 1] for i in range(1, hs)) + bytes(16)
    h = dict(size=hs, compression=hb[0], deltaset=hb[1], vectable=hb[2], ysize=hb[3] | hb[4] << 8, xsize=hb[5] | hb[6] << 8,
             checksum=hb[7] | hb[8] << 8, version=hb[9], header_type=hb[10], flags=hb[11], control=hb[12])
    if h['version'] >= 2 and h['header_type'] in (2, 3):
        f = h['flags']
        if not f & FLAG_INTERFRAME:
            f |= FLAG_KEYFRAME
    else:
        f = FLAG_KEYFRAME
    h['kflags'] = f
    return h


class Decoder:
    """frame = 높이×너비 list of 32비트 낱말(0x00RRGGBB) — 이전 프레임을 유지(인터 프레임)"""
    def __init__(self):
        self.frame = None; self.key = None; self.tab = None; self.w = self.h = 0; self.b16 = None
        self.fat_mode = 'ffmpeg'                     # 이스케이프 뒤 처리 가설(녹화본 대조용)

    def decode(self, buf):
        if len(buf) < 2:                             # 빈 덩어리 = 앞 화면 유지
            return self.frame
        h = header(buf)
        alg, bw, bh, bt = COMP[h['compression']]
        if alg == 0:                                 # ★NOP = 앞 화면 유지(ffmpeg 는 여기서 화면 크기를 304폭으로 바꿨다 되돌리며 버퍼를 버려
            return self.frame                        #   다음 키 프레임까지 인터 프레임이 깨진다 — OPENING 37‥48초)
        b16 = alg in (1, 2)
        ws = 0 if b16 else 1
        w, hgt = h['xsize'] >> ws, h['ysize']                 # 화소 폭(24비트는 머리 xsize 의 절반)
        nw = w >> 1 if b16 else w                             # 한 줄 32비트 낱말 수(16비트 = 화소 2개/낱말)
        key = (h['deltaset'], h['vectable'], h['compression'], h['header_type'])
        if key != self.key:
            self.tab = Tables(*key); self.key = key
        if self.frame is None or (w, hgt, b16) != (self.w, self.h, self.b16):
            self.w, self.h, self.b16 = w, hgt, b16; self.frame = [[0] * nw for _ in range(hgt)]
        rowsize = ((w >> (2 - ws)) + 7) >> 3
        keyframe = h['kflags'] & FLAG_KEYFRAME
        mb = h['size']
        idx_pos = mb if keyframe else mb + rowsize * (hgt >> 2)
        T = self.tab; Y, C, FY, FC = T.y, T.c, T.fy, T.fc
        st = {'p': idx_pos}

        def nxt():
            v = buf[st['p']] * 4; st['p'] += 1
            return v
        vert = [0] * nw
        index = nxt()
        hp = 0
        F = self.frame
        for y in range(hgt):
            hp = 0
            row = F[y]
            cbits = buf[mb + (y >> 2) * rowsize: mb + (y >> 2) * rowsize + rowsize]
            x = 0
            for blk in range(nw >> 1):
                changed = keyframe or not (cbits[blk >> 3] >> (blk & 7)) & 1
                if changed:
                    r = y & 3
                    if r == 0:
                        seq = 'CYCY' if bw == 2 else 'CYY'
                    elif r == 2:
                        seq = 'CYCY' if bt == BLOCK_2x2 else ('CYY' if bt == BLOCK_4x2 else 'YY')
                    else:
                        seq = 'YY'
                    for op in seq:
                        tb, ftb = (C, FC) if op == 'C' else (Y, FY)
                        pp = tb[index]; hp = (hp + (pp >> 1)) & M32
                        if pp & 1:
                            index = nxt()
                            if not index:
                                index = nxt()
                                if b16:                      # 16비트 이스케이프 = 같은 표 ×5
                                    pp = tb[index]; hp = (hp + (pp >> 1) * 5) & M32
                                else:
                                    pp = ftb[index]; hp = (hp + (pp >> 1)) & M32
                                if pp & 1:
                                    index = nxt()
                                else:
                                    index += 1
                        else:
                            index += 1
                        if op == 'Y':
                            v = (vert[x] + hp) & M32
                            row[x] = v; vert[x] = v; x += 1
                else:
                    vert[x] = row[x]; x += 1
                    hp = (row[x] - vert[x]) & M32
                    vert[x] = row[x]; x += 1
        return F


class GDecoder(Decoder):
    """★게임(새턴) 24비트 모델 — 낱말 하나 = 화소 2개(2026-10-03 실기 VRAM 과 304/304 일치 검증).
    Y 쌍 p1 = 왼쪽 밝기 Ya, p2 = 오른쪽 밝기 Yb, C 쌍 = 공용 색(CR, CB). ffmpeg 낱말 (R, G, B) = (Yb+CR, Yb, Ya+CB) 이고
    d = Ya − Yb 를 따로 쌓는다(dframe) → 왼쪽 = (R+d, G+d, B), 오른쪽 = (R, G, B−d) (성분 mod 256).
    16비트는 Decoder 와 같다(dframe 은 0)."""
    def decode(self, buf):
        if len(buf) < 2:                             # 빈 덩어리 = 앞 화면 유지
            return self.frame
        h = header(buf)
        alg, bw, bh, bt = COMP[h['compression']]
        if alg == 0:                                 # ★NOP = 앞 화면 유지(ffmpeg 는 여기서 화면 크기를 304폭으로 바꿨다 되돌리며 버퍼를 버려
            return self.frame                        #   다음 키 프레임까지 인터 프레임이 깨진다 — OPENING 37‥48초)
        b16 = alg in (1, 2)
        ws = 0 if b16 else 1
        w, hgt = h['xsize'] >> ws, h['ysize']                 # 화소 폭(24비트는 머리 xsize 의 절반)
        nw = w >> 1 if b16 else w                             # 한 줄 32비트 낱말 수(16비트 = 화소 2개/낱말)
        key = (h['deltaset'], h['vectable'], h['compression'], h['header_type'])
        if key != self.key:
            self.tab = Tables(*key); self.key = key
        if self.frame is None or (w, hgt, b16) != (self.w, self.h, self.b16):
            self.w, self.h, self.b16 = w, hgt, b16; self.frame = [[0] * nw for _ in range(hgt)]
        rowsize = ((w >> (2 - ws)) + 7) >> 3
        keyframe = h['kflags'] & FLAG_KEYFRAME
        mb = h['size']
        idx_pos = mb if keyframe else mb + rowsize * (hgt >> 2)
        T = self.tab; Y, C, FY, FC = T.y, T.c, T.fy, T.fc
        if not hasattr(T, 'yd'):
            ydt, cdt, fydt, fcdt = delta_tables(self.key[0])
            T.yd = [0] * 1024; T.fyd = [0] * 1024
            for i, ent in enumerate(T.cb):
                for j, (p1, p2) in enumerate(ent):
                    T.yd[i * 4 + j] = ydt[p1] - ydt[p2]; T.fyd[i * 4 + j] = fydt[p1] - fydt[p2]
        if getattr(self, 'dframe', None) is None or len(self.dframe) != hgt:
            self.dframe = [[0] * nw for _ in range(hgt)]
        DF = self.dframe; dvert = [0] * nw
        st = {'p': idx_pos}

        def nxt():
            v = buf[st['p']] * 4; st['p'] += 1
            return v
        vert = [0] * nw
        index = nxt()
        hp = 0
        F = self.frame
        for y in range(hgt):
            hp = 0; dh = 0
            row = F[y]; drow = DF[y]
            cbits = buf[mb + (y >> 2) * rowsize: mb + (y >> 2) * rowsize + rowsize]
            x = 0
            for blk in range(nw >> 1):
                changed = keyframe or not (cbits[blk >> 3] >> (blk & 7)) & 1
                if changed:
                    r = y & 3
                    if r == 0:
                        seq = 'CYCY' if bw == 2 else 'CYY'
                    elif r == 2:
                        seq = 'CYCY' if bt == BLOCK_2x2 else ('CYY' if bt == BLOCK_4x2 else 'YY')
                    else:
                        seq = 'YY'
                    for op in seq:
                        tb, ftb = (C, FC) if op == 'C' else (Y, FY)
                        pp = tb[index]; hp = (hp + (pp >> 1)) & M32
                        if op == 'Y': dh += T.yd[index]
                        if pp & 1:
                            index = nxt()
                            if not index:
                                index = nxt()
                                if b16:                      # 16비트 이스케이프 = 같은 표 ×5
                                    pp = tb[index]; hp = (hp + (pp >> 1) * 5) & M32
                                else:
                                    pp = ftb[index]; hp = (hp + (pp >> 1)) & M32
                                    if op == 'Y': dh += T.fyd[index]
                                if pp & 1:
                                    index = nxt()
                                else:
                                    index += 1
                        else:
                            index += 1
                        if op == 'Y':
                            v = (vert[x] + hp) & M32
                            row[x] = v; vert[x] = v
                            dv = dvert[x] + dh; drow[x] = dv; dvert[x] = dv; x += 1
                else:
                    vert[x] = row[x]; dvert[x] = drow[x]; x += 1
                    hp = (row[x] - vert[x]) & M32; dh = drow[x] - dvert[x]
                    vert[x] = row[x]; dvert[x] = drow[x]; x += 1
        return F




def game_rgb(F, DF):
    """GDecoder 화면 → 304폭 RGB 바이트(게임 화면 그대로)"""
    out = bytearray()
    for row, drow in zip(F, DF):
        for v, d in zip(row, drow):
            R, G, B = (v >> 16) & 255, (v >> 8) & 255, v & 255
            out += bytes(((R + d) & 255, (G + d) & 255, B, R, G, (B - d) & 255))
    return bytes(out)


def movi_pos(d):
    """«LIST 크기 movi» 의 movi 위치 — ★JUNK 속 경로 문자열(E:\movie\…)의 'movi' 를 잡지 않게(VIRUS S037_1 등, 2026-10-13)"""
    import re
    m = re.search(rb'LIST.{4}movi', d, re.S)
    return m.start() + 8


def avi_frames(path):
    """AVI movi 의 00dc·00db(키) 덩어리 목록 [(파일 안 오프셋, 바이트)]"""
    d = open(path, 'rb').read()
    i = movi_pos(d) + 4; out = []
    while i + 8 <= len(d):
        tag = d[i:i + 4]; n = struct.unpack_from('<I', d, i + 4)[0]
        if tag == b'LIST':
            i += 12; continue
        if tag == b'idx1':
            break
        if tag[2:] in (b'dc', b'db'):
            out.append((i, d[i + 8:i + 8 + n]))
        i += 8 + n + (n & 1)
    return out


def to_rgb(F, b16=False):
    if not b16:
        return bytes(b for row in F for v in row for b in ((v >> 16) & 255, (v >> 8) & 255, v & 255))
    out = bytearray()
    for row in F:
        for v in row:
            for q in (v & 0xFFFF, v >> 16):              # 낱말 아래 16비트 = 왼쪽 화소(리틀 엔디언 버퍼)
                r, g, b = (q >> 10) & 31, (q >> 5) & 31, q & 31
                out += bytes(((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)))
    return bytes(out)


if __name__ == '__main__' and sys.argv[1] == 'check':
    import numpy as np
    name = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    fr = avi_frames(os.path.join(ROOT, 'work', 'movie', 'avi', name + '.AVI'))
    ref = np.fromfile(os.path.join(ROOT, 'work', 'movie', 'op_raw.rgb'), np.uint8).reshape(-1, 208, 152, 3)
    D = Decoder(); k = 0
    for off, b in fr[:n]:
        if not b:
            continue
        F = D.decode(b)
        a = np.frombuffer(to_rgb(F), np.uint8).reshape(208, 152, 3)
        print(k, header(b)['kflags'], 'diff', int((a != ref[k]).sum()))
        k += 1


FFMPEG = r'C:\claude\utils\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe'


def to_mp4(avi, mp4):
    """이 디코더로 풀어(NOP·빈 프레임 = 앞 화면 유지) mp4(16비트 320×224 → 640×448 · 24비트 152×208 → 608×416) — 소리는 AVI 그대로"""
    import subprocess
    fr = avi_frames(avi)
    h0 = header(next(b for _, b in fr if len(b) >= 2))
    b16 = COMP[h0['compression']][0] in (1, 2)
    w, hgt = (h0['xsize'], h0['ysize']) if b16 else (h0['xsize'] >> 1, h0['ysize'])
    sc = 'scale=%d:%d:flags=neighbor,setsar=1' % ((w * 2, hgt * 2) if b16 else (w * 4, hgt * 2))
    p = subprocess.Popen([FFMPEG, '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, hgt), '-r', '15',
                          '-i', '-', '-i', avi, '-map', '0:v', '-map', '1:a', '-vf', sc,
                          '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', mp4], stdin=subprocess.PIPE)
    D = Decoder()
    for _, b in fr:
        F = D.decode(b)
        p.stdin.write(to_rgb(F, b16) if F else bytes(w * hgt * 3))
    p.stdin.close(); p.wait()
    return len(fr)


if __name__ == '__main__' and sys.argv[1] == 'mp4':
    import glob
    for a in sorted(glob.glob(os.path.join(ROOT, 'work', 'movie', 'avi', '*.AVI'))):
        n = os.path.splitext(os.path.basename(a))[0]
        if len(sys.argv) > 2 and n not in sys.argv[2:]:
            continue
        print(n, to_mp4(a, os.path.join(ROOT, 'work', 'movie', 'mp4', n + '.mp4')), flush=True)

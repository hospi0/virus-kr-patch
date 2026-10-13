# -*- coding: utf-8 -*-
r"""Duck TrueMotion 1 인코더(16비트 RGB16H · 24비트 RGB24H) — 동영상 자막용 (2026-10-03)
  방식: 화면 «아래 띠»(BAND 줄, 4의 배수)만 다시 부호화하고 그 위는 원본 델타 열을 그대로 다시 묶는다(손실 0).
    · trace(): 원본 프레임을 풀면서 연산마다 (줄, 낱말, C/Y, 델타쌍, 이스케이프쌍) 기록
    · segment(): 연산 열 → Tunstall 코드북 색인 바이트(동적 계획, 이스케이프 = 코드 끝 뒤 0 + 첫 항목이 ×5/fat 인 코드)
    · 띠: 닫힌 고리(디코더와 같은 셈)로 목표(원본 + 자막) 화소에 가장 가까운 델타 선택, 성분은 늘 범위 안
  검증: 다시 짠 프레임을 tm1.Decoder 로 풀어 의도한 화면과 비트 대조.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import tm1

M32 = 0xFFFFFFFF


def ops_seq(r, bw, bt):
    if r == 0:
        return 'CYCY' if bw == 2 else 'CYY'
    if r == 2:
        return 'CYCY' if bt == tm1.BLOCK_2x2 else ('CYY' if bt == tm1.BLOCK_4x2 else 'YY')
    return 'YY'


class Frame:
    """한 프레임 풀이 결과: 머리·변경 비트·연산 열(줄별)"""
    pass


def trace(D, buf):
    """tm1.Decoder D 의 상태로 buf 를 풀며 연산 기록 → Frame (D.frame 도 갱신)"""
    h = tm1.header(buf)
    alg, bw, bh, bt = tm1.COMP[h['compression']]
    fr = Frame(); fr.h = h; fr.buf = buf
    if alg == 0:
        fr.nop = True; return fr
    fr.nop = False
    D.decode(buf)                                    # 화면은 기준 디코더로(상태 일치)
    b16 = alg in (1, 2); ws = 0 if b16 else 1
    w, hgt = h['xsize'] >> ws, h['ysize']; nw = w >> 1 if b16 else w
    rowsize = ((w >> (2 - ws)) + 7) >> 3
    keyframe = h['kflags'] & tm1.FLAG_KEYFRAME
    mb = h['size']; pos = mb if keyframe else mb + rowsize * (hgt >> 2)
    T = D.tab; Y, C, FY, FC = T.y, T.c, T.fy, T.fc
    cb = T.cb
    st = [pos]

    def nxt():
        v = buf[st[0]] * 4; st[0] += 1
        return v
    fr.b16, fr.w, fr.hgt, fr.nw, fr.rowsize, fr.key = b16, w, hgt, nw, rowsize, keyframe
    fr.bw, fr.bt = bw, bt
    fr.cbits = [] if keyframe else [buf[mb + i * rowsize: mb + i * rowsize + rowsize] for i in range(hgt >> 2)]
    rows = []
    index = nxt()
    for y in range(hgt):
        cbits = None if keyframe else fr.cbits[y >> 2]
        ops = []
        for blk in range(nw >> 1):
            changed = keyframe or not (cbits[blk >> 3] >> (blk & 7)) & 1
            if not changed:
                continue
            for op in ops_seq(y & 3, bw, bt):
                tb = C if op == 'C' else Y
                pair = cb[index >> 2][index & 3]
                esc = None
                pp = tb[index]
                if pp & 1:
                    index = nxt()
                    if not index:
                        index = nxt()
                        esc = cb[index >> 2][index & 3]
                        pp2 = tb[index] if b16 else (FC if op == 'C' else FY)[index]
                        if pp2 & 1:
                            index = nxt()
                        else:
                            index += 1
                else:
                    index += 1
                ops.append((blk, op, pair, esc))
        rows.append(ops)
    fr.rows = rows
    return fr


def build_dict(cb):
    d = {}
    for i, ent in enumerate(cb):
        if i == 0:
            continue                                 # 색인 0 = 이스케이프 표지
        d.setdefault(tuple(ent), i)
    return d


def segment(ops, cdict):
    """ops = [(pair, esc|None)] → 색인 바이트 열(최소 길이). 이스케이프 연산은 코드의 «마지막 항목»이어야 하고,
       뒤에 0 + (esc 쌍으로 시작하는 코드)가 온다 — 그 코드의 나머지 항목은 다음 연산들."""
    n = len(ops)
    INF = 10 ** 9
    memo = {}
    sys.setrecursionlimit(1000000)
    # 반복 DP: f(i, pend) = i 번 연산부터 덮는 최소 바이트, pend = 다음 코드 첫 항목으로 와야 할 esc 쌍
    best = [[None, None] for _ in range(n + 1)]       # [pend 없음, pend 있음(그 esc 는 ops[i-1] 의 것)]
    cost = [[INF, INF] for _ in range(n + 1)]
    cost[n][0] = 0
    for i in range(n, -1, -1):
        for pe in (0, 1):
            if i == n and pe == 0:
                continue
            if pe == 1:
                if i == 0 or ops[i - 1][1] is None:
                    continue
                head = [ops[i - 1][1]]
            else:
                if i == n:
                    continue
                head = []
            bc, bchoice = INF, None
            for L in range(0 if pe else 1, 5 - len(head)):
                if i + L > n:
                    break
                seq = head + [ops[k][0] for k in range(i, i + L)]
                if not seq or len(seq) > 4:
                    continue
                # 코드 안쪽(마지막 제외) 연산은 이스케이프 없어야
                if any(ops[k][1] is not None for k in range(i, i + L - 1)):
                    continue
                idx = cdict.get(tuple(seq))
                if idx is None:
                    continue
                last_esc = L > 0 and ops[i + L - 1][1] is not None
                if last_esc:
                    c = 2 + cost[i + L][1]            # 이 코드 + 0 표지 (+ esc 코드는 다음 상태가 셈)
                else:
                    c = 1 + cost[i + L][0]
                if c < bc:
                    bc, bchoice = c, (L, idx, last_esc)
            cost[i][pe] = bc; best[i][pe] = bchoice
    if cost[0][0] >= INF:
        raise ValueError('부호화 불가 연산 열')
    out = bytearray(); i, pe = 0, 0
    while not (i == n and pe == 0):
        L, idx, last_esc = best[i][pe]
        out.append(idx)
        if last_esc:
            out.append(0)
        i += L; pe = 1 if last_esc else 0
    return bytes(out)


def enc_header(hb, hs, first_data):
    """복호 머리 hb(길이 hs-1) → 암호화된 머리 바이트(hs 개). buf[i]^buf[i+1] = hb[i-1], buf[hs] = first_data"""
    b = [0] * (hs + 1); b[hs] = first_data
    for i in range(hs - 1, 0, -1):
        b[i] = hb[i - 1] ^ b[i + 1]
    # 첫 바이트: ((x>>5)|(x<<3))&0x7F == hs 인 값(원본 그대로 쓰는 게 안전)
    return b


def rebuild(fr, rows_ops, cbits, cdict):
    """연산 열·변경 비트로 프레임 바이트를 다시 짠다(머리는 원본 그대로 다시 암호화)"""
    buf = fr.buf; hs = fr.h['size']
    hb = bytes(buf[i] ^ buf[i + 1] for i in range(1, hs))
    flat = [(p, e) for ops in rows_ops for (_, _, p, e) in ops]
    idx = segment(flat, cdict) + b''                # 디코더가 마지막 코드 뒤 색인 하나를 더 읽는다(0 이면 이스케이프로 또 읽음)
    body = (b'' if fr.key else b''.join(bytes(c) for c in cbits)) + idx
    b = enc_header(hb, hs, body[0])
    return bytes([buf[0]] + b[1:hs]) + body


if __name__ == '__main__' and sys.argv[1] == 'same':
    # 검증 1: 원본을 추적해 그대로 다시 묶은 프레임이 원본과 같은 화면이 되는가
    import numpy as np
    name = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    frs = tm1.avi_frames(os.path.join(tm1.ROOT, 'work', 'movie', 'avi', name + '.AVI'))
    A, B = tm1.Decoder(), tm1.Decoder()
    tot0 = tot1 = 0; bad = 0
    for k, (_, b) in enumerate(frs[:n]):
        if len(b) < 2:
            continue
        fr = trace(A, b)
        if fr.nop:
            B.decode(b); continue
        cd = build_dict(A.tab.cb)
        nb = rebuild(fr, fr.rows, fr.cbits, cd)
        B.decode(nb)
        same = A.frame == B.frame
        bad += not same; tot0 += len(b); tot1 += len(nb)
        if not same or k % 50 == 0:
            print(k, '같음' if same else '★다름', len(b), '→', len(nb))
    print('다름 %d · 크기 %d → %d (%.1f%%)' % (bad, tot0, tot1, 100.0 * tot1 / max(1, tot0)))

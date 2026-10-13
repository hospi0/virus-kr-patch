# -*- coding: utf-8 -*-
r"""TrueMotion 1 «아래 띠» 인코더 (2026-10-03) — tools/tm1enc.py 의 위쪽 그대로 재현과 짝
  낱말 = 16비트: 화소 2개(lane 0 = 아래 16비트 = 왼쪽) × (R, G, B) 5비트 / 24비트: 화소 1개 × (R, G, B) 8비트
  Y 쌍 (p1, p2): 16비트 = lane0 RGB += ydt[p1], lane1 RGB += ydt[p2] · 24비트 = B += ydt[p1], G·R += ydt[p2]
  C 쌍 (p1, p2): R += cdt[p1], B += cdt[p2] (16비트는 두 lane 모두)
  이스케이프(코드 끝 뒤 0 + 코드): 16비트 = 같은 표 ×5 를 더함, 24비트 = fat 표 값을 더함
  가로 누적 H 는 줄 안에서 계속 쌓이고 화소 = 위 화소 + H — 성분이 범위를 벗어나는 선택은 버린다(디코더 구현 차이 회피).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import tm1, tm1enc


def unpack(v, b16):
    if b16:
        return ([(v >> (s + 10)) & 31 for s in (0, 16)], [(v >> (s + 5)) & 31 for s in (0, 16)], [(v >> s) & 31 for s in (0, 16)])
    return ([(v >> 16) & 255], [(v >> 8) & 255], [v & 255])


def pack(R, G, B, b16):
    if b16:
        return sum(((R[k] << 10) | (G[k] << 5) | B[k]) << (16 * k) for k in range(2))
    return (R[0] << 16) | (G[0] << 8) | B[0]


class Stuck(Exception):
    """(VIRUS) 범위를 지킬 Y 가 없음 — 왼쪽 «건너뜀» 블록이 누적값을 앞 화면 차이로 덮어 생김(색차 없는 홀수 줄)"""
    def __init__(self, y, blk):
        super().__init__(y, blk); self.y, self.blk = y, blk


class BandEnc:
    def __init__(self, tab, ds, b16, bw, bt, y0, tol=None, coarse=0):
        self.coarse = coarse              # ★0‥ : 클수록 이스케이프를 덜 써서 바이트를 줄인다(덩어리 크기 한도용, 2026-10-03)
        self.b16, self.bw, self.bt, self.y0 = b16, bw, bt, y0
        self.ydt, self.cdt, self.fydt, self.fcdt = tm1.delta_tables(ds)
        self.mx = 31 if b16 else 255
        self.nl = 2 if b16 else 1
        self.tol = tol if tol is not None else (1 if b16 else 6)
        self.cdict = tm1enc.build_dict(tab.cb)
        singles = {k[0] for k in self.cdict if len(k) == 1}
        # 단독 코드가 있는 색인만 쓴다(그래야 어떤 열이든 묶인다)
        self.allowed = [a for a in range(8) if all((a, b) in singles and (b, a) in singles for b in range(8) if b == a or True)
                        and all((a, b) in singles for b in range(8) if b in [c for c in range(8) if all((c, d) in singles for d in range(8))])]
        ok = [a for a in range(8) if all((a, b) in singles for b in range(8)) or all((a, b) in singles for b in range(7))]
        self.allowed = [a for a in ok if all((a, b) in singles for b in ok) and all((b, a) in singles for b in ok)]
        # Y 그룹: 16비트 lane0(RGB) ← p1, lane1(RGB) ← p2 / 24비트 B ← p1, (R, G) ← p2
        self.ygroups = [[(0, 0), (1, 0), (2, 0)], [(0, 1), (1, 1), (2, 1)]] if b16 else [[(2, 0)], [(0, 0), (1, 0)]]

    # ── 선택 ──
    def nearest(self, need, vals):
        best = None
        for a in self.allowed:
            e = abs(need - vals[a])
            if best is None or e < best[0]:
                best = (e, a)
        return best[1]

    def pick_c(self, dR, dB):
        cdt = self.cdt
        a = self.nearest(dR, cdt); b = self.nearest(dB, cdt) if self.b16 else self.allowed[0] if cdt[self.allowed[0]] == 0 else self.nearest(0, cdt)
        add = [cdt[a], cdt[b]]; esc = None
        rem = [dR - add[0], (dB - add[1]) if self.b16 else 0]
        lim = (4 if self.b16 else 24) * (1 + self.coarse)
        if abs(rem[0]) > lim or abs(rem[1]) > lim:
            ft = [v * 5 for v in cdt] if self.b16 else self.fcdt
            ea = self.nearest(rem[0], ft); eb = self.nearest(rem[1], ft) if self.b16 else self.nearest(0, ft)
            if abs(rem[0] - ft[ea]) + abs(rem[1] - ft[eb]) < abs(rem[0]) + abs(rem[1]) - 2:
                esc = (ea, eb); add = [add[0] + ft[ea], add[1] + ft[eb]]
        return (a, b), esc, add

    def pick_y(self, tg, v, H):
        mx, ydt = self.mx, self.ydt
        ft = [x * 5 for x in ydt] if self.b16 else self.fydt

        nv = getattr(self, '_next', None)      # ★(VIRUS) 같은 C 묶음의 다음 낱말 위 화소 — 그 낱말도 «어떤 Y 로든» 범위 안이어야
        if nv is not None and not hasattr(self, 'yvals'):
            self.c_ok([], None, None, None)

        def err(g, d):
            e = 0
            for (c, l) in g:
                val = v[c][l] + H[c][l] + d
                if val < 0 or val > mx:
                    return None
                e += (tg[c][l] - val) ** 2
            if nv is not None:
                l = g[0][1]
                base = [nv[c][l] + H[c][l] + d for c in range(3)]
                lo, hi = -min(base), mx - max(base)
                if lo > hi or not any(lo <= q <= hi for q in self.yvals):
                    return None
            return e
        res = []
        need_esc = False
        for g in self.ygroups:
            best = None
            for a in self.allowed:
                e = err(g, ydt[a])
                if e is not None and (best is None or e < best[0]):
                    best = (e, a, None, ydt[a])
            if best is None or best[0] > (12 if self.b16 else 900) * (1 + self.coarse) ** 2:
                need_esc = True
            res.append(best)
        esc = None
        if need_esc:
            alt = []
            for g, c0 in zip(self.ygroups, res):
                best = c0
                for a in self.allowed:
                    for b in self.allowed:
                        d = ydt[a] + ft[b]
                        e = err(g, d)
                        if e is not None and (best is None or e < best[0]):
                            best = (e, a, b, d)
                alt.append(best)
            old = sum(c[0] for c in res) if all(res) else 10 ** 9
            new = sum(c[0] for c in alt)
            if new < old - (8 if self.b16 else 400) * (1 + self.coarse) ** 2:
                z = self.nearest(0, ft)
                res = alt
                esc = tuple(c[2] if c[2] is not None else z for c in alt)
                res = [(c[0], c[1], c[2], ydt[c[1]] + (ft[c[2]] if c[2] is not None else ft[z])) for c in alt]
        pair = (res[0][1], res[1][1])
        add = [[0] * self.nl for _ in range(3)]
        for g, c in zip(self.ygroups, res):
            for (cc, l) in g:
                add[cc][l] = c[3]
        return pair, esc, add

    def c_ok(self, xs, vert, H, add):
        """C 값 add=[dR, dB] 를 더한 뒤, 뒤따르는 화소마다 lane 별로 «한 Y 값 d 로 R·G·B 모두 0‥mx» 가 가능한가"""
        if not hasattr(self, 'yvals'):
            ft = [x * 5 for x in self.ydt]
            self.yvals = sorted({self.ydt[a] for a in self.allowed} | {self.ydt[a] + ft[b] for a in self.allowed for b in self.allowed})
        mx = self.mx
        if not xs:
            return True
        # 묶음 안 낱말들을 «차례로» — 앞 낱말의 Y 값이 H 에 쌓여 뒤 낱말로 넘어가므로 이어서 가능한지(lane 별 독립)
        for l in range(self.nl):
            bases = [[vert[xx][0][l] + H[0][l] + add[0], vert[xx][1][l] + H[1][l], vert[xx][2][l] + H[2][l] + add[1]] for xx in xs]
            reach = {0}
            for bs in bases:
                nxt = set()
                for sh in reach:
                    lo, hi = -(min(bs) + sh), mx - (max(bs) + sh)
                    for v in self.yvals:
                        if lo <= v <= hi:
                            nxt.add(sh + v)
                if not nxt:
                    return False
                reach = nxt
        return True

    # ── 띠 부호화 ──
    def encode(self, cur, prev_rows, target, keyframe, force=()):
        """cur = 현재 프레임 낱말 행 목록(띠 위는 원본, 띠는 덮어씀) · prev_rows = 이전 프레임 낱말 행 · target[y][x] = (R[], G[], B[])
           → (줄별 연산 [(blk, op, pair, esc)], 띠 블록 줄 변경 비트 bytes 목록)"""
        b16, nl, mx = self.b16, self.nl, self.mx
        nw = len(cur[0]); nblk = nw >> 1; hgt = len(cur)
        changed = {}; cb_rows = []
        for by in range(self.y0 >> 2, hgt >> 2):
            bits = bytearray((nblk + 7) >> 3)
            for blk in range(nblk):
                ch = bool(keyframe)
                if not ch:
                    for y in range(by * 4, by * 4 + 4):
                        for x in (blk * 2, blk * 2 + 1):
                            pr = unpack(prev_rows[y][x], b16); tg = target[y][x]
                            if any(abs(pr[c][l] - tg[c][l]) > self.tol for c in range(3) for l in range(nl)):
                                ch = True; break
                        if ch:
                            break
                ch = ch or (by, blk) in force           # ★(VIRUS) 막힘 풀기용 강제 부호화
                changed[(by, blk)] = ch
                if not ch:
                    bits[blk >> 3] |= 1 << (blk & 7)
            cb_rows.append(bytes(bits))
        if self.y0 > 0:
            vert = [list(map(list, unpack(v, b16))) for v in cur[self.y0 - 1]]
        else:
            vert = [[[0] * nl for _ in range(3)] for _ in range(nw)]
        rows_ops = []
        for y in range(self.y0, hgt):
            H = [[0] * nl for _ in range(3)]
            row = cur[y]; ops = []; x = 0
            seq = tm1enc.ops_seq(y & 3, self.bw, self.bt)
            for blk in range(nblk):
                if not changed[(y >> 2, blk)]:
                    for k in (0, 1):
                        pv = prev_rows[y][x]; row[x] = pv
                        P = unpack(pv, b16)
                        if k == 1:
                            H = [[P[c][l] - vert[x][c][l] for l in range(nl)] for c in range(3)]
                        vert[x] = [list(P[c]) for c in range(3)]
                        x += 1
                    continue
                for si, op in enumerate(seq):
                    if op == 'C':
                        xs = []
                        for j in range(si + 1, len(seq)):
                            if seq[j] == 'C':
                                break
                            xs.append(x + len(xs))
                        dR = dB = 0.0; n = 0
                        for xx in xs:
                            tg = target[y][xx]
                            for l in range(nl):
                                g = tg[1][l] - (vert[xx][1][l] + H[1][l])
                                dR += tg[0][l] - (vert[xx][0][l] + H[0][l]) - g
                                dB += tg[2][l] - (vert[xx][2][l] + H[2][l]) - g
                                n += 1
                        pair, esc, add = self.pick_c(dR / max(n, 1), dB / max(n, 1))
                        # ★(VIRUS 2026-10-13) C 가 R·B 를 끝으로 밀면 뒤 Y(세 성분 같이)로 범위를 못 지켜 pick_y 가 막힌다(OPA)
                        #   → 뒤따르는 화소들이 «어떤 Y 값으로든» 범위 안에 들어갈 수 있는 C 만. 안 되면 가까운 순으로 다른 C 쌍.
                        if not self.c_ok(xs, vert, H, add):
                            dRm, dBm = dR / max(n, 1), dB / max(n, 1)
                            alts = sorted(((abs(dRm - self.cdt[a]) + abs(dBm - self.cdt[b2]), a, b2)
                                           for a in self.allowed for b2 in self.allowed))
                            found = False
                            for _, a, b2 in alts:
                                ad = [self.cdt[a], self.cdt[b2]]
                                if self.c_ok(xs, vert, H, ad):
                                    pair, esc, add = (a, b2), None, ad; found = True
                                    break
                            if not found:                 # 누적 어긋남이 크면 탈출(×5) 색차까지
                                ft = [v * 5 for v in self.cdt]
                                alts = sorted(((abs(dRm - self.cdt[a] - ft[ea]) + abs(dBm - self.cdt[b2] - ft[eb]), a, b2, ea, eb)
                                               for a in self.allowed for b2 in self.allowed for ea in self.allowed for eb in self.allowed))
                                for _, a, b2, ea, eb in alts:
                                    ad = [self.cdt[a] + ft[ea], self.cdt[b2] + ft[eb]]
                                    if self.c_ok(xs, vert, H, ad):
                                        pair, esc, add = (a, b2), (ea, eb), ad
                                        break
                        H[0] = [h + add[0] for h in H[0]]; H[2] = [h + add[1] for h in H[2]]
                        ops.append((blk, 'C', pair, esc))
                    else:
                        self._next = vert[x + 1] if si + 1 < len(seq) and seq[si + 1] == 'Y' and x + 1 < nw else None
                        try:
                            pair, esc, add = self.pick_y(target[y][x], vert[x], H)
                        except TypeError:
                            raise Stuck(y, blk)
                        for c in range(3):
                            for l in range(nl):
                                H[c][l] += add[c][l]
                        P = [[vert[x][c][l] + H[c][l] for l in range(nl)] for c in range(3)]
                        if not all(0 <= P[c][l] <= mx for c in range(3) for l in range(nl)):
                            raise AssertionError(('범위 밖', y, x, P))
                        row[x] = pack(P[0], P[1], P[2], b16); vert[x] = P
                        ops.append((blk, 'Y', pair, esc))
                        x += 1
            rows_ops.append(ops)
        return rows_ops, cb_rows


CMAX = 40


class BandEnc24G(BandEnc):
    """★24비트 «게임 모델» 띠 인코더(2026-10-03) — 새턴은 낱말 하나를 화소 2개로 낸다(tm1.GDecoder).
    Y 쌍: p1 → 왼쪽 밝기 Ya(ffmpeg 낱말의 B), p2 → 오른쪽 밝기 Yb(R·G), d = Ya − Yb 를 따로 쌓는다.
    목표 = 304폭 게임 화소(왼쪽 tl, 오른쪽 tr). 왼쪽·오른쪽 오차가 p1·p2 로 갈라지므로 따로 고른다.
    ffmpeg 모델로만 맞추면 좌우 밝기 차가 커져 게임에서 파란 점·흰 얼룩(2026-10-03 실기)."""

    def side(self, Y, CR, CB, t, ydt, ft):
        """한쪽 밝기 Y 를 목표 화소 t 에 맞출 (색인, 이스케이프 색인 or None, 더할 값)"""
        def err(Yn):
            p = (Yn + CR, Yn, Yn + CB)
            if min(p) < 0 or max(p) > 255:
                return None
            return sum((a - b) ** 2 for a, b in zip(p, t))
        best = None
        for a in self.allowed:
            e = err(Y + ydt[a])
            if e is not None and (best is None or e < best[0]):
                best = (e, a, None, ydt[a])
        if best is None or best[0] > 300 * (1 + self.coarse) ** 2:
            for a in self.allowed:
                for b in self.allowed:
                    dv = ydt[a] + ft[b]; e = err(Y + dv)
                    if e is not None and (best is None or e < best[0] - 300 * (1 + self.coarse) ** 2):
                        best = (e, a, b, dv)
        if best is None:                              # 범위 안 후보가 없으면 가장 덜 넘는 것
            best = min(((abs(min(0, Y + ydt[a] + min(CR, CB, 0))) + max(0, Y + ydt[a] + max(CR, CB, 0) - 255), a, None, ydt[a])
                        for a in self.allowed))
        return best

    def feasible(self, Y, CR, CB):
        lo, hi = min(0, CR, CB), max(0, CR, CB)
        ds = [self.ydt[a] for a in self.allowed] + [self.ydt[a] + self.fydt[b] for a in self.allowed for b in self.allowed]
        return any(Y + v + lo >= 0 and Y + v + hi <= 255 for v in ds)

    def encode_game(self, cur, curd, prev_rows, prevd, target, keyframe):
        """cur/curd = 현재 프레임 낱말·d(띠 위는 원본) · prev_rows/prevd = 이전 출력 프레임 · target[y][x] = (tl, tr) 게임 화소"""
        nw = len(cur[0]); nblk = nw >> 1; hgt = len(cur)
        ydt = self.ydt; ft = self.fydt
        def game(v, d):
            R, G, B = (v >> 16) & 255, (v >> 8) & 255, v & 255
            return ((R + d) & 255, (G + d) & 255, B), (R, G, (B - d) & 255)
        changed = {}; cb_rows = []
        for by in range(self.y0 >> 2, hgt >> 2):
            bits = bytearray((nblk + 7) >> 3)
            for blk in range(nblk):
                ch = bool(keyframe)
                if not ch:
                    for y in range(by * 4, by * 4 + 4):
                        for x in (blk * 2, blk * 2 + 1):
                            gl, gr = game(prev_rows[y][x], prevd[y][x]); tl, tr = target[y][x]
                            if any(abs(a - b) > self.tol for a, b in zip(gl + gr, tl + tr)):
                                ch = True; break
                        if ch:
                            break
                changed[(by, blk)] = ch
                if not ch:
                    bits[blk >> 3] |= 1 << (blk & 7)
            cb_rows.append(bytes(bits))
        if self.y0 > 0:
            vert = [list(map(list, unpack(v, False))) for v in cur[self.y0 - 1]]; dvert = list(curd[self.y0 - 1])
        else:
            vert = [[[0], [0], [0]] for _ in range(nw)]; dvert = [0] * nw
        z = self.nearest(0, ft)
        rows_ops = []
        for y in range(self.y0, hgt):
            H = [[0], [0], [0]]; dh = 0
            row = cur[y]; drow = curd[y]; ops = []; x = 0
            seq = tm1enc.ops_seq(y & 3, self.bw, self.bt)
            for blk in range(nblk):
                if not changed[(y >> 2, blk)]:
                    for k in (0, 1):
                        pv = prev_rows[y][x]; pd = prevd[y][x]; row[x] = pv; drow[x] = pd
                        P = unpack(pv, False)
                        if k == 1:
                            H = [[P[c][0] - vert[x][c][0]] for c in range(3)]; dh = pd - dvert[x]
                        vert[x] = [list(P[c]) for c in range(3)]; dvert[x] = pd
                        x += 1
                    continue
                for si, op in enumerate(seq):
                    if op == 'C':
                        xs = []
                        for j in range(si + 1, len(seq)):
                            if seq[j] == 'C':
                                break
                            xs.append(x + len(xs))
                        dR = dB = 0.0; n = 0
                        for xx in xs:
                            tl, tr = target[y][xx]
                            R = vert[xx][0][0] + H[0][0]; G = vert[xx][1][0] + H[1][0]; B = vert[xx][2][0] + H[2][0]
                            d = dvert[xx] + dh
                            for t in (tl, tr):
                                dR += (t[0] - t[1]) - (R - G); dB += (t[2] - t[1]) - (B - G - d); n += 1
                        # ★다음 Y 들이 범위 안 값을 고를 수 있는 색만(크로마가 너무 크면 Y 가 어떤 값이든 0‥255 를 벗어난다)
                        # 크로마는 아래 줄(같은 블록의 Y 만 있는 줄)로도 세로로 이어진다 → |CR|·|CB| ≤ CMAX 로 묶어 밝기가 어디로 가도 범위 안
                        x0 = xs[0]
                        cR = vert[x0][0][0] + H[0][0] - (vert[x0][1][0] + H[1][0])
                        cB = vert[x0][2][0] + H[2][0] - (vert[x0][1][0] + H[1][0]) - (dvert[x0] + dh)
                        cands = [(dR / max(n, 1), dB / max(n, 1)), (0.5 * dR / max(n, 1), 0.5 * dB / max(n, 1)), (0.0, 0.0), (-cR, -cB)]
                        best_c = None
                        for tR, tB in cands:
                            pair, esc, add = self.pick_c(tR, tB)
                            worst = 0
                            for xx in xs:
                                R = vert[xx][0][0] + H[0][0] + add[0]; G = vert[xx][1][0] + H[1][0]; B = vert[xx][2][0] + H[2][0] + add[1]
                                d = dvert[xx] + dh
                                CR, CB = R - G, B - G - d
                                tl, tr = target[y][xx]                 # 목표 색만큼은 허용(채도 높은 색을 자르지 않게)
                                bR = max(CMAX, abs(tl[0] - tl[1]) + 10, abs(tr[0] - tr[1]) + 10)
                                bB = max(CMAX, abs(tl[2] - tl[1]) + 10, abs(tr[2] - tr[1]) + 10)
                                worst = max(worst, abs(CR) - bR, abs(CB) - bB)
                                if not (self.feasible(G + d, CR, CB) and self.feasible(G, CR, CB)):
                                    worst = max(worst, 999)
                            if best_c is None or worst < best_c[0]:
                                best_c = (worst, pair, esc, add)
                            if worst <= 0:
                                break
                        _, pair, esc, add = best_c
                        H[0][0] += add[0]; H[2][0] += add[1]
                        ops.append((blk, 'C', pair, esc))
                    else:
                        tl, tr = target[y][x]
                        R = vert[x][0][0] + H[0][0]; G = vert[x][1][0] + H[1][0]; B = vert[x][2][0] + H[2][0]
                        d = dvert[x] + dh
                        Ya, Yb = G + d, G; CR, CB = R - G, B - G - d
                        _, a, ea, da = self.side(Ya, CR, CB, tl, ydt, ft)
                        _, b, eb, db = self.side(Yb, CR, CB, tr, ydt, ft)
                        esc = None
                        if ea is not None or eb is not None:
                            if ea is None:
                                ea = z; da += ft[z]
                            if eb is None:
                                eb = z; db += ft[z]
                            esc = (ea, eb)
                        H[2][0] += da; H[0][0] += db; H[1][0] += db; dh += da - db
                        P = [vert[x][c][0] + H[c][0] for c in range(3)]
                        if not all(0 <= v <= 255 for v in P):
                            self.oob = getattr(self, 'oob', 0) + 1      # 드문 경우 — 그대로 둔다(게임은 성분 mod 256)
                        row[x] = pack([max(0, min(255, v)) for v in P[:1]], [max(0, min(255, P[1]))], [max(0, min(255, P[2]))], False) if not all(0 <= v <= 255 for v in P) else pack([P[0]], [P[1]], [P[2]], False)
                        vert[x] = [[P[0]], [P[1]], [P[2]]]
                        dvert[x] = d + da - db; drow[x] = dvert[x]          # 이 화소의 d = 위 d + 쌓인 dh
                        ops.append((blk, 'Y', (a, b), esc))
                        x += 1
            rows_ops.append(ops)
        return rows_ops, cb_rows


def target_rows(F, b16):
    return [[unpack(v, b16) for v in row] for row in F]


if __name__ == '__main__' and sys.argv[1] == 'test':
    # 검증 2: 원본 그대로를 목표로 띠만 다시 부호화 → 위쪽은 비트 일치, 띠는 오차·크기 보고
    import copy
    name = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 40; band = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    frs = tm1.avi_frames(os.path.join(tm1.ROOT, 'work', 'movie', 'avi', name + '.AVI'))
    A, B = tm1.Decoder(), tm1.Decoder()
    t0 = t1 = 0; maxerr = 0
    for k, (_, b) in enumerate(frs[:n]):
        if len(b) < 2:
            continue
        prevB = copy.deepcopy(B.frame) if B.frame else None
        fr = tm1enc.trace(A, b)
        if fr.nop:
            B.decode(b); continue
        y0 = fr.hgt - band
        tg = target_rows(A.frame, fr.b16)
        cur = [list(r) for r in A.frame]               # 위쪽은 원본과 같다(검증으로 확인)
        if prevB is None:
            prevB = [[0] * fr.nw for _ in range(fr.hgt)]
        E = BandEnc(A.tab, fr.h['deltaset'], fr.b16, fr.bw, fr.bt, y0)
        bops, bcb = E.encode(cur, prevB, tg, fr.key)
        rows = fr.rows[:y0] + bops
        cbits = (fr.cbits[:y0 >> 2] + bcb) if not fr.key else []
        nb = tm1enc.rebuild(fr, rows, cbits, E.cdict)
        B.decode(nb)
        up_ok = B.frame[:y0] == A.frame[:y0]
        me_ok = all((B.frame[y][x] ^ cur[y][x]) & 0x7FFFFFFF == 0 for y in range(y0, fr.hgt) for x in range(fr.nw))   # 31번 비트 = 디코더 >>1 쓰레기(화면 무관)
        err = 0
        for y in range(y0, fr.hgt):
            for x in range(fr.nw):
                a = unpack(A.frame[y][x], fr.b16); bb = unpack(B.frame[y][x], fr.b16)
                err = max(err, max(abs(a[c][l] - bb[c][l]) for c in range(3) for l in range(len(a[0]))))
        maxerr = max(maxerr, err)
        t0 += len(b); t1 += len(nb)
        if k % 10 == 0 or not up_ok or not me_ok:
            print(k, '위쪽', '같음' if up_ok else '★다름', '시뮬', '맞음' if me_ok else '★틀림', '띠 최대오차', err, len(b), '→', len(nb))
    print('크기 %d → %d (%.1f%%) · 띠 최대오차 %d' % (t0, t1, 100.0 * t1 / max(1, t0), maxerr))

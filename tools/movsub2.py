# -*- coding: utf-8 -*-
r"""VIRUS 동영상 자막 굽기 (2026-10-13) — 카오스 시드 tools/moviesub.py(실기 통과) 를 옮긴 것.
  ★tools/tm1sub.c(직접 만든 C 인코더)는 폐기: iddx·채널 범위(새턴은 B·G·R 로 묶어 범위 밖이면 원색 잡음)·탈출 뒤 0 을 하나씩 다시 밟음.
  부호화 = tools/tm1.py · tm1enc.py · tm1band.py(카오스 시드 복사, 성분이 늘 범위 안 — 디코더 구현 차이 회피).
  VIRUS 맞춤: 자막 = data/movie_ko.tsv(movsub.cues_of — 2줄씩 나눔·시간 비율) · 글꼴 movsub.STYLE(폭 320/120)
    · 덩어리 상한 = max(원본 avih 권장 버퍼, 원본 최대 덩어리) · ★CD 읽기 속도 예산(원본의 «누적 − 2배속×시간» 최대값을 안 넘게)
    · iddx 없는 영상(idx1 만) 도 처리 · 디스크마다 이름이 다른 사본 각자 이름으로.
  python tools/movsub2.py OPA [S042_1 …]   (없으면 전부) → work/build/d<N>/<이름>.AVI
  python tools/movsub2.py --test OPA 1000  → 프레임 1000 이 든 자막 장면만 인코딩해 막힘 확인(파일 안 씀, 몇 초)
"""
import collections, copy, os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tm1, tm1enc, tm1band, movsub
from PIL import Image, ImageDraw, ImageFont

BUILD = os.path.join(ROOT, 'work', 'build')
RATE = 307200.0 * 0.95          # 2배속 CD(2048×150 B/s)의 95%
MARGIN = 128 * 1024             # 원본 선행량에 더해 허용(새턴 CD 블록 자체 선행 버퍼 ~400KB — 카오스 시드는 예산 없이 +18% 실기 통과)


def chunks(d):
    """movi 안 덩어리 [(꼬리표, 데이터 시작, 크기)] (LIST 는 건너뜀)"""
    mv = tm1.movi_pos(d); lst = mv - 8
    end = lst + 8 + struct.unpack_from('<I', d, lst + 4)[0]
    i = mv + 4; out = []
    while i + 8 <= end:
        tag = d[i:i + 4]; n = struct.unpack_from('<I', d, i + 4)[0]
        if tag == b'LIST':
            out.append((tag, i + 8, 4)); i += 12; continue      # rec 머리 12바이트도 읽기 양에 셈
        out.append((tag, i + 8, n)); i += 8 + n + (n & 1)
    return out


def rate_budget(d, dt):
    """영상 프레임 k 마다 «앞으로 늘려도 되는 바이트» — min_{j≥k}(D − (누적(j) − R·j·dt))"""
    cum = 0; v = []
    for tag, o, n in chunks(d):
        cum += 8 + n + (n & 1)
        if tag[2:] in (b'dc', b'db'):
            v.append(cum - RATE * len(v) * dt)
    D = max(v)
    ms = [0.0] * (len(v) + 1); ms[len(v)] = 1e18
    for k in range(len(v) - 1, -1, -1):
        ms[k] = min(D - v[k], ms[k + 1])
    return ms


def render(base_rgb, w, hgt, lines, st, band):
    img = Image.frombytes('RGB', (w, hgt), base_rgb)
    if not lines:
        return img
    f = ImageFont.truetype(st[0], st[1]); d = ImageDraw.Draw(img)
    y = hgt - 2 - st[2] * len(lines)
    for ln in lines:
        x = (w - d.textlength(ln, font=f)) / 2
        d.text((round(x), y), ln, font=f, fill=(255, 255, 255), stroke_width=st[3], stroke_fill=(0, 0, 0))
        y += st[2]
    return img


def target_from(img, nw, hgt):
    px = img.load(); tg = []
    for y in range(hgt):
        row = []
        for x in range(nw):
            p0, p1 = px[2 * x, y], px[2 * x + 1, y]
            row.append(([p0[0] >> 3, p1[0] >> 3], [p0[1] >> 3, p1[1] >> 3], [p0[2] >> 3, p1[2] >> 3]))
        tg.append(row)
    return tg


def burn(src, cues, log=print, start=0, stop=None):
    d = open(src, 'rb').read()
    fr_all = tm1.avi_frames(src)
    h0 = tm1.header(next(b for _, b in fr_all if len(b) >= 2 and tm1.COMP[tm1.header(b)['compression']][0]))
    assert tm1.COMP[h0['compression']][0] in (1, 2), '16비트만'
    w, hgt = h0['xsize'], h0['ysize']
    st = movsub.STYLE[w]; band = hgt - st[4]
    ai = d.find(b'avih') + 8
    us = struct.unpack_from('<I', d, ai)[0]; dt = us / 1e6
    buf = max(struct.unpack_from('<I', d, ai + 28)[0], max(len(b) for _, b in fr_all))
    ms = rate_budget(d, dt)
    f = ImageFont.truetype(st[0], st[1])
    sc = movsub.split_cues(cues, f, w - 8)
    A, B = tm1.Decoder(), tm1.Decoder()
    out = []; extra = 0; t0 = time.time(); prev_lines = None; nre = 0; dropped = 0; over = 0
    for k, (off, b) in enumerate(fr_all):
        if stop is not None and k >= stop:
            break
        if k < start:                             # ★시험용: 자막 장면 앞까지는 원본을 풀기만(띠 = 원본) — 장면 하나를 몇 초에
            if len(b) >= 2 and tm1.COMP[tm1.header(b)['compression']][0]:
                A.decode(b); B.decode(b)
            out.append(b); continue
        t = k * dt
        c = next((c for c in sc if c[0] <= t < c[1]), None)
        lines = c[2] if c else None
        if not (len(b) >= 2 and tm1.COMP[tm1.header(b)['compression']][0]):
            out.append(b)                         # NOP·빈 덩어리 — 자막 바뀜은 다음 실제 프레임에서(VIRUS 는 NOP 드묾)
            if len(b) >= 2:
                A.decode(b); B.decode(b)
            continue
        if lines is None and A.frame is not None and B.frame is not None:
            if B.frame == A.frame or tm1.header(b)['kflags'] & tm1.FLAG_KEYFRAME:
                A.decode(b); B.decode(b); out.append(b); prev_lines = None
                continue
        prevB = copy.deepcopy(B.frame) if B.frame else None
        fr = tm1enc.trace(A, b)
        nw = len(A.frame[0]); y0 = hgt - band
        base = tm1.to_rgb(A.frame, True)
        cur = [list(r) for r in A.frame]
        if prevB is None:
            prevB = [[0] * nw for _ in range(hgt)]
        limit = int(min(buf, len(b) + ms[k] + MARGIN - extra))
        tol = None; coarse = 0; use = lines
        while True:
            tg = target_from(render(base, w, hgt, use, st, band), nw, hgt)
            E = tm1band.BandEnc(A.tab, A.key[0], True, fr.bw, fr.bt, y0, tol, coarse)
            force = set(); stuck = False
            while True:                               # 막히면 왼쪽 «건너뜀» 블록을 부호화로 바꿔 다시
                try:
                    bops, bcb = E.encode([list(r) for r in cur], prevB, tg, fr.key, force)
                    break
                except tm1band.Stuck as st_:
                    by = st_.y >> 2; cand = [bk for bk in range(st_.blk - 1, -1, -1) if (by, bk) not in force]
                    if not cand and (by, st_.blk) in force:
                        stuck = True; break
                    force.add((by, cand[0]) if cand else (by, st_.blk))
                    E = tm1band.BandEnc(A.tab, A.key[0], True, fr.bw, fr.bt, y0, tol, coarse)
            if stuck:                                 # 다 풀어도 막힘 → 이 프레임만 자막 빼고(목표 = 원래 화면)
                assert use is not None, ('막힘 못 풂', k)
                use = None; tol = None; coarse = 0; dropped += 1
                continue
            rows = fr.rows[:y0] + bops
            cbits = [] if fr.key else fr.cbits[:y0 >> 2] + bcb
            nb = tm1enc.rebuild(fr, rows, cbits, E.cdict)
            if len(nb) <= limit:
                break
            if E.tol < 16:
                tol = E.tol * 2
            elif coarse < 8:
                coarse += 1
            elif use is not None:                 # 그래도 넘치면 이 프레임만 자막 빼고(목표 = 원본) 다시
                use = None; tol = None; coarse = 0; dropped += 1
            elif len(nb) <= buf:                      # 속도 예산은 추정(원본부터 2배속 가정을 넘는 영상 — S401_1) → 버퍼 상한 안이면 받음
                over += 1; break
            else:
                raise SystemExit('⛔ 프레임 %d: %d B > 버퍼 %d' % (k, len(nb), buf))
        B.decode(nb)
        assert all((B.frame[y][x] ^ A.frame[y][x]) & 0x7FFF7FFF == 0 for y in range(y0) for x in range(nw)), (k, '위쪽 불일치')
        extra += len(nb) - len(b); nre += 1
        out.append(nb); prev_lines = lines
        if k % 200 == 0:
            log('  %d/%d %.0fs' % (k, len(fr_all), time.time() - t0))
    return out, nre, dropped


def write_avi(src, frames_new, dst):
    """영상 덩어리만 바꿔 쓰기 — ★LIST 'rec ' 묶음 보존(크기 갱신), 색인(idx1·iddx)은 «원래 항목 순서·깃발 그대로» 각 항목의
    원래 자리(movi 기준)를 새 자리·크기로 옮김(rec 항목 포함). avih/strh 권장 버퍼 = max(원래, 새 최대 덩어리).
    (카오스 시드 write_avi 는 rec 묶음 머리를 옛 크기로 복사하고 색인에서 rec 항목을 뺐다 — VIRUS 15편이 그 꼴, 2026-10-13)"""
    d = open(src, 'rb').read()
    mv = tm1.movi_pos(d); lst = mv - 8
    end_movi = lst + 8 + struct.unpack_from('<I', d, lst + 4)[0]
    fi = iter(frames_new)
    remap = {}                      # 원래 «movi 기준 오프셋»(머리 자리) → (새 오프셋, 새 크기)
    body = bytearray()

    def walk(i, end):
        while i + 8 <= end:
            tag = d[i:i + 4]; n = struct.unpack_from('<I', d, i + 4)[0]
            o_old = i - mv
            if tag == b'LIST':
                at = len(body); body.extend(d[i:i + 12])           # 머리(크기는 뒤에 고침)
                walk(i + 12, i + 8 + n)
                sz = len(body) - at - 8
                struct.pack_into('<I', body, at + 4, sz)
                remap[o_old] = (at + 4, sz)
                i += 8 + n + (n & 1); continue
            data = d[i + 8:i + 8 + n]
            if tag[2:] in (b'dc', b'db'):
                data = next(fi)
            at = len(body)
            body.extend(tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b''))
            remap[o_old] = (at + 4, len(data))
            i += 8 + n + (n & 1)

    walk(mv + 4, end_movi)
    assert next(fi, None) is None, '새 덩어리가 남음'
    head = bytearray(d[:lst])
    movi = b'LIST' + struct.pack('<I', len(body) + 4) + b'movi' + bytes(body)

    def fix_index(buf, p, n):
        """buf[p:p+n] 의 16바이트 항목들: 오프셋(movi 기준, 첫 덩어리 = 4) → 새 값"""
        for q in range(p, p + n, 16):
            off = struct.unpack_from('<I', buf, q + 8)[0]
            no, ns = remap[off]
            struct.pack_into('<II', buf, q + 8, no, ns)

    tail = b''
    oi = d.find(b'idx1', end_movi)
    if oi >= 0:
        on = struct.unpack_from('<I', d, oi + 4)[0]
        ib = bytearray(d[oi + 8:oi + 8 + on]); fix_index(ib, 0, on)
        tail = b'idx1' + struct.pack('<I', on) + bytes(ib) + d[oi + 8 + on:]
    xi = head.find(b'iddx')                   # ★movi 앞 idx1 사본 — 재생기가 이걸 읽는다
    if xi >= 0:
        fix_index(head, xi + 8, struct.unpack_from('<I', head, xi + 4)[0])
    vmax = max(len(f) for f in frames_new)
    ai = head.find(b'avih') + 8
    struct.pack_into('<I', head, ai + 28, max(vmax, struct.unpack_from('<I', head, ai + 28)[0]))
    si = head.find(b'strh') + 8
    if head[si:si + 4] == b'vids':
        struct.pack_into('<I', head, si + 36, max(vmax, struct.unpack_from('<I', head, si + 36)[0]))
    out = head + movi + tail
    struct.pack_into('<I', out, 4, len(out) - 8)
    # 검산: idx1·iddx 항목마다 «movi+오프셋» 자리 꼬리표·크기 = 항목
    o = bytes(out); mv2 = tm1.movi_pos(o)
    for p in (o.find(b'iddx', 0, mv2), o.find(b'idx1', mv2 + len(body))):
        if p < 0:
            continue
        n = struct.unpack_from('<I', o, p + 4)[0]
        for q in range(p + 8, p + 8 + n, 16):
            tag = o[q:q + 4]; off, sz = struct.unpack_from('<II', o, q + 8)
            h = mv2 + off
            got = o[h + 8:h + 12] if o[h:h + 4] == b'LIST' else o[h:h + 4]
            assert got == tag and struct.unpack_from('<I', o, h + 4)[0] == sz, ('색인 불일치', q)
    open(dst, 'wb').write(out)
    return len(d), len(out)


def test(nm, frame):
    by = movsub.cues_of()
    vid = next(v for v in by if any(c.split(':')[1] == nm for c in v.split()))
    n0 = vid.split()[0].split(':')[0]
    src = os.path.join(ROOT, 'work', 'movie', n0, nm + '.AVI')
    d = open(src, 'rb').read(); us = struct.unpack_from('<I', d, d.find(b'avih') + 8)[0] / 1e6
    t = frame * us
    a, e, _ = max((c for c in by[vid] if c[0] - 1 <= t), key=lambda c: c[0])   # 그 프레임 앞에서 시작한 마지막 장면(자막 끝난 뒤 복원 구간 포함)
    k0, k1 = max(0, int(a / us) - 2), max(int(e / us) + 15, frame + 5)
    t0 = time.time()
    fs, nre, dropped = burn(src, by[vid], start=k0, stop=k1)
    print('%s 프레임 %d‥%d 통과 · 다시 짠 %d · %.1fs' % (nm, k0, k1, nre, time.time() - t0))


def one(job):
    """영상 하나(병렬 일꾼) — 막혀도 멈추지 않고 사유를 돌려줌"""
    vid, cues = job
    copies = [c.split(':') for c in vid.split()]
    try:
        return do_one(copies, cues)
    except BaseException as e:
        import traceback
        return '⛔%s %s %s' % (copies[0][1], type(e).__name__, str(e)[:200] or traceback.format_exc()[-300:])


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if sys.argv[1:2] == ['--test']:
        return test(sys.argv[2], int(sys.argv[3]))
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    by = movsub.cues_of()
    jobs = [(vid, cues) for vid, cues in by.items()
            if not args or any(c.split(':')[1] in args for c in vid.split())]
    jobs.sort(key=lambda j: -os.path.getsize(os.path.join(ROOT, 'work', 'movie', *j[0].split()[0].split(':')) + '.AVI'))
    import multiprocessing as mp
    nproc = int(next((a.split('=')[1] for a in sys.argv if a.startswith('--j=')), '6'))
    with mp.Pool(nproc) as pool:
        for r in pool.imap_unordered(one, jobs):
            print(r, flush=True)


def do_one(copies, cues):
    if True:
        n0, nm = copies[0]
        src = os.path.join(ROOT, 'work', 'movie', n0, nm + '.AVI')
        t0 = time.time()
        fs, nre, dropped = burn(src, cues, log=lambda *a: None)
        tmp = os.path.join(ROOT, 'work', 'movsub', nm + '.AVI')
        a, b = write_avi(src, fs, tmp)
        for n, cn in copies:
            dd = os.path.join(BUILD, n); os.makedirs(dd, exist_ok=True)
            open(os.path.join(dd, cn + '.AVI'), 'wb').write(open(tmp, 'rb').read())
        return '%-10s %s 다시 짠 프레임 %d · 자막 뺀 프레임 %d · %d → %d B (%+.0f%%) · %.0fs' % (
            nm, ','.join(n for n, _ in copies), nre, dropped, a, b, (b / a - 1) * 100, time.time() - t0)


if __name__ == '__main__':
    main()

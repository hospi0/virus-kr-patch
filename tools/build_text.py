# -*- coding: utf-8 -*-
r"""VIRUS 본편 글 되넣기 → work/build/{VIRUS.BIN, VIRUS.IDX, DICTIO.BIN, FONT.DAT}
  번역 data/virus_ko.tsv(vmerge 결과) · 자리 work/text/occ.tsv(ID·블롭·문자열 자리·포인터 자리들).
  · 글꼴: tools/vfont.py — 한글을 1수준 한자 칸에, 나머지 한자 칸은 빈칸.
  · 블롭(모듈 45 + DICTIO)마다: 번역이 원문과 같은 자리는 손대지 않음. 바뀐 자리의 원래 바이트 범위(문자열+NUL)를 비우고
    (같은 범위 안에 손대지 않는 자리가 겹치면 그 범위는 비우지 않음) 새 문자열(같은 바이트는 하나로)을 큰 것부터 빈 곳에 채움.
    남는 문자열은 모듈 끝 + BSS 틈(모듈 0x800 · DICTIO 0x100) 뒤에 붙임 → 모듈 크기 증가(모듈 바로 뒤 RAM 은 모듈 변수(BSS)라 띄움).
    포인터(u32 BE, 기준 + 자리) 를 새 자리로.
  ★모듈 끝 뒤 = BSS(약 0x200) + 힙(장면마다 동적 할당 — 원본 V01 에서 끝+0x19800 자리 사용). 모듈이 커지면 힙이 줄어
    큰 할당 실패 → 리셋(2026-10-13 V01 «버튼» 대사 뒤 BIOS 로 튕김, V01 +0x1700 증가판). 그래서 큰 모듈은 크기 증가 금지,
    끝이 GROW_MAX 아래인 작은 모듈만 조금 커져도 됨(최대 모듈 V01 보다 힙이 훨씬 넉넉). DICTIO 는 0x290000 앞까지.
  · 1ST_READ.PRG: 대화 상자 줄바꿈 세로 3칸(24px, 루비 자리) → 2칸(16px) — 한글판은 루비가 없어 4줄이 원본 3줄 높이에.
  · 시스템 글(1ST_READ 안 메뉴·덧프로그램 S*PROG·TESHMES·ITEMDATA 등): tools/build_sys.py(제자리 우선, 파일 크기 그대로).
  · VIRUS.BIN 은 모듈을 원래 순서대로 섹터 경계에 다시 쌓고 VIRUS.IDX(섹터·크기) 갱신.
  python tools/build_text.py
"""
import collections, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import vfont, build_sys

SRC = os.path.join(ROOT, 'work', 'disc1')
OUT = os.path.join(ROOT, 'work', 'build')
GAP = {'DIC': 0x100}
MODGAP = 0x800
GROW_MAX = 0x2C8000                 # 커져도 되는 모듈 새 끝 한계(원본 최대 V01 0x2D67D4·V06 0x2CEAE0 보다 아래)
DIC_MAX = 0x28F000                  # DICTIO(0x280000) 끝 한계 — 0x290000 부터 다른 자료
# 1ST_READ.PRG(적재 0x06004000) 손질: (주소, 원래 u16, 새 u16)
PRG_PATCH = [(0x0600D334, 0x7103, 0x7102)]   # 대화 줄바꿈 ADD #3,R1 → ADD #2,R1 (+0x0C 줄 칸)


def load():
    ko = {}; ja = {}
    for l in open(os.path.join(ROOT, 'data', 'virus_ko.tsv'), encoding='utf-8').read().splitlines()[1:]:
        c = l.split('\t'); ko[c[0]] = c[2]; ja[c[0]] = c[1]
    occ = collections.defaultdict(list)
    for l in open(os.path.join(ROOT, 'work', 'text', 'occ.tsv'), encoding='utf-8').read().splitlines()[1:]:
        rid, blob, site, ptrs = l.split('\t')
        occ[blob].append((int(site, 16), rid, [int(p, 16) for p in ptrs.split()]))
    return ko, ja, occ


def rebuild(name, m, base, sites, ko, ja, cmap):
    m = bytearray(m)
    keep = set(); change = []; skipped = []
    # 진짜 포인터 = 4바이트 정렬(리터럴 풀·구조체). 2바이트 정렬 «포인터»는 u16 표가 우연히 맞은 것 → 버림
    sites = [(s, rid, [p for p in ptrs if p % 4 == 0]) for s, rid, ptrs in sites]
    allptr = [p for _, _, ps in sites for p in ps]
    for s, rid, ptrs in sites:
        if not ptrs:
            keep.add(s); continue
        e = m.index(bytes(1), s) + 1
        if ko[rid] == ja[rid] or any(s < p + 4 and p < e for p in allptr):
            keep.add(s)                 # 같거나, 문자열 범위 안에 포인터가 있음(가짜 문자열) → 손대지 않음
            if ko[rid] != ja[rid]:
                skipped.append(rid)
        else:
            change.append((s, rid, ptrs))
    if skipped:
        print('  %s 범위 안에 포인터가 있어 건너뛴 자리 %d: %s' % (name, len(skipped), ' '.join(skipped[:5])))
    # 비울 범위
    keep_ranges = [(s, m.index(b'\0', s) + 1) for s in keep]
    free = []
    for s, rid, ptrs in change:
        e = m.index(b'\0', s) + 1
        if any(a < e and s < b for a, b in keep_ranges):
            continue
        free.append([s, e])
    free.sort(); merged = []
    for a, b in free:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in merged:
        m[a:b] = bytes(b - a)
    # 새 문자열
    want = collections.OrderedDict()
    for s, rid, ptrs in change:
        want.setdefault(vfont.encode(ko[rid], cmap, set(ja[rid])) + b'\0', []).append((s, ptrs))
    holes = [[a, b] for a, b in merged]
    place = {}; over = bytearray()
    ovbase = (len(m) + GAP.get(name, MODGAP) + 3) & ~3
    for data in sorted(want, key=len, reverse=True):      # 큰 것부터, 가장 꼭 맞는 구멍에(best-fit)
        fit = [h for h in holes if h[1] - h[0] >= len(data)]
        if fit:
            h = min(fit, key=lambda h: h[1] - h[0])
            place[data] = h[0]; m[h[0]:h[0] + len(data)] = data; h[0] += len(data)
        else:
            place[data] = ovbase + len(over); over += data
    if over:
        m += bytes(ovbase - len(m)) + over
    npt = 0
    for data, users in want.items():
        for s, ptrs in users:
            for p in ptrs:
                v, = struct.unpack_from('>I', m, p)
                assert v == base + s, (name, hex(p), hex(v), hex(base + s))
                struct.pack_into('>I', m, p, base + place[data]); npt += 1
    return bytes(m), len(change), npt, len(over)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    os.makedirs(OUT, exist_ok=True)
    ko, ja, occ = load()
    cmap = vfont.build_map([ko[r] for r in ko if ko[r] != ja[r]] + build_sys.texts())   # 본편 + 시스템 글
    open(os.path.join(OUT, 'FONT.DAT'), 'wb').write(vfont.render_font(cmap, open(os.path.join(SRC, 'FONT.DAT'), 'rb').read()))
    print('글꼴: 한글 등 %d자 → 1수준 한자 칸 %d개 중' % (len(cmap), len(vfont.SLOTS)))
    # 모듈
    idx = open(os.path.join(SRC, 'VIRUS.IDX'), 'rb').read(); vb = open(os.path.join(SRC, 'VIRUS.BIN'), 'rb').read()
    ent = [struct.unpack_from('>II', idx, 8 * k) for k in range(len(idx) // 8)]
    order = sorted(range(len(ent)), key=lambda k: ent[k][0])
    new = {}
    grow = 0
    for k in range(len(ent)):
        s, sz = ent[k]; m = vb[s * 2048:s * 2048 + sz]
        nm, nch, npt, nov = rebuild('V%02d' % k, m, 0x002A0000, occ.get('V%02d' % k, []), ko, ja, cmap)
        new[k] = nm
        if nov and 0x2A0000 + len(nm) > GROW_MAX:
            sys.exit('⛔ V%02d 넘친 글 %d B → 끝 0x%X > 0x%X (큰 모듈은 크기 증가 금지 — 힙 부족)' % (k, nov, 0x2A0000 + len(nm), GROW_MAX))
        if nov:
            grow += 1
            print('  V%02d %d → %d B (넘친 글 %d B, 모듈 뒤 0x%X)' % (k, sz, len(nm), nov, 0x2A0000 + len(nm)))
    out = bytearray(); nidx = bytearray()
    sec = {}
    for k in order:
        sec[k] = len(out) // 2048
        out += new[k]; out += bytes(-len(out) % 2048)
    for k in range(len(ent)):
        nidx += struct.pack('>II', sec[k], len(new[k]))
    nidx += idx[len(ent) * 8:]
    print('VIRUS.BIN %d → %d B (원래 %d섹터 → %d섹터) · 커진 모듈 %d' % (len(vb), len(out), (len(vb) + 2047) // 2048, len(out) // 2048, grow))
    open(os.path.join(OUT, 'VIRUS.BIN'), 'wb').write(out)
    open(os.path.join(OUT, 'VIRUS.IDX'), 'wb').write(nidx)
    prg = bytearray(open(os.path.join(SRC, '1ST_READ.PRG'), 'rb').read())
    for a, o, n in PRG_PATCH:
        assert struct.unpack_from('>H', prg, a - 0x06004000)[0] == o, hex(a)
        struct.pack_into('>H', prg, a - 0x06004000, n)
    print('1ST_READ.PRG 손질 %d곳' % len(PRG_PATCH))
    print('시스템 글(data/sys_ko.tsv):')
    sysout, bad, squeezed = build_sys.build(cmap, bytes(prg))
    open(os.path.join(ROOT, 'work', 'check', 'sys_squeezed.tsv'), 'w', encoding='utf-8').write(''.join(x + '\n' for x in squeezed))
    if bad:
        for b in bad:
            print('  ⛔', *b)
        sys.exit('⛔ 시스템 글 %d줄이 자리에 안 들어감' % len(bad))
    for f, b in sysout.items():
        open(os.path.join(OUT, f), 'wb').write(b)
    d = open(os.path.join(SRC, 'DICTIO.BIN'), 'rb').read()
    nd, nch, npt, nov = rebuild('DIC', d, 0x00280000, occ.get('DIC', []), ko, ja, cmap)
    if 0x280000 + len(nd) > DIC_MAX:
        sys.exit('⛔ DICTIO 끝 0x%X > 0x%X' % (0x280000 + len(nd), DIC_MAX))
    open(os.path.join(OUT, 'DICTIO.BIN'), 'wb').write(nd)
    print('DICTIO.BIN %d → %d B (넘친 글 %d B)' % (len(d), len(nd), nov))


if __name__ == '__main__':
    main()

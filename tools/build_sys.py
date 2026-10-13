# -*- coding: utf-8 -*-
r"""VIRUS 본편 밖 글(시스템 메시지) 되넣기 — data/sys_ko.tsv(smerge 결과) × work/text/sys_occ.tsv(자리) + data/sys_extra.tsv.
  적재 기준(1ST_READ 의 적재 호출로 확인, 2026-10-13): 1ST_READ 0x06004000 · 덧프로그램 S*PROG/AIS_PROG/POLMAP 0x2D0000 ·
    POLMAP2 0x2DC000 · TESHMES 0x293000(추출 때 추정 0x290000 은 우연 일치 — 틀림) · ITEMDATA 0x29E000.
  포인터 = 같은 파일 안 4바이트 정렬 u32 BE == 기준+자리 (여기서 다시 셈). TESHMES 는 1ST_READ 코드의 포인터도 함께 고침.
  · 옮길 수 있는 글(포인터 있음 · 범위 안에 포인터 없음 · VIRUS.BIN(상주 모듈)·다른 파일이 가리키지 않음):
      바뀐 것 전부 원래 범위(글+NUL)를 비우고(옮기는 글끼리 사이 4바이트 미만 정렬 틈은 합침) 큰 것부터 best-fit, 포인터 갱신.
  · 그 밖(포인터 없음 등): 제자리, 예산 = 원문 글 길이(정렬 채움은 안 씀). 남는 바이트 0.
  · ITEMDATA: 이름 = 40바이트 레코드(0x00‥0xDE7)의 20바이트 칸(+8‥+0x1B, NUL 뒤 «　» 채움) /
              설명 = 0xDE8‥끝, NUL 하나로 이어진 순차 목록 → 통째로 다시 씀(순서·개수 그대로).
              ★설명은 게임이 «원래 위치»로 찾으므로 제자리·원문 길이 안(짧은 번역 data/sys_short.tsv). 파일 크기 그대로.
  · 넘치면 «줄임»(그 글만): 글자 사이 «　»(2B, 12px) → 게임의 띄어쓰기 코드 <u>(1B, 8px), 줄바꿈 앞·글 끝 «　» 지움. 그래도 넘치면 ⛔.
  파일 크기는 그대로(ITEMDATA 만 예외).
  build_text.py 가 부름: build(cmap, prg) → ({파일: 바이트}, ⛔ 목록, 줄인 ID 목록)
"""
import collections, os, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disc, vfont

BASE = {'1ST_READ.PRG': 0x06004000, 'TESHMES.BIN': 0x293000, 'POLMAP2.BIN': 0x2DC000, 'ITEMDATA.BIN': 0x29E000}
OVL = 0x2D0000
ITEM_DESC = 0xDE8
ITEM_END = 0x29FE00          # ITEMDATA 새 끝 한계(모듈 0x2A0000 앞, 여유 0x200)


def load():
    ko = {}; ja = {}
    for l in open(os.path.join(ROOT, 'data', 'sys_ko.tsv'), encoding='utf-8').read().splitlines()[1:]:
        c = l.split('\t'); ko[c[0]] = c[2]; ja[c[0]] = c[1]
    occ = collections.defaultdict(list)
    for l in open(os.path.join(ROOT, 'work', 'text', 'sys_occ.tsv'), encoding='utf-8').read().splitlines()[1:]:
        rid, n, f, site, ptrs, base = l.split('\t')
        occ[f].append((int(site, 16), rid))
    for l in open(os.path.join(ROOT, 'data', 'sys_extra.tsv'), encoding='utf-8').read().splitlines():
        if l.strip() and not l.startswith('#'):
            rid = l.split('\t')[0]
            tag, site = rid.rsplit('_', 1)
            f = tag + ('.PRG' if tag == '1ST_READ' else '.BIN')
            if (int(site, 16), rid) not in occ[f]:
                occ[f].append((int(site, 16), rid))
    return ko, ja, occ


def texts():
    ko, ja, _ = load()
    return [ko[r] for r in ko if ko[r] != ja[r]]


def squeeze(K):
    """넘친 글 줄이기: 줄바꿈 앞·글 끝 «　» 지움, 글자 사이·색 코드 옆 «　» → <u>"""
    K = re.sub(r'　+(?=<[^<>]*n[^<>]*>)', '', K)
    K = re.sub(r'　+((?:<[^<>]*>)*)$', r'\1', K)
    K = re.sub(r'(?<=[^　<>])　(?=[^　<>])', '<u>', K)
    K = re.sub(r'(?<=<c\d>)　(?=[^　<>])|(?<=[^　<>])　(?=<c\d>)', '<u>', K)
    return K


class Enc:
    def __init__(self, ko, ja, cmap):
        self.ko, self.ja, self.cmap = ko, ja, cmap
        self.squeezed = set()

    def __call__(self, rid, budget=None):
        """budget 넘으면(0 = 무조건) 줄인 꼴로"""
        b = vfont.encode(self.ko[rid], self.cmap, set(self.ja[rid]))
        if budget is not None and len(b) > budget:
            b2 = vfont.encode(squeeze(self.ko[rid]), self.cmap, set(self.ja[rid]))
            if len(b2) < len(b):
                self.squeezed.add(rid)
                return b2
        return b


def u32_map(d):
    out = collections.defaultdict(list)
    for o in range(0, len(d) - 3, 4):
        out[struct.unpack_from('>I', d, o)[0]].append(o)
    return out


def other_refs(D, files):
    """→ (VIRUS.BIN(상주 모듈) u32 값, 1ST_READ 밖 모든 파일(.AVI·.DAT 빼고)의 0x0600xxxx 값)"""
    vb = set(u32_map(D.read(*files['VIRUS.BIN'])))
    hw = set()
    for p, (l, sz) in files.items():
        if p == '1ST_READ.PRG' or p.endswith(('.AVI', '.DAT')):
            continue
        for v in u32_map(D.read(l, sz)):
            if 0x06004000 <= v < 0x06080000:
                hw.add(v)
    return vb, hw


def pack(holes, datas):
    """큰 것부터 best-fit → 자리 목록(실패면 None)"""
    hs = [list(h) for h in holes]; at = [None] * len(datas)
    for k in sorted(range(len(datas)), key=lambda k: -len(datas[k])):
        n = len(datas[k])
        fit = [h for h in hs if h[1] - h[0] >= n]
        if not fit:
            return None
        h = min(fit, key=lambda h: h[1] - h[0]); at[k] = h[0]; h[0] += n
    return at


def rebuild(name, d, sites, enc, refs, prg):
    """prg = 1ST_READ bytearray(TESHMES 를 가리키는 포인터를 함께 고침)"""
    m = bytearray(d)
    base = BASE.get(name, OVL)
    pv = u32_map(d)
    xp = u32_map(prg) if name == 'TESHMES.BIN' else {}
    allptr = [o for v, os_ in pv.items() for o in os_ if base <= v < base + len(d)]
    bad = []; inplace = 0
    uniq = dict((s, rid) for s, rid in sites)
    movable = []; fixed = []
    for s, rid in sorted(uniq.items()):
        if enc.ko[rid] == enc.ja[rid]:
            continue
        e = m.index(b'\0', s)
        # ★1ST_READ 의 값 == 기준(자리 0)은 «파일 적재 주소» 인수(0x601C394·0x6008DEC = 0x293000) — 포인터 아님.
        #   2026-10-13 시험판 6 이 이걸 고쳐 TESHMES 가 0x2954BA 에 실려 부팅 멈춤.
        ptrs = [('f', p) for p in pv.get(base + s, [])] + [('x', p) for p in xp.get(base + s, []) if s]
        inside = any(s < p + 4 and p <= e for p in allptr)
        ext = (base + s) in (refs[1] if name == '1ST_READ.PRG' else refs[0])
        if ptrs and not inside and not ext:
            movable.append((s, e, rid, ptrs))
        else:
            fixed.append((s, e, rid, '포인터 없음' if not ptrs else '옮기기 불가(%s)' % ('범위 안 포인터' if inside else '다른 파일이 가리킴')))
    for s, e, rid, why in fixed:
        new = enc(rid, e - s)
        if len(new) > e - s:
            bad.append((rid, len(new) - (e - s), '제자리·%s %dB 넘침' % (why, len(new) - (e - s))))
            continue
        m[s:s + len(new)] = new; m[s + len(new):e + 1] = bytes(e + 1 - s - len(new)); inplace += 1
    holes = []
    for s, e, rid, ptrs in movable:
        m[s:e + 1] = bytes(e + 1 - s); holes.append([s, e + 1])
    holes.sort(); merged = []
    for a, b in holes:      # 옮기는 글끼리 사이의 정렬 틈(0, 4바이트 미만)은 합침
        if merged and a <= merged[-1][1] + 3 and not any(m[merged[-1][1]:a]):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    holes = merged
    datas = [enc(rid) + b'\0' for s, e, rid, ptrs in movable]
    plan = pack(holes, datas)
    for k in sorted(range(len(datas)), key=lambda k: -len(datas[k])):      # 안 들어가면 큰 것부터 하나씩 줄임
        if plan is not None:
            break
        datas[k] = enc(movable[k][2], 0) + b'\0'
        plan = pack(holes, datas)
    if plan is None:
        bad.append((name, sum(map(len, datas)) - sum(b - a for a, b in holes), '옮길 글 %d개가 빈 곳에 안 들어감' % len(datas)))
        return bytes(m), inplace, 0, bad
    for (s, e, rid, ptrs), data, at in zip(movable, datas, plan):
        m[at:at + len(data)] = data
        for kind, p in ptrs:
            buf = m if kind == 'f' else prg
            v, = struct.unpack_from('>I', buf, p)
            assert v == base + s, (name, kind, hex(p), hex(v), hex(base + s))
            struct.pack_into('>I', buf, p, base + at)
    assert len(m) == len(d)
    return bytes(m), inplace, len(movable), bad


def rebuild_item(d, sites, enc):
    m = bytearray(d); bad = []; n = 0
    uniq = dict((s, rid) for s, rid in sites)
    for s, rid in sorted(uniq.items()):
        if s >= ITEM_DESC or enc.ko[rid] == enc.ja[rid]:
            continue
        g = s if d[s:s + 1] == b'g' else s + 1            # 추출이 머리 끝 바이트(I·, 등)를 붙여 잡은 자리
        rec = g - 8; end = rec + 0x1C
        assert d[g:g + 1] == b'g' and rec % 0x28 == 0, (rid, hex(s))
        new = enc(rid, end - s - 1)
        if len(new) + 1 > end - s:
            bad.append((rid, len(new) + 1 - (end - s), '이름 칸(20B) %dB 넘침' % (len(new) + 1 - (end - s)))); continue
        pad = end - s - len(new) - 1
        m[s:end] = new + b'\0' + b'\x81\x40' * (pad // 2) + b' ' * (pad % 2); n += 1      # 홀수 채움도 NUL 아님
    # 설명 목록(0xDE8‥): 게임이 «원래 위치»로 찾음(2026-10-13 무기 교환 «설명 없음» — 통째로 다시 쓴 판에서 칼 설명을 원래 0x29F770 에서 읽음)
    #   → 제자리·원문 길이 안. 남는 자리는 NUL 앞 «　»/<u> 로 채워 NUL 개수(순차 세기)도 원본과 같게.
    for s, rid in sorted(uniq.items()):
        if s < ITEM_DESC or enc.ko[rid] == enc.ja[rid]:
            continue
        e = m.index(b'\0', s)
        new = enc(rid, e - s)
        if len(new) > e - s:
            bad.append((rid, len(new) - (e - s), '설명 제자리 %dB 넘침' % (len(new) - (e - s)))); continue
        pad = e - s - len(new)
        m[s:e] = new + b'\x81\x40' * (pad // 2) + b'u' * (pad % 2); n += 1   # «　» + 홀수면 <u>
    return bytes(m), n, 0, bad


def build(cmap, prg):
    """→ ({파일: 바이트}, ⛔ 목록, 줄인 ID)"""
    ko, ja, occ = load()
    D = disc.Disc()
    files = {p: (l, sz) for p, l, sz in D.walk()}
    refs = other_refs(D, files)
    enc = Enc(ko, ja, cmap)
    out = {}; allbad = []
    prg = bytearray(prg)
    for f in ['1ST_READ.PRG'] + sorted(x for x in occ if x != '1ST_READ.PRG'):
        sites = occ[f]
        d = bytes(prg) if f == '1ST_READ.PRG' else D.read(*files[f])
        if f == 'ITEMDATA.BIN':
            nd, ni, mv, bad = rebuild_item(d, sites, enc)
        else:
            nd, ni, mv, bad = rebuild(f, d, sites, enc, refs, prg)
        if f == '1ST_READ.PRG':
            prg[:] = nd
        else:
            out[f] = nd
        allbad += [(f,) + b for b in bad]
        grow = ' · 크기 %d → %d' % (len(d), len(nd)) if len(nd) != len(d) else ''
        print('  %-14s 제자리 %3d · 옮김 %3d%s%s' % (f, ni, mv, grow, ' · ⛔%d' % len(bad) if bad else ''))
    out['1ST_READ.PRG'] = bytes(prg)        # TESHMES 포인터까지 고친 것
    print('  띄어쓰기 줄임(«　»→<u>) %d줄' % len(enc.squeezed))
    return out, allbad, sorted(enc.squeezed)

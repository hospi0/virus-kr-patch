# -*- coding: utf-8 -*-
r"""VIRUS 본편 밖 글 추출 — 1ST_READ.PRG(메뉴·상점·몬스터 설명·컨티뉴 등) + 텍스트 든 BIN(ITEMDATA·TESHMES·POLMAP·S*PROG 등).
  모집단: 0 종료·cp932 온전·가나 2자 이상 문자열(extract.show 로 표시·왕복). 세 장 모두 훑고 같은 내용 파일은 한 번.
  문자열 시작 = 그 파일 안 u32 BE 포인터가 가리키는 자리(적재 기준은 «포인터−자리» 최빈값으로 추정, 1ST_READ 는 0x06004000).
  포인터가 없는 문자열은 앞쪽 찌꺼기(«-5舂…» 처럼 앞 데이터 꼬리)를 첫 제어 코드 m/q 자리에서 자름.
  출력: my files/tsv/sys_NNN.tsv (20 KB 단위, ID·자리수·원문·번역) · work/text/sys_occ.tsv (ID·디스크·파일·자리·포인터 자리들·적재 기준)
  python tools/extract_sys.py
"""
import collections, os, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disc
from extract import show

TSV = os.path.join(ROOT, 'my files', 'tsv'); TXT = os.path.join(ROOT, 'work', 'text')
SKIP = ('VIRUS.BIN', 'DICTIO.BIN', 'VIRUS.IDX')
KANA = re.compile(r'[ぁ-ヾ]')


def candidates(d):
    """[(자리, 끝)] — 0 으로 끝나는 cp932 글 덩어리(가나 2자 이상)"""
    out = []; i = 0; n = len(d)
    while i < n:
        j = i; nj = 0
        while j < n:
            c = d[j]
            if 0x20 <= c < 0x7f:
                j += 1; continue
            if (0x81 <= c <= 0x9f or 0xe0 <= c <= 0xef) and j + 1 < n and 0x40 <= d[j + 1] <= 0xfc and d[j + 1] != 0x7f:
                j += 2; nj += 1; continue
            break
        if nj and j < n and d[j] == 0:
            out.append((i, j)); i = j + 1
        else:
            i = j if j > i else i + 1
    return out


def ptr_table(d):
    t = collections.defaultdict(list)
    for o in range(0, len(d) - 3, 2):
        t[struct.unpack_from('>I', d, o)[0]].append(o)
    return t


def strings(name, d):
    cands = candidates(d)
    pt = ptr_table(d)
    if name == '1ST_READ.PRG':
        base = 0x06004000
    else:                                  # 포인터−자리 최빈값(가나 든 덩어리 안 자리들로)
        diff = collections.Counter()
        vals = [v for v in pt if v >= 0x200000]
        for a, e in cands:
            if len(KANA.findall(d[a:e].decode('cp932', 'replace'))) < 2:
                continue
            for v in vals:
                k = v - a
                if k >= 0 and (k & 0xFFFF) == 0:
                    diff[k] += 1
        base = diff.most_common(1)[0][0] if diff and diff.most_common(1)[0][1] >= 2 else None
    out = []
    for a, e in cands:
        starts = []
        if base is not None:
            starts = [x for x in range(a, e) if base + x in pt and any(p % 4 == 0 for p in pt[base + x])]
        if not starts:
            m = re.search(rb'q?z?\d*m\d{4}', d[a:e])
            starts = [a + m.start()] if m and m.start() > 0 and d[a + m.start() - 1:a + m.start()] not in (b'q', b'z') else [a]
        for k, s in enumerate(starts):
            raw = d[s:e]
            t = show(raw)
            if t is None:
                continue
            ptrs = [p for p in pt.get(base + s, []) if p % 4 == 0] if base is not None else []
            body = re.sub(r'<[^<>]*>', '', t); k = len(KANA.findall(body))
            if name == '1ST_READ.PRG':
                ok = bool(ptrs) and re.search(r'[ぁ-ヾ一-鿿]', body)   # 포인터 확인된 것만(코드 속 가짜 글 배제)
            else:
                ok = k >= 3 and k >= 0.3 * len(body)       # 그림·소리 자료의 우연한 cp932 덩어리 배제
            if not ok:
                continue
            out.append((s, raw, t, ptrs))
    return base, out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    seen = {}            # 파일 내용 → 처음 본 (디스크, 이름)
    rows = collections.OrderedDict()   # raw → [ID, [(디스크, 파일, 자리, 포인터들, 기준)]]
    stat = collections.Counter()
    for n in (1, 2, 3):
        D = disc.Disc(os.path.join(disc.ROMDIR, 'Virus (Japan) (Disc %d)' % n, 'Virus (Japan) (Disc %d) (Track 1).bin' % n))
        for p, l, sz in D.walk():
            if p.upper().endswith(('.AVI', '.DAT', '.TXT', '.TSK')) or p in SKIP:
                continue
            d = D.read(l, sz)
            key = (p, hash(d))
            if key in seen:
                continue
            seen[key] = n
            base, ss = strings(p, d)
            for s, raw, t, ptrs in ss:
                tag = re.sub(r'\.(BIN|PRG)$', '', p)
                r = rows.setdefault(raw, ['%s_%05X' % (tag, s), t, []])
                r[2].append((n, p, s, ptrs, base))
                stat[p] += 1
    # 포인터 없는 문자열이 하나뿐인 파일 = 그림 자료의 우연한 덩어리(DNG_BG «びぷ∀び÷»·S080 등)
    lone = {p for p, c in stat.items() if c == 1}
    for raw in [r for r, (_, _, s) in rows.items() if all(x[1] in lone and not x[3] for x in s)]:
        del rows[raw]
    os.makedirs(TXT, exist_ok=True)
    with open(os.path.join(TXT, 'sys_occ.tsv'), 'w', encoding='utf-8', newline='') as f:
        f.write('ID\t디스크\t파일\t자리\t포인터 자리들\t적재 기준\n')
        for raw, (rid, t, sites) in rows.items():
            for n, p, s, ptrs, base in sites:
                f.write('%s\t%d\t%s\t%05X\t%s\t%s\n' % (rid, n, p, s, ' '.join('%05X' % x for x in ptrs),
                                                       '%08X' % base if base is not None else '-'))
    for p in os.listdir(TSV):
        if re.match(r'sys_\d{3}\.tsv$', p):
            os.remove(os.path.join(TSV, p))
    head = 'ID\t자리수\t원문\t번역\n'; lim = 20 * 1024; cur = head; files = []
    def flush(cur):
        q = os.path.join(TSV, 'sys_%03d.tsv' % (len(files) + 1))
        open(q, 'w', encoding='utf-8', newline='').write(cur); files.append(q)
    for raw, (rid, t, sites) in rows.items():
        ln = '%s\t%d\t%s\t\n' % (rid, len(sites), t)
        if len((cur + ln).encode('utf-8')) > lim and cur != head:
            flush(cur); cur = head
        cur += ln
    if cur != head:
        flush(cur)
    jp = sum(len(re.sub(r'<[^<>]*>', '', t)) for _, t, _ in rows.values())
    print('고유 문자열 %d · 일본어 %d자 · 파일 %d개(20KB)' % (len(rows), jp, len(files)))
    for p, c in stat.most_common():
        print('  %-14s %d' % (p, c))


if __name__ == '__main__':
    main()

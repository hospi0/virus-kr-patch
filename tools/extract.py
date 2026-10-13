# -*- coding: utf-8 -*-
r"""VIRUS 번역 원문 추출 — 포인터가 가리키는 문자열 전수.
  모집단: VIRUS.BIN 장면 모듈 45개(적재 0x002A0000, VIRUS.IDX = u32 BE 섹터·크기) + DICTIO.BIN(적재 0x00280000).
  모듈 안 2바이트 정렬 u32 BE 값 v 가 [기준, 기준+크기) 이고 그 자리부터 0 까지가 cp932 로 온전하며
  비ASCII 글자를 하나 이상 가진 문자열 = 번역 대상. (2026-10-12 표본 200개 = 기준 일치 100%)
  표시: ASCII 덩어리(제어 코드 m0420·c7·n·u·}1 …)는 <…> 로 감싼다(«}» 가 루비 코드라 {} 못 씀, < > 는 원문에 없음) — 되돌릴 때 <> 안을 그대로 ASCII 로.
  같은 바이트 문자열은 한 줄(ID = 처음 나온 자리), 전체 자리는 work/text/occ.tsv.
  python tools/extract.py [KB=24]  → my files/tsv/virus_NNN.tsv + work/text/{occ,strings}.tsv
"""
import collections, os, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'work', 'disc1')
TXT = os.path.join(ROOT, 'work', 'text'); TSV = os.path.join(ROOT, 'my files', 'tsv')


def blobs():
    """[(이름, 바이트, 적재 기준)]"""
    idx = open(os.path.join(SRC, 'VIRUS.IDX'), 'rb').read(); b = open(os.path.join(SRC, 'VIRUS.BIN'), 'rb').read()
    out = []
    for k in range(len(idx) // 8):
        s, sz = struct.unpack_from('>II', idx, k * 8)
        out.append(('V%02d' % k, b[s * 2048:s * 2048 + sz], 0x002A0000))
    out.append(('DIC', open(os.path.join(SRC, 'DICTIO.BIN'), 'rb').read(), 0x00280000))
    return out


def show(raw):
    """바이트 → 표시 글(ASCII 덩어리는 <…>). 온전하지 않으면 None"""
    try:
        raw.decode('cp932')
    except UnicodeDecodeError:
        return None
    out = []; i = 0; asc = bytearray(); nonascii = False
    while i < len(raw):
        c = raw[i]
        if c < 0x80:
            if c < 0x20: return None
            asc.append(c); i += 1; continue
        if asc:
            out.append('<%s>' % asc.decode()); asc = bytearray()
        if not (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xEF):
            return None                    # 반각 가나·IBM 확장(0xFA‥) — 글꼴(FONT.DAT JIS 순)에 없음 → 가짜 포인터
        n = 2
        out.append(raw[i:i + n].decode('cp932')); i += n; nonascii = True
    if asc:
        out.append('<%s>' % asc.decode())
    t = "".join(out) if nonascii else None
    return t if t is not None and unshow(t) == raw else None


def unshow(t):
    """show 의 역"""
    out = bytearray()
    for part in re.split(r'(<[^<>]*>)', t):
        if part.startswith('<') and part.endswith('>') and len(part) >= 2:
            out += part[1:-1].encode('ascii')
        else:
            out += part.encode('cp932')
    return bytes(out)


def collect():
    occ = []   # (블롭, 문자열 자리, 포인터 자리, 바이트)
    for name, m, base in BL:
        for i in range(0, len(m) - 3, 2):
            v, = struct.unpack_from('>I', m, i)
            o = v - base
            if not (0 <= o < len(m)):
                continue
            e = m.find(b'\0', o)
            if e <= o:
                continue
            raw = m[o:e]
            if show(raw) is None:
                continue
            occ.append((name, o, i, raw))
    return occ


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    kb = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    occ = collect()
    os.makedirs(TXT, exist_ok=True); os.makedirs(TSV, exist_ok=True)
    # 같은 문자열 자리를 가리키는 포인터는 모으고, 같은 바이트는 한 ID
    by_site = collections.OrderedDict()
    for name, o, i, raw in sorted(occ, key=lambda x: (x[0], x[1], x[2])):
        by_site.setdefault((name, o), (raw, []))[1].append(i)
    ids = collections.OrderedDict()
    for (name, o), (raw, ptrs) in by_site.items():
        ids.setdefault(raw, []).append((name, o, ptrs))
    with open(os.path.join(TXT, 'occ.tsv'), 'w', encoding='utf-8', newline='') as f:
        f.write('ID\t블롭\t자리\t포인터 자리들\n')
        for raw, sites in ids.items():
            rid = '%s_%05X' % (sites[0][0], sites[0][1])
            for name, o, ptrs in sites:
                f.write('%s\t%s\t%05X\t%s\n' % (rid, name, o, ' '.join('%05X' % p for p in ptrs)))
    rows = []
    for raw, sites in ids.items():
        rid = '%s_%05X' % (sites[0][0], sites[0][1])
        t = show(raw); assert unshow(t) == raw, rid
        rows.append((rid, len(sites), t))
    head = 'ID\t자리수\t원문\t번역\n'
    for p in os.listdir(TSV):
        if re.match(r'virus_\d{3}\.tsv$', p):
            os.remove(os.path.join(TSV, p))
    lim = kb * 1024; cur = head; files = []
    def flush(cur):
        p = os.path.join(TSV, 'virus_%03d.tsv' % (len(files) + 1))
        open(p, 'w', encoding='utf-8', newline='').write(cur); files.append(p)
    for rid, n, t in rows:
        ln = '%s\t%d\t%s\t\n' % (rid, n, t)
        if len((cur + ln).encode('utf-8')) > lim and cur != head:
            flush(cur); cur = head
        cur += ln
    if cur != head:
        flush(cur)
    jp = sum(len(re.sub(r'<[^<>]*>', '', t)) for _, _, t in rows)
    tail = sum(1 for (name, o), (raw, ptrs) in by_site.items()
               if o > 0 and dict((n, m) for n, m, _ in BL)[name][o - 1] != 0)
    print('포인터 %d · 문자열 자리 %d · 고유 문자열 %d · 일본어 %d자 · 파일 %d개(%dKB 단위)' % (len(occ), len(by_site), len(rows), jp, len(files), kb))
    print('앞 바이트가 0 이 아닌 자리(꼬리 공유·접두 데이터 후보) %d' % tail)
    print('블롭별 고유 자리', collections.Counter(n for n, _ in by_site))


BL = blobs()

if __name__ == '__main__':
    main()

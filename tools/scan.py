# -*- coding: utf-8 -*-
r"""초기 조사 — ①세 디스크의 같은 이름 파일 동일 여부 ②파일별 SJIS 평문 문자열 분량(가나 포함 연속 4자 이상).
  python tools/scan.py  → work/scan.txt
"""
import hashlib, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import importlib

SJ = re.compile(rb'(?:[\x81-\x9F\xE0-\xEF][\x40-\x7E\x80-\xFC]){4,}')


def disc(n):
    os.environ['VDISC'] = str(n)
    import disc as d
    importlib.reload(d)
    return d.Disc(d.ROM)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ds = {n: disc(n) for n in (1, 2, 3)}
    fs = {n: {p: (l, s) for p, l, s in ds[n].walk()} for n in ds}
    names = sorted(set().union(*fs.values()))
    out = []; same = diff = 0; texty = []
    for p in names:
        if p.upper().endswith('.AVI'):
            continue
        hs = {}
        for n in ds:
            if p in fs[n]:
                hs[n] = hashlib.md5(ds[n].read(*fs[n][p])).hexdigest()
        if len(hs) > 1:
            if len(set(hs.values())) == 1: same += 1
            else: diff += 1; out.append('다름 %s %s' % (p, sorted(hs)))
        n0 = min(hs); b = ds[n0].read(*fs[n0][p])
        chars = 0; cnt = 0; kana = 0
        for m in SJ.finditer(b):
            s = m.group(0)
            try:
                t = s.decode('cp932')
            except UnicodeDecodeError:
                continue
            if not re.search('[ぁ-んァ-ヶ]', t):
                continue
            cnt += 1; chars += len(t)
        if cnt:
            texty.append((chars, cnt, p, len(b), sorted(hs)))
    out.append('같은 파일 %d · 디스크마다 다른 파일 %d' % (same, diff))
    texty.sort(reverse=True)
    out.append('SJIS 문자열 많은 파일(글자수 문자열수 파일 크기 디스크):')
    out += ['  %7d %5d %-24s %9d %s' % t for t in texty]
    out.append('합계 %d자' % sum(t[0] for t in texty))
    open(os.path.join(ROOT, 'work', 'scan.txt'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print('\n'.join(out[:5] + out[-60:]))


if __name__ == '__main__':
    main()

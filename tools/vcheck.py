# -*- coding: utf-8 -*-
r"""VIRUS 본편 번역 검사·병합 — my files/virus번역/virus_*.tsv(받은 번역) × my files/tsv/virus_*.tsv(원문).
  루비 <}1>본문<}2>루비<}> → «본문(루비)» (사용자 2026-10-13) 로 바꾼 뒤 검사.
  검사: ① 제어 코드(<n>·루비 빼고) 순서·개수 원문과 같음 ② 줄 칸 ≤ 21(제어 코드 빼고 글자 수, 전각 1칸)
        ③ 인물 이름(<c1>이름<c7>)·용어(사전 DIC·루비 쌍) 번역 일관 ④ 일본어 남음(가나·한자) ⑤ 말투(화자별 끝맺음 분포에서 튀는 줄)
  python tools/vcheck.py           → work/check/*.tsv 보고, 막힘 0 이면 data/virus_ko.tsv 병합
"""
import collections, glob, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
WIDTH = 21
RUBY = re.compile(r'<\}1>(.*?)<\}2>(.*?)<\}>')
TOK = re.compile(r'<[^>]*>')
KANA = re.compile(r'[぀-ヿ一-鿿]')


def load(pat, col):
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'my files', pat))):
        for n, l in enumerate(open(f, encoding='utf-8-sig').read().splitlines()[1:], 2):
            c = l.split('\t')
            out[c[0]] = (c[2], c[col] if len(c) > col else '', os.path.basename(f), n)
    return out


def deruby(t):
    return RUBY.sub(lambda m: '%s(%s)' % (m.group(1), m.group(2)), t)


def toks(t):
    """제어 코드 나열(<n>·루비 제외). <m0420c3> 처럼 묶인 것은 그대로 비교."""
    return [x for x in TOK.findall(t) if x != '<n>' and not x.startswith('<}')]


def lines(t):
    t = re.sub(r'<n>', '\n', t)
    return [TOK.sub('', x) for x in t.split('\n')]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    src = load('tsv/virus_*.tsv', 2)
    tr = load('virus번역/virus_*.tsv', 3)
    out = os.path.join(ROOT, 'work', 'check'); os.makedirs(out, exist_ok=True)
    rep = collections.defaultdict(list)
    names = collections.defaultdict(collections.Counter); rubies = collections.defaultdict(collections.Counter)
    for i, (ja, ko0, f, n) in tr.items():
        ko = deruby(ko0)
        if toks(ja) != toks(ko):
            rep['token'].append((i, f, n, ' '.join(toks(ja)), ' '.join(toks(ko)), ja, ko0))
        if ja.count('<n>') != ko.count('<n>'):
            rep['newline'].append((i, f, n, ja.count('<n>'), ko.count('<n>'), ja, ko0))
        for li, x in enumerate(lines(ko)):
            if len(x) > WIDTH:
                rep['over'].append((i, f, n, len(x), x, ja, ko0))
        if KANA.search(TOK.sub('', ko)):
            rep['jp'].append((i, f, n, ''.join(KANA.findall(TOK.sub('', ko))), ja, ko0))
        mj = re.search(r'<c1>(.*?)<c7>', ja); mk = re.search(r'<c1>(.*?)<c7>', ko0)
        if mj:
            names[mj.group(1)][mk.group(1) if mk else '(없음)'] += 1
        rj = RUBY.findall(ja); rk = RUBY.findall(ko0)
        for a, b in zip(rj, rk):
            rubies['%s/%s' % a]['%s(%s)' % b] += 1
    # 이름·루비 일관성
    for k, c in names.items():
        if len(c) > 1:
            rep['name'].append((k, ' · '.join('%s×%d' % x for x in c.most_common())))
    for k, c in rubies.items():
        if len(c) > 1:
            rep['ruby'].append((k, ' · '.join('%s×%d' % x for x in c.most_common())))
    for kind, rows in rep.items():
        with open(os.path.join(out, '%s.tsv' % kind), 'w', encoding='utf-8') as w:
            for r in rows:
                w.write('\t'.join(str(x) for x in r) + '\n')
    print('검사 %d줄' % len(tr), {k: len(v) for k, v in rep.items()})
    return tr, rep, names


if __name__ == '__main__':
    main()

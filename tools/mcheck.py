# -*- coding: utf-8 -*-
r"""동영상 자막 번역 검사·병합 — my files/virus번역/movie_*.tsv → data/movie_ko.tsv (ID·영상·시작·끝·원문·번역·비고).
  본편(data/virus_ko.tsv)과 맞춤:
   ① 인물 이름: 본편 화자 이름 표(원문 <c1>이름<c7> → 최종 번역 최다) — 원문에 이름이 있는데 번역에 그 한글 이름이 없으면 보고,
      알려진 틀린 꼴(data/virus_names.tsv)·본편과 다른 꼴은 자동 교체(data/movie_fix.tsv 손질 먼저)
   ② 용어: 본편 루비 «본문(루비)» 의 가타카나 루비 → 한글 루비(최다), 원문에 그 가타카나가 있으면 번역에 그 한글이 있는지 보고
   ③ 말투: 원문 です·ます ↔ 번역 존대 어미(요·니다) 어긋남 보고(휴리스틱)
   ④ 가사(비고 «가사») 는 번역 없음 그대로, 받아쓰기 «⚠확신 낮음» 은 비고 유지
   ⑤ 영상의 모든 줄이 «확신 낮음»(위스퍼 환각 «감사합니다»·의성어 등)이면 그 영상 통째 자막 제외 — 번역 비우고 비고 «제외»(사용자 2026-10-13)
  python tools/mcheck.py → data/movie_ko.tsv + work/check/movie_*.tsv
"""
import collections, glob, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

JP_POL = re.compile(r'(です|ます|ました|ません|でした|ください|下さい|ましょう|でしょう|ございます)')
KO_POL = re.compile(r'(요|니다|니까요|세요|십시오)(?=[\s.,!?！？。…」』)]|$)')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    # 본편에서 이름·용어 표
    names = collections.defaultdict(collections.Counter); terms = collections.defaultdict(collections.Counter)
    for l in open(os.path.join(ROOT, 'data', 'virus_ko.tsv'), encoding='utf-8').read().splitlines()[1:]:
        i, ja, ko, note = l.split('\t')
        mj = re.search(r'c1>([^<]+)<c7', ja); mk = re.search(r'c1>([^<]+)<c7', ko)
        if mj and mk:
            names[mj.group(1)][mk.group(1)] += 1
        for base, ruby in re.findall(r'<\}1>(.*?)<\}2>(.*?)<\}>', ja):
            m = re.search(re.escape(re.sub('[・ー]', '', base)[:2]) + r'[^（]*（([^）]+)）', ko.replace('　', ' '))
            if m and re.fullmatch(r'[ァ-ヶー・]+', ruby):
                terms[ruby][m.group(1).replace('　', ' ')] += 1
    norm = lambda x: re.sub(r'<[^<>]*>', '', x).replace('　', ' ').strip()
    NAME = {k: norm(c.most_common(1)[0][0]) for k, c in names.items() if re.fullmatch(r'[ァ-ヶー・]+', k) and len(k) >= 2}
    TERM = {k: norm(c.most_common(1)[0][0]) for k, c in terms.items() if sum(c.values()) >= 2}
    has = lambda w, t: re.search(r'(?<![ァ-ヶー])' + re.escape(w) + r'(?![ァ-ヶー])', t)
    fixes = collections.defaultdict(list)
    fp = os.path.join(ROOT, 'data', 'movie_fix.tsv')
    if os.path.exists(fp):
        for l in open(fp, encoding='utf-8').read().splitlines():
            if l.strip() and not l.startswith('#'):
                a = l.split('\t'); fixes[a[0]].append((a[1], a[2]))
    bad = [l.split('\t') for l in open(os.path.join(ROOT, 'data', 'virus_names.tsv'), encoding='utf-8').read().splitlines() if l.strip() and not l.startswith('#')]
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'my files', 'virus번역', 'movie_*.tsv'))):
        for l in open(f, encoding='utf-8-sig').read().splitlines()[1:]:
            c = l.split('\t') + [''] * 7
            rows.append(c[:7])
    rep = collections.defaultdict(list); out = []
    for i, vid, t0, t1, ja, ko, note in rows:
        notes = [note] if note else []
        for a, b in fixes.get(i, []):
            if a in ko:
                ko = ko.replace(a, b)
            else:
                rep['fix_miss'].append((i, a))
        for src, good, badv, scope in bad:
            if src in ja:
                for b in badv.split(','):
                    if b in ko and not (scope == 'name' and b in good):
                        if scope == 'all' or re.search(r'(^|[\s「（,.!?])' + re.escape(b) + r'(?=[\s가-힣,.!?」）]|$)', ko):
                            ko = ko.replace(b, good); notes.append('이름 통일 %s→%s' % (b, good))
        if ko:
            for jn, kn in NAME.items():
                if has(jn, ja) and kn not in ko and kn.replace(' ', '') not in ko.replace(' ', ''):
                    rep['name'].append((i, jn, kn, ja, ko))
            for jt, kt in TERM.items():
                if has(jt, ja) and kt not in ko and kt.replace(' ', '') not in ko.replace(' ', ''):
                    rep['term'].append((i, jt, kt, ja, ko))
            j = bool(JP_POL.search(ja)); k = bool(KO_POL.search(ko))
            if j != k:
                rep['tone'].append((i, '원문존대→번역반말' if j else '원문반말→번역존대', ja, ko))
        out.append((i, vid, t0, t1, ja, ko, ' / '.join(x for x in notes if x)))
    byv = collections.defaultdict(list)
    for r in out:
        byv[r[1]].append(r)
    drop = {v for v, rs in byv.items() if all('확신' in r[6] for r in rs)}
    out = [r if r[1] not in drop else r[:5] + ('', (r[6] + ' / ' if r[6] else '') + '제외: 영상 전체 확신 낮음') for r in out]
    print('전부 확신 낮음 → 제외 영상 %d개 · %d줄' % (len(drop), sum(len(byv[v]) for v in drop)))
    with open(os.path.join(ROOT, 'data', 'movie_ko.tsv'), 'w', encoding='utf-8', newline='\n') as w:
        w.write('ID\t영상\t시작\t끝\t원문\t번역\t비고\n')
        for r in out:
            w.write('\t'.join(r) + '\n')
    od = os.path.join(ROOT, 'work', 'check'); os.makedirs(od, exist_ok=True)
    for k, v in rep.items():
        with open(os.path.join(od, 'movie_%s.tsv' % k), 'w', encoding='utf-8') as w:
            for r in v:
                w.write('\t'.join(str(x) for x in r) + '\n')
    print('자막 %d줄 → data/movie_ko.tsv' % len(out), {k: len(v) for k, v in rep.items()})
    print('이름표 %d · 용어표 %d' % (len(NAME), len(TERM)))


if __name__ == '__main__':
    main()

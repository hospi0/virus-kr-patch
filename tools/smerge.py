# -*- coding: utf-8 -*-
r"""VIRUS 본편 밖 글(시스템 메시지) 번역 검사·병합 — my files/virus번역/sys_*.tsv → data/sys_ko.tsv (ID · 원문 · 번역(최종) · 비고).
  손질은 본편과 같은 vmerge.merge_row(손질표·이름 통일·루비 괄호·전각·부호 뒤 공백·머리 코드·<u>·용어 붙여 쓰기).
    흘리기(21칸)·첫 줄 들여쓰기 지우기는 «대화 상자 글»(<m0420…> 로 시작, 자리 코드 x·q·l·y·a·s·g 없음)만.
  · 코드 없는 고정 칸 글(메뉴 «　見る　»·ジャンル 등): 원문 글자 수에 맞춤 — 길면 앞뒤 «　» 를 덜고, 짧으면 «　» 로 채움.
  검사(보고 work/check/sys_*.tsv):
    token  제어 코드가 원문과 다름(⛔)            jp    일본어(가나·한자) 남음
    name   화자 이름이 본편 번역과 다름 → 본편 다수 꼴로 통일(본편 3번↑·80%↑일 때)
    ruby   루비 용어(본문/루비 쌍)가 본편 번역과 다름   noun  코드 없는 낱말(아이템·메뉴)이 본편 대사 번역에 거의 안 나옴
    tone   말투: 원문 です·ます ↔ 번역 존대 어미 어긋남 · 화자의 본편 말투(존대/반말 90%↑)와 다름
    width  대화 상자 밖 글에서 줄이 원문 최장 줄보다 김(창 폭 미확인 — 보고만)
  python tools/smerge.py   (Kiwi venv: C:/claude/utils/kiwi-venv/Scripts/python)
"""
import collections, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import vcheck, vmerge, vtext

TAG = re.compile(r'<[^<>]*>')
POS = set('xqlyasg/')
POLITE = re.compile(r'(요|니다|니까[？?]|세요|시오|죠|예|더|소|꺼|이소|지예)[\.．!！?？…‥~～」』）\)　]*$')
JPOL = re.compile(r'(です|ます|ません|でしょう|ました|ましょう|ください|下さい|ませ|まして|でした|ですか|ますか)[。、！？…‥～」』）　]*$')
SPK = re.compile(r'<[^<>]*c1[^<>]*>(.*?)<[^<>]*c[0-9][^<>]*>')


def extra_file(i):
    tag = i.rsplit('_', 1)[0]
    return tag + ('.PRG' if tag == '1ST_READ' else '.BIN')


def is_dialog(J):
    return J.startswith('<m04') and not (set(vtext.codes(J)[5:]) & POS)


def speaker(t):
    m = SPK.match(t)
    return vtext.deruby_tags(m.group(1)) if m else None


def sentences_end(t):
    """대사 끝맺음들(코드·화자 빼고, 。！？ 와 줄 끝 단위)"""
    body = t
    m = SPK.match(t)
    if m:
        body = t[m.end():]
    body = TAG.sub('', re.sub(r'<[^<>]*n[^<>]*>', '\n', body))
    return [x.strip('　 ') for x in re.split(r'(?<=[。．！？!?」])|\n', body) if x and x.strip('　 「」')]


def polite_ko(s):
    return bool(POLITE.search(s))


def fix_width(J, K):
    """코드 없는 고정 칸 글 → 원문 글자 수로"""
    w = len(J)
    if len(K) > w:
        while len(K) > w and (K.startswith('　') or K.endswith('　')):
            if K.endswith('　') and (len(K) - len(K.rstrip('　')) >= len(K) - len(K.lstrip('　'))):
                K = K[:-1]
            else:
                K = K[1:]
    elif len(K) < w:
        lead = (w - len(K)) // 2 if J.startswith('　') else 0
        K = '　' * lead + K + '　' * (w - len(K) - lead)
    return K


def wrap_other(i, J, K, note, rep):
    """대화 상자 밖(자리 코드 있는) 글: 줄바꿈 코드가 모두 같은 꼴(<nx04>·<nx05c5> 의 n+x##)이면 그 꼴로 다시 흘림.
      줄 칸 = max(21, 원문 최장 줄). 색 코드는 줄바꿈 코드에서 떼어 제자리에 둠(바이트는 같음)."""
    its = vmerge.items(K)
    nls = [v for k, v in its if k == 'nl']
    if not nls:
        return K
    xs = {re.match(r'(x\d\d)?', v).group(0) for v in nls}
    if len(xs) != 1 or any(re.sub(r'^x\d\d', '', v) and not re.fullmatch(r'(c\d)+', re.sub(r'^x\d\d', '', v)) for v in nls):
        return K
    x = xs.pop()
    jl = vmerge.lines_of(vmerge.items(J))
    w = max(21, max(vmerge.wlen(l) for l in jl))
    if not any(vmerge.wlen(l) > w for l in vmerge.lines_of(its)):
        return K
    flat = []
    for k, v in its:
        if k == 'nl':
            flat.append(('nl', ''))
            if v[len(x):]:
                flat.append(('c', v[len(x):]))
        else:
            flat.append((k, v))
    old = vmerge.W; vmerge.W = w
    try:
        new, err = vmerge.reflow(flat, False)
    finally:
        vmerge.W = old
    if err:
        rep['wrap'].append((i, err, K)); note.append('⛔' + err); return K
    K2 = ''.join('<n%s>' % x if k == 'nl' else ('<%s>' % v if k == 'c' else v) for k, v in new)
    note.append('흘림(%d칸)' % w)
    n0, n1 = len(jl), len(vmerge.lines_of(new))
    if n1 > n0:
        rep['grown'].append((i, n0, n1, K2))
    return K2


LX = re.compile(r'(<qz00m)(\d\d)(\d\d>)|(<nx)(\d\d)(>)')


def recenter(J, K, note):
    """가운데 정렬 메뉴(<qz00mXXYY>줄<nxXX>줄…, x = 8px 단위, 원문 줄 가운데가 한 자리)를 한글 폭으로 다시 맞춤.
      줄 안 «　» 는 <u>(8px). 2026-10-13 옵션 메뉴 «무기 교환…» 줄맞춤(사용자)."""
    def lines(t):
        parts = LX.split(t)
        out = []; i = 1
        while i < len(parts):
            g = parts[i:i + 6]; txt = parts[i + 6] if i + 6 < len(parts) else ''
            x = int(g[1] if g[0] else g[4])
            out.append((x, txt)); i += 7
        return out
    if not LX.match(J):
        return K
    lj, lk = lines(J), lines(K)
    if len(lj) < 2 or len(lj) != len(lk) or any(TAG.search(t) for _, t in lj):
        return K
    cs = [x * 8 + len(t) * 6 for x, t in lj]
    if max(cs) - min(cs) > 8 or len({x for x, _ in lj}) < 2:
        return K
    c = sum(cs) / len(cs)
    xs = []; texts = []
    for _, t in lk:
        t = re.sub(r'(?<=[^　])　(?=[^　])', '<u>', t)
        w = len(TAG.sub('', t)) * 12 + 8 * t.count('<u>')
        xs.append(max(0, round((c - w / 2) / 8))); texts.append(t)
    it = iter(zip(xs, texts)); k = [0]
    def sub(m):
        x, t = next(it)
        return (m.group(1) + '%02d' % x + m.group(3)) if m.group(1) else (m.group(4) + '%02d' % x + m.group(6))
    out = LX.sub(sub, K)
    # 줄 글도 <u> 로 바꾼 것으로
    segs = LX.split(out); res = ''; i = 0; n = 0
    res = segs[0]; i = 1
    while i < len(segs):
        g = segs[i:i + 6]
        res += (g[0] + g[1] + g[2]) if g[0] else (g[3] + g[4] + g[5])
        res += texts[n]; n += 1; i += 7
    note.append('가운데 맞춤')
    return res


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    tr = vcheck.load('virus번역/sys_*.tsv', 3)
    src = vcheck.load('tsv/sys_*.tsv', 2)
    rep = collections.defaultdict(list)
    miss = [i for i in src if i not in tr]; extra = [i for i in tr if i not in src]
    diff = [i for i in tr if i in src and tr[i][0] != src[i][0]]
    empty = [i for i, v in tr.items() if not v[1].strip()]
    print('받은 번역 %d줄 / 추출 %d줄 · 빠짐 %d · 남는 ID %d · 원문 바뀜 %d · 빈 번역 %d' % (len(tr), len(src), len(miss), len(extra), len(diff), len(empty)))
    if miss or extra or diff:
        sys.exit('⛔ ID·원문 불일치: %s %s %s' % (miss[:5], extra[:5], diff[:5]))
    # 추출 보충(data/sys_extra.tsv): TESHMES 진짜 문장 시작 + 빠진 짧은 글 — 조각 ID 는 원문 그대로(빌드에서 손 안 댐)
    import disc
    from extract import show
    D = disc.Disc(); fl = {p: (l, sz) for p, l, sz in D.walk()}
    frag = {}
    for r in vmerge.read_tsv('sys_extra.tsv'):
        i, drop, t = r[0], r[1], r[2]
        for x in filter(None, drop.split(',')):
            frag[x] = i
        if t != '-':
            site = int(i.rsplit('_', 1)[1], 16); b = D.read(*fl[extra_file(i)])
            tr[i] = (show(b[site:b.index(b'\0', site)]), t, 'sys_extra.tsv', 0)
    for x in frag:
        assert x in tr, x
    for r in vmerge.read_tsv('sys_short.tsv'):          # 자리에 맞춘 짧은 번역
        assert r[0] in tr, r[0]
        tr[r[0]] = (tr[r[0]][0], r[1], 'sys_short.tsv', 0)
    fixes = collections.defaultdict(list)
    for r in vmerge.read_tsv('virus_fix.tsv'):
        fixes[r[0]].append((r[1], r[2]))
    names = vmerge.read_tsv('virus_names.tsv')
    # 본편 기준표
    main = {}
    for l in open(os.path.join(ROOT, 'data', 'virus_ko.tsv'), encoding='utf-8').read().splitlines()[1:]:
        c = l.split('\t'); main[c[0]] = (c[1], c[2])
    spk = collections.defaultdict(collections.Counter); spk_pol = collections.defaultdict(collections.Counter)
    for ja, K in main.values():
        a, b = speaker(ja), speaker(K)
        if a and b:
            spk[a][b] += 1
            for e in sentences_end(K):
                spk_pol[a][polite_ko(e)] += 1
    rawmain = vcheck.load('virus번역/virus_*.tsv', 3)
    rub = collections.defaultdict(collections.Counter)
    for ja, ko, _, _ in rawmain.values():
        for a, b in zip(vtext.RUBY.findall(vtext.split_tags(ja)), vtext.RUBY.findall(vtext.split_tags(ko))):
            rub[a][b] += 1
    out_rows = []
    for i, (ja, ko, f, n) in tr.items():
        if i in frag:
            out_rows.append((i, ja, ja, '조각→' + frag[i])); continue
        J = vtext.deruby_tags(ja)
        dlg = is_dialog(J)
        K, note, grown = vmerge.merge_row(i, ja, ko, f, n, fixes, names, rep, wrap=dlg)
        # 이름 통일(화자 자리)
        a, b = speaker(ja), speaker(K)
        if a and b and a in spk:
            best, cnt = spk[a].most_common(1)[0]
            if b != best:
                if cnt >= 3 and cnt >= 0.8 * sum(spk[a].values()):
                    m = SPK.match(K)
                    K = K[:m.start(1)] + best + K[m.end(1):]
                    note.append('이름 통일'); rep['name'].append((i, a, b, '→ ' + best, dict(spk[a])))
                else:
                    rep['name'].append((i, a, b, '(본편 갈림)', dict(spk[a])))
        # 루비 용어
        for x, y in zip(vtext.RUBY.findall(vtext.split_tags(ja)), vtext.RUBY.findall(vtext.split_tags(ko))):
            if x in rub and y not in rub[x]:
                rep['ruby'].append((i, '%s/%s' % x, '%s(%s)' % y, ' · '.join('%s(%s)×%d' % (p, q, c) for (p, q), c in rub[x].most_common(3))))
            elif x not in rub:
                rep['ruby_new'].append((i, '%s/%s' % x, '%s(%s)' % y))
        # 고정 칸 글
        if not TAG.search(J) and K != J:
            K2 = fix_width(J, K)
            if K2 != K:
                note.append('칸 맞춤'); rep['fixwidth'].append((i, J, K, K2))
                K = K2
            if len(K) > len(J):
                rep['width'].append((i, '고정 칸 %d > 원문 %d' % (len(K), len(J)), J, K))
        elif not dlg:
            K = recenter(J, K, note)
            K = wrap_other(i, J, K, note, rep)
            jw = max(len(x) for x in vcheck.lines(re.sub(r'<[^<>]*n[^<>]*>', '<n>', J)))
            kw = max(len(x) for x in vcheck.lines(re.sub(r'<[^<>]*n[^<>]*>', '<n>', K)))
            if kw > jw and kw > 21:
                rep['width'].append((i, '줄 %d > 원문 최장 %d' % (kw, jw), J, K))
        # 일본어 남음
        if vcheck.KANA.search(TAG.sub('', K).replace('・', '')) and K != J:
            left = ''.join(vcheck.KANA.findall(TAG.sub('', K).replace('・', '')))
            if not set(left) <= set(TAG.sub('', J)) or re.search(r'[ぁ-ヿ]', left):
                rep['jp'].append((i, left, K))
        # 말투
        if a:
            je, ke = sentences_end(J), sentences_end(K)
            if je and ke:
                jp_pol = bool(JPOL.search(je[-1])); ko_pol = polite_ko(ke[-1])
                if jp_pol and not ko_pol:
                    rep['tone'].append((i, '원문 존대·번역 반말', je[-1], ke[-1]))
                pc = spk_pol.get(a)
                if pc and sum(pc.values()) >= 10:
                    r = pc[True] / sum(pc.values())
                    for e in ke:
                        if (r >= 0.9 and not polite_ko(e)) or (r <= 0.1 and polite_ko(e)):
                            rep['tone'].append((i, '%s 본편 존대 %.0f%%' % (a, 100 * r), J, e)); break
        out_rows.append((i, ja, K, ' '.join(note)))
    # 낱말(아이템·메뉴) ↔ 본편 대사
    plain_main = [(TAG.sub('', ja), TAG.sub('', K).replace('　', '')) for ja, K in main.values()]
    for i, ja, K, _ in out_rows:
        jw = TAG.sub('', ja).strip('　'); kw = TAG.sub('', K).strip('　').replace('　', '')
        if TAG.sub('', ja.split('>', 1)[-1] if ja.startswith('<g') else ja) != (ja.split('>', 1)[-1] if ja.startswith('<g') else ja):
            continue
        if len(jw) < 3 or kw == jw:
            continue
        hits = [k for j, k in plain_main if jw in j]
        if len(hits) >= 2:
            ok = sum(kw in k for k in hits)
            if ok < len(hits) / 2:
                c = collections.Counter()
                rep['noun'].append((i, jw, kw, '본편 %d곳 중 %d' % (len(hits), ok), ' | '.join(h[:40] for h in hits[:3])))
    with open(os.path.join(ROOT, 'data', 'sys_ko.tsv'), 'w', encoding='utf-8', newline='\n') as w:
        w.write('ID\t원문\t번역\t비고\n')
        for r in out_rows:
            w.write('\t'.join(r) + '\n')
    od = os.path.join(ROOT, 'work', 'check')
    for p in os.listdir(od):
        if p.startswith('sys_'):
            os.remove(os.path.join(od, p))
    for k, rows in rep.items():
        with open(os.path.join(od, 'sys_%s.tsv' % k), 'w', encoding='utf-8') as w:
            for r in rows:
                w.write('\t'.join(str(x) for x in r) + '\n')
    c = collections.Counter(x for r in out_rows for x in r[3].split() if x)
    print('병합 %d줄 → data/sys_ko.tsv' % len(out_rows), dict(c), {k: len(v) for k, v in rep.items()})


if __name__ == '__main__':
    main()

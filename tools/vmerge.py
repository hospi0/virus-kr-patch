# -*- coding: utf-8 -*-
r"""VIRUS 본편 번역 병합 — my files/virus번역/virus_*.tsv → data/virus_ko.tsv (ID · 원문 · 번역(최종) · 비고).
  순서: ① data/virus_fix.tsv 손질 ② data/virus_names.tsv 이름 통일(화자 자리 / 본문)
        ③ 루비 → 본문(루비) ④ 반각 → 전각, 부호 뒤 공백 지움 ⑤ 머리 코드(<m0420c1> 등)는 원문 것으로
        ⑥ 빠진 <u> 는 글 길이 비율 자리(가까운 공백 뒤)에 되살림 ⑦ 줄 칸 21 넘으면 흘리기(공백·부호 뒤에서만, 이어지는 줄 머리 «　»는 원문 꼴)
  막힘(비고에 ⛔, 병합은 하되 보고): 코드가 u 말고도 다름 · 한 낱말이 21칸 넘음.
  보고: work/check/merge_*.tsv · 원문보다 줄이 늘어난 상자 수.
  python tools/vmerge.py
"""
import collections, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import vcheck, vtext

W = vtext.WIDTH
NOINDENT = True
BRK = set('　，、。．！？…‥・')   # 끊는 자리: 공백·쉼표·마침표류 뒤(닫는 괄호 뒤는 조사가 붙으므로 안 끊음)


def read_tsv(p):
    rows = []
    for l in open(os.path.join(ROOT, 'data', p), encoding='utf-8').read().splitlines():
        if l.strip() and not l.startswith('#'):
            rows.append(l.split('\t'))
    return rows


def items(t):
    """글 → [('c', 코드글) | ('nl', 코드글(n 빠짐)) | ('t', 글자)]"""
    out = []
    for part in re.split(r'(<[^<>]*>)', t):
        if not part:
            continue
        if part.startswith('<'):
            c = part[1:-1]
            if 'n' in c and not c.startswith('m'):
                rest = c.replace('n', '')
                out.append(('nl', rest))
            elif 'n' in c and c.startswith('m'):
                out.append(('nl', c.replace('n', '')))
            else:
                out.append(('c', c))
        else:
            out += [('t', ch) for ch in part]
    return out


def render(its):
    s = ''
    for k, v in its:
        if k == 't':
            s += v
        elif k == 'c':
            s += '<%s>' % v
        else:
            s += '<%sn>' % v if v else '<n>'
    return s


def lines_of(its):
    L = [[]]
    for it in its:
        if it[0] == 'nl':
            L.append([])
        else:
            L[-1].append(it)
    return L


U_W = 8 / 12      # <u> = 화면에서 8px 띄움(글자 칸 12px) — 2026-10-13 실기 «요즘　<u>사람과» 틈 두 배로 확인


A_W = 1          # <a00>·<a01>… = 변수(숫자 등) 한 글자씩 찍힘 — 2026-10-13 V01 «계약금 <a00>００Ｍ» 줄넘침(0칸으로 셌음)


def wlen(line):
    return (sum(1 for k, v in line if k == 't') + U_W * sum(v.count('u') for k, v in line if k == 'c')
            + A_W * sum(len(re.findall(r'a\d\d', v)) for k, v in line if k == 'c'))


def reflow(its, indent):
    """줄 칸 W 로 다시 흘림. → (새 items, 실패 사유|None)"""
    # 줄바꿈 코드의 나머지 코드는 제자리에 남기고, 이어지는 줄 머리 들여쓰기 «　» 지움
    flat = []; first = True
    for k, v in its:
        if k == 'nl':
            if v:
                flat.append(('c', v))
            if flat and flat[-1] != ('t', '　') and not (flat[-1][0] == 't' and flat[-1][1] in BRK):
                flat.append(('t', '　'))
            first = False
            continue
        flat.append((k, v))
    # 들여쓰기 다음 «　» 연속 정리
    clean = []
    for i, it in enumerate(flat):
        if it == ('t', '　') and clean and clean[-1] == ('t', '　'):
            continue
        clean.append(it)
    # 낱말 단위(끊는 자리 = «　» 뒤·부호 뒤)로 묶어 탐욕 채움
    words = []; cur = []
    for it in clean:
        if it == ('t', '（') and cur and len(cur) > 1:     # 루비 괄호 앞도 끊을 수 있음(긴 낱말+괄호)
            words.append(cur); cur = []
        cur.append(it)
        if it[0] == 't' and it[1] in BRK:
            words.append(cur); cur = []
    if cur:
        words.append(cur)
    # 닫는 괄호만 있는 낱말은 앞 낱말에 붙임(줄 머리에 «」» 혼자 가지 않게)
    merged = []
    for wd in words:
        if merged and wd and all(k == 't' and v in '」』）' for k, v in wd):
            merged[-1] = merged[-1] + wd
        else:
            merged.append(wd)
    words = merged
    lines = []; line = []
    for wd in words:
        trial = line + wd
        tw = wlen(trial) - (1 if trial and trial[-1] == ('t', '　') else 0)
        if line and tw > W:
            while line and line[-1] == ('t', '　'):
                line.pop()
            lines.append(line)
            while wd and wd[0] == ('t', '　'):
                wd = wd[1:]
            line = ([('t', '　')] if indent else []) + wd
        else:
            line = trial
        if wlen(line) - (1 if line and line[-1] == ('t', '　') else 0) > W:
            return its, '한 낱말이 %d칸 넘음' % W
    while line and line[-1] == ('t', '　'):
        line.pop()
    lines.append(line)
    res = []
    for i, ln in enumerate(lines):
        if i:
            res.append(('nl', ''))
        res += ln
    for ln in lines:
        if wlen(ln) > W:
            return its, '흘린 뒤에도 %d칸' % wlen(ln)
    return res, None


_KIWI = None
GLUE = [(r'(?:넷|네트)(?:　|<n>)?매니저', '넷매니저'), (r'넷(?:　|<n>)?아미', '넷아미'),
        (r'넷(?:　|<n>|・)?에이전트', '넷에이전트'), (r'뉴크(?:　|<n>)?포맷', '뉴크포맷'), (r'사이버(?:　|<n>)?제일', '사이버제일')]
READ_RUBY = re.compile(r'([Ａ-Ｚ]+)（(?:스탠드|에이스|스코우|스카우|노아|엠스리|콜디악|야누트|숄트|스턴트|박스)）')
# Kiwi 가 못 잡는 «앞말<u>뒷말» 띄어쓰기(외래어·이름을 한 덩어리로 묶는 경우) — 앞말·뒷말 머리
U_FORCE = [('빨리', '애널'), ('물론', '차이넬'), ('외', '생존자'), ('따위에게', '나는'), ('평화를', '가져다'), ('정말', '셰리'),
           ('분명히', '도나'), ('분명', '후라'), ('당신도', '질리지'), ('그러나', '주어지지'), ('내려가서', '가　'), ('뭐라니', '가　'),
           ('억수로', '든다'), ('감전도', '안　'), ('또', '메리콕'), ('만약', '맥노튼'), ('모습으로는', '도나'), ('도나도', '네　'),
           ('다이브로', '머리'), ('아니면', '이건'), ('딴지', '고맙'), ('나', '시스코'), ('홀로그래프', '프로젝터'), ('홀로그래프', '미러'),
           ('재패니즈', '블레이드'), ('오리엔탈', '룸'), ('차이넬', '트리'), ('먼저는', '애널'), ('여기는', '애널'), ('지금은', '콜로니'),
           ('조사는', '차이넬'), ('기사는', '플로어'), ('트랜스포드는', '플로어')]


def ruby_tidy(ko):
    """루비(<}1>본문<}2>루비<}>) 손질(사용자 2026-10-13):
      ① 한 대사 안 같은 루비 두 번째부터는 본문만 ② 루비 앞이 한글에 붙었고 앞말이 조사·어미·부사·관형사로 끝나면 띄움"""
    global _KIWI
    seen = set(); out = []; last = 0
    for m in vtext.RUBY.finditer(ko):
        out.append(ko[last:m.start()]); last = m.end()
        base, rb = m.group(1), m.group(2)
        key = re.sub(r'[\s　]', '', re.sub(r'<[^<>]*>', '', rb))
        prev = ''.join(out)
        if prev and re.match(r'[가-힣]', prev[-1:]):
            if _KIWI is None:
                from kiwipiepy import Kiwi
                _KIWI = Kiwi()
            lt = _KIWI.tokenize(re.sub(r'<[^<>]*>', ' ', prev).replace('　', ' '))
            if lt and (lt[-1].tag[0] in 'JE' or lt[-1].tag in ('MAG', 'MM') or lt[-1].form in ('그', '이', '저')):
                out.append(' ')
        out.append(base if key in seen else m.group(0))
        seen.add(key)
    out.append(ko[last:])
    return ''.join(out)


def u_space(K):
    """한글<u…>한글 → 한글　<u…>한글. 단 『』 안(이름 나이트<u>스톰) · 뒤가 조사·어미·접미사 · 한 형태소 가운데는 그대로"""
    global _KIWI
    hits = [m for m in re.finditer(r'(?<=[가-힣])(<u[^<>]*>)(?=[가-힣])', K)]
    if not hits:
        return K, 0
    if _KIWI is None:
        from kiwipiepy import Kiwi
        _KIWI = Kiwi()
    # 태그 뺀 글 + 자리 대응
    plain = []; pos = {}
    for m in re.finditer(r'<[^<>]*>|.', K, re.S):
        if m.group(0).startswith('<') and len(m.group(0)) > 1:
            pos[m.end()] = len(plain)
        else:
            plain.append(m.group(0))
    P = ''.join(plain)
    starts = {}
    for t in _KIWI.tokenize(P.replace('　', ' ')):
        starts.setdefault(t.start, t.tag)          # 같은 자리 첫 형태소(잤 = 자/VV + 았/EP → VV)
    out = K; n = 0
    for m in reversed(hits):
        if K[:m.start()].count('『') > K[:m.start()].count('』'):
            continue
        q = pos.get(m.end())
        tag = starts.get(q)
        bad = lambda t: t[0] in 'JE' or t.startswith('XS') or t == 'VCP'
        if tag is not None:
            if bad(tag):
                continue
        else:                                      # 통째 분석에 경계 없음(외래어를 «먼저는애널라이저» 로 묶음, 또는 낱말 가운데 u)
            lt = _KIWI.tokenize(P[:q].replace('　', ' '))
            rt = _KIWI.tokenize(P[q:].replace('　', ' '))
            if not lt or not rt or bad(rt[0].tag) or lt[-1].tag[0] not in 'JE':
                continue                           #  → 왼쪽만 따로 봐서 조사·어미로 끝날 때만 띄움
        out = out[:m.start()] + '　' + out[m.start():]; n += 1
    return out, n


def merge_row(i, ja, ko, f, n, fixes, names, rep, wrap=True):
    """번역 한 줄 손질(①‥⑦) → (최종 글, 비고 목록, 원문보다 줄이 늘었나)"""
    grown = False
    note = []
    for a, b in fixes.get(i, []):
        if a not in ko:
            rep['fix_miss'].append((i, a)); continue
        ko = ko.replace(a, b)
    for src, good, bad, scope in names:
        for b in bad.split(','):
            if scope == 'name':
                if re.search(r'<[^>]*c1[^>]*>%s<' % re.escape(b), ko) and src in ja:
                    ko = re.sub(r'(<[^>]*c1[^>]*>)%s(<)' % re.escape(b), r'\g<1>%s\2' % good, ko)
            elif b in ko and src in ja:
                ko = ko.replace(b, good)
    J = vtext.deruby_tags(ja)
    ko = ko.replace('。', '.').replace('、', ',')   # 번역에 섞인 일본식 부호 → 반각(아래 full 이 전각·뒤 공백 처리)
    ko = ruby_tidy(vtext.split_tags(ko))
    K = vtext.full(vtext.deruby_tags(ko))
    K = K.replace('어라이브', '얼라이브')        # 표기 통일(사용자 2026-10-13)
    # 영문 약어 뒤 «소리만 적은» 루비 괄호 빼기(ＳＴＡＮＤ（스탠드）→ＳＴＡＮＤ) — 모듈 자리 확보(사용자 2026-10-13 «살짝 다듬어»)
    K = READ_RUBY.sub(lambda m: m.group(1), K)
    # 용어 붙여 쓰기 통일(사용자 2026-10-13): 넷매니저·넷아미·넷에이전트·뉴크포맷·사이버제일
    for a, b in GLUE:
        K = re.sub(a, b, K)
    # ⑤ 머리 코드
    mj = re.match(r'(<[^<>]*>)', J); mk = re.match(r'(<[^<>]*>)', K)
    if mj and mk and mj.group(1) != mk.group(1) and J.startswith(mj.group(1)) and K.startswith(mk.group(1))                 and (mk.group(1).startswith('<m') or mj.group(1).startswith('<m')):
        K = mj.group(1) + K[len(mk.group(1)):]
    # ⑥ 빠진 u
    cj, ck = vtext.codes(J), vtext.codes(K)
    if cj != ck and cj.replace('u', '') == ck.replace('u', '') and cj.count('u') > ck.count('u'):
        need = cj.count('u') - ck.count('u')
        its = items(K); tpos = [k for k, it in enumerate(its) if it[0] == 't']
        # 원문에서 u 가 놓인 글자 비율
        ji = items(J); jt = 0; ratios = []
        jtotal = sum(1 for it in ji if it[0] == 't') or 1
        for it in ji:
            if it[0] == 't':
                jt += 1
            elif it[0] == 'c' and 'u' in it[1]:
                ratios.append(jt / jtotal)
        ratios = ratios[:need] if len(ratios) >= need else ratios + [1.0] * (need - len(ratios))
        for r in sorted(ratios, reverse=True):
            k = int(r * len(tpos))
            k = min(max(k, 0), len(tpos) - 1) if tpos else 0
            # 가까운 공백 뒤로
            for d in range(0, 6):
                if 0 <= k + d < len(tpos) and its[tpos[k + d]][1] == '　':
                    k = k + d + 1; break
            at = tpos[k] if k < len(tpos) else len(its)
            its.insert(at, ('c', 'u'))
            tpos = [q for q, it in enumerate(its) if it[0] == 't']
        K = render(its); note.append('u 되살림')
    cj, ck = vtext.codes(J), vtext.codes(K)
    if cj != ck and cj.replace('u', '') == ck.replace('u', '') and ck.count('u') > cj.count('u'):
        extra = ck.count('u') - cj.count('u')      # 번역자가 더 넣은 <u> — 뒤에서부터 뺌
        its = items(K)
        for q in range(len(its) - 1, -1, -1):
            if extra and its[q] == ('c', 'u'):
                its.pop(q); extra -= 1
        K = render(its); note.append('u 덜어냄')
        cj, ck = vtext.codes(J), vtext.codes(K)
    if cj != ck and cj.replace('u', '') == ck.replace('u', '') and cj.count('u') == ck.count('u'):
        note.append('u 자리 다름')                  # 색 코드와의 앞뒤만 다름 — 화면 차이 없음
    elif cj != ck:
        note.append('⛔코드 다름')
        rep['code'].append((i, f, n, vtext.codes(J), vtext.codes(K), ja, ko))
    # ⑥-2 <u> 띄어쓰기: u 는 화면 폭 없는 코드 → 번역자가 원문처럼 «는<u>수많은» 으로 붙이면 띄어쓰기가 사라짐
    # ⛔(2026-10-13) 틀린 진단 — <u> 는 화면에서 8px 띄우는 코드(원문 분절 띄어쓰기). 앞에 «　» 를 더하면 틈이 두 배.
    #   번역자의 «요즘<u>사람과» 가 맞다 → 띄우지 않고, 번역자가 «　<u>» 로 둔 곳은 «　» 를 지움.
    K, nu = re.subn(r'　+(<[^<>]*u[^<>]*>)', lambda m: m.group(1), K)
    K, c = re.subn(r'(<[^<>]*u[^<>]*>)　+', lambda m: m.group(1), K); nu += c
    if nu:
        note.append('u 앞뒤 빈칸 지움'); rep['u_space'].append((i, nu, K))
    # ⑦ 흘리기
    # 이어지는 줄 머리 들여쓰기 «　» 없앰(2026-10-13): 모듈 글 자리 모자람(V01 등, 0x2D0000 위는 덧프로그램 자리라 못 씀) + 줄 수 줄이기
    if NOINDENT and wrap:
        K = re.sub(r'^((?:<[^<>]*>)*)　+', lambda m: m.group(1), K)   # 첫 줄 머리 들여쓰기도 전부(사용자 2026-10-13)
        K = re.sub(r'(<[^<>]*n[^<>]*>)　(?!　)', lambda m: m.group(1), K)
    its = items(K); L = lines_of(its)
    if wrap and K != J and any(wlen(x) > W for x in L):     # 원문 그대로인 줄(ＡＬＥＲＴ<u>ＦＯＲ… 등)은 원래 꼴 유지
        jl = lines_of(items(J))
        indent = (not NOINDENT) and len(jl) > 1 and all(x and x[0] == ('t', '　') for x in jl[1:] if x)
        new, err = reflow(its, indent)
        if err:
            note.append('⛔' + err); rep['wrap'].append((i, f, n, err, K))
        else:
            K = render(new); note.append('흘림')
            K = re.sub(r'(<[^<>]*u[^<>]*>)　+', lambda m: m.group(1), K)   # <un> 이 <u> 로 풀리며 남은 줄 머리 «　»
            if len(lines_of(new)) > len(jl):
                grown = True; rep['grown'].append((i, len(jl), len(lines_of(new)), K))
    return K, note, grown


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    tr = vcheck.load('virus번역/virus_*.tsv', 3)
    fixes = collections.defaultdict(list)
    for r in read_tsv('virus_fix.tsv'):
        fixes[r[0]].append((r[1], r[2]))
    names = read_tsv('virus_names.tsv')
    rep = collections.defaultdict(list)
    out_rows = []
    grown = 0
    for i, (ja, ko, f, n) in tr.items():
        K, note, g = merge_row(i, ja, ko, f, n, fixes, names, rep)
        grown += g
        out_rows.append((i, ja, K, ' '.join(note)))
    with open(os.path.join(ROOT, 'data', 'virus_ko.tsv'), 'w', encoding='utf-8', newline='\n') as w:
        w.write('ID\t원문\t번역\t비고\n')
        for r in out_rows:
            w.write('\t'.join(r) + '\n')
    od = os.path.join(ROOT, 'work', 'check'); os.makedirs(od, exist_ok=True)
    for k, rows in rep.items():
        with open(os.path.join(od, 'merge_%s.tsv' % k), 'w', encoding='utf-8') as w:
            for r in rows:
                w.write('\t'.join(str(x) for x in r) + '\n')
    c = collections.Counter(x for r in out_rows for x in r[3].split() if x)
    print('병합 %d줄 → data/virus_ko.tsv' % len(out_rows), dict(c), {k: len(v) for k, v in rep.items()})


if __name__ == '__main__':
    main()

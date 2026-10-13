# -*- coding: utf-8 -*-
r"""받아쓰기(work/movie/asr2.tsv, 확신도 포함) → 자막 작업 TSV my files/tsv/movie_NNN.tsv (24 KB 단위)
  열: ID(영상_줄번호) · 영상(같은 내용이 여러 디스크·이름이면 «d1:S090_1 d3:…») · 시작 · 끝 · 원문(받아쓰기) · 번역 · 비고
  순서 = 디스크 1→3, 디스크 안 LBA 순(대체로 진행 순). 말 없는 영상은 뺀다.
  버림: 위스퍼 상투구 환각(«ご視聴ありがとう…» 등) · 잡음 낱말(JUNK 와 똑같은 줄).
  비고 «⚠반복»·«⚠확신 낮음»(무음확률 > 0.5 또는 평균로그확률 < -0.8)은 사람이 들어 볼 줄.
  python tools/movie_tsv.py [KB=24]
"""
import collections, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
MV = os.path.join(ROOT, 'work', 'movie'); TSV = os.path.join(ROOT, 'my files', 'tsv')
HALLU = ('ご視聴ありがとう', 'チャンネル登録', 'おやすみなさい', '最後までご覧', 'ご覧いただき', 'お疲れ様でした',
         'BGM', '字幕', '視聴者', '作詞', '作曲', 'それではまた')
# 음악·무음 위 잡음 낱말(통째로 이것뿐인 줄만). ⛔길이로 자르지 말 것 — «心って不思議なものね»·«バカな!» 같은 진짜 대사가 버려졌다
JUNK = {'音楽', 'エンディング', 'おわり', '早送り', 'アーメン', '次回予告', '音声'}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    kb = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    names = collections.OrderedDict()
    for ln in list(open(os.path.join(MV, 'list.tsv'), encoding='utf-8'))[1:]:
        d, n, dur, h, w = ln.rstrip('\n').split('\t')
        if w != '-':
            names.setdefault(w, []).append('d%s:%s' % (d, n.rsplit('.', 1)[0]))
    # VAD 끈 판(asr2)·켠 판(asr_vad) 둘 다 걸러 읽고, 영상마다 남은 글자가 많은 판을 쓴다
    def load(fn):
        out = collections.defaultdict(list); drop = 0
        for ln in list(open(os.path.join(MV, fn), encoding='utf-8'))[1:]:
            w, s, e, t, ns, lp, cr = ln.rstrip('\n').split('\t')
            t = t.strip()
            if not t:
                continue
            if any(x in t for x in HALLU) or t in JUNK:
                drop += 1
                continue
            out[w].append((float(s), float(e), t, float(ns), float(lp)))
        return out, drop
    a, dropped = load('asr2.tsv')
    b, _ = load('asr_vad.tsv')
    segs = {}; picked = collections.Counter()
    for w in set(a) | set(b):
        la = sum(len(x[2]) for x in a.get(w, [])); lb = sum(len(x[2]) for x in b.get(w, []))
        if lb > la:
            segs[w] = b[w]; picked['VAD'] += 1
        else:
            segs[w] = a[w]; picked['기본'] += 1
    print('판 고름', dict(picked))
    rows = []
    for w, ns_ in names.items():
        if w not in segs:
            continue
        base = ns_[0].split(':')[1]
        prev = None
        for k, (s, e, t, ns, lp) in enumerate(segs[w], 1):
            note = ''
            if re.search(r'(.{2,})\1{3,}', t) or t == prev:
                note = '⚠반복'
            elif ns > 0.5 or lp < -0.8:
                note = '⚠확신 낮음'
            rows.append(('%s_%02d' % (base, k), ' '.join(ns_), '%.2f' % s, '%.2f' % e, t, '', note))
            prev = t
    for p in os.listdir(TSV):
        if re.match(r'movie_\d{3}\.tsv$', p):
            os.remove(os.path.join(TSV, p))
    head = 'ID\t영상\t시작\t끝\t원문\t번역\t비고\n'
    lim = kb * 1024; cur = head; files = []

    def flush(cur):
        p = os.path.join(TSV, 'movie_%03d.tsv' % (len(files) + 1))
        open(p, 'w', encoding='utf-8', newline='').write(cur); files.append(p)
    for r in rows:
        ln = '\t'.join(r) + '\n'
        if len((cur + ln).encode('utf-8')) > lim and cur != head:
            flush(cur); cur = head
        cur += ln
    if cur != head:
        flush(cur)
    print('버린 줄(환각) %d' % dropped)
    print('대사 있는 영상 %d / 소리 있는 영상 %d · 줄 %d · 일본어 %d자 · 들어 볼 줄 %d · 파일 %d개'
          % (len(segs), len(names), len(rows), sum(len(r[4]) for r in rows), sum(1 for r in rows if r[6]), len(files)))


if __name__ == '__main__':
    main()

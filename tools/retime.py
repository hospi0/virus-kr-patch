# -*- coding: utf-8 -*-
r"""동영상 자막 시각 다시 잡기 (2026-10-13) — 자막이 대사보다 한참 먼저 뜨는 문제(S344_1 0.00초 ↔ 실제 8.18초).
  원인: movie_ko.tsv 시각 = 위스퍼 «구간» 시작 — 앞 음악·무음까지 첫 구간에 묶임.
  방법: 자막 남은 영상만 faster-whisper large-v3 를 word_timestamps 로 다시 → 구간마다 (글, 첫 낱말 시작, 마지막 낱말 끝)
        → 자막 줄(원문)을 «연속 구간 1~3개» 와 글자 유사도로 짝짓기(원래 시각 ±6초 안) → 시작 = 첫 낱말, 끝 = max(마지막 낱말 + 0.4,
        시작 + max(1.2, 0.12초×한글 글자)) 이고 다음 줄 시작 − 0.05 를 넘지 않게.
  짝 못 찾은 줄(유사도 < 0.45)은 그대로 두고 보고 work/check/retime_miss.tsv.
  결과: data/movie_ko.tsv 의 시작·끝 열을 고침(백업 work/movie_ko_before_retime.tsv). 캐시 work/movie/words.tsv.
  C:\claude\utils\whisper-venv\Scripts\python.exe tools/retime.py
"""
import csv, difflib, os, re, shutil, sys, wave
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
P = os.path.join(ROOT, 'data', 'movie_ko.tsv')
CACHE = os.path.join(ROOT, 'work', 'movie', 'words_vad.tsv' if '--vad' in sys.argv else 'words.tsv')
VAD = '--vad' in sys.argv          # 2차: 1차에서 못 찾은 줄만, VAD 켠 받아쓰기로(음악 위 대사를 VAD 끈 판이 통째로 놓침)
norm = lambda s: re.sub(r'[\s　、。！？!?…‥・「」『』（）()，．,.~〜ー-]', '', s)


def segs_of(model, wav, vad=False):
    w = wave.open(wav); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    out = []
    for s in model.transcribe(a, language='ja', word_timestamps=True, vad_filter=vad)[0]:
        ws = list(s.words or [])
        if ws:
            out.append((ws[0].start, ws[-1].end, s.text.strip()))
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    rows = list(csv.reader(open(P, encoding='utf-8'), delimiter='\t'))
    head, body = rows[0], rows[1:]
    live = [r for r in body if len(r) > 5 and r[5].strip() and '제외' not in (r[6] if len(r) > 6 else '')]
    if VAD:                                       # 1차에서 못 찾은 줄만
        mids = {l.split('	')[0] for l in open(os.path.join(ROOT, 'work', 'check', 'retime_miss.tsv'), encoding='utf-8').read().splitlines()}
        live = [r for r in live if r[0] in mids]
    vids = []
    for r in live:
        if r[1] not in vids:
            vids.append(r[1])
    lst = {l.split('\t')[1][:-4]: l.strip().split('\t')[4] for l in list(open(os.path.join(ROOT, 'work', 'movie', 'list.tsv'), encoding='utf-8'))[1:]}
    cache = {}
    if os.path.exists(CACHE):
        for l in open(CACHE, encoding='utf-8').read().splitlines():
            v, a, b, t = l.split('\t'); cache.setdefault(v, []).append((float(a), float(b), t))
    need = [v for v in vids if v not in cache]
    if need:
        from faster_whisper import WhisperModel
        m = WhisperModel('large-v3', device='cuda', compute_type='float16')
        with open(CACHE, 'a', encoding='utf-8') as f:
            for k, v in enumerate(need):
                nm = v.split()[0].split(':')[1]
                ss = segs_of(m, os.path.join(ROOT, 'work', 'movie', 'wav', lst[nm] + '.wav'), VAD)
                cache[v] = ss
                for a, b, t in ss:
                    f.write('%s\t%.2f\t%.2f\t%s\n' % (v, a, b, t.replace('\t', ' ')))
                print('  받아쓰기 %d/%d %s 구간 %d' % (k + 1, len(need), nm, len(ss)), flush=True)
    BK = os.path.join(ROOT, 'work', 'movie_ko_before_retime.tsv')
    if not VAD:
        if not os.path.exists(BK):
            shutil.copy(P, BK)
        else:                                         # 다시 돌릴 땐 시각만 조정 전 값으로 되돌림(문구 수정·제외 표시는 유지)
            ot = {x[0]: (x[2], x[3]) for x in csv.reader(open(BK, encoding='utf-8'), delimiter='	') if len(x) > 3}
            for r in body:
                if r[0] in ot and len(r) > 3:
                    r[2], r[3] = ot[r[0]]
    miss = []; moved = []
    for v in vids:
        rs = [r for r in live if r[1] == v]
        ss = cache.get(v, [])
        span = {}
        for r in rs:
            s0, e0 = float(r[2]), float(r[3]); jt = norm(r[4])
            best = (0, None)
            for i in range(len(ss)):
                for j in range(i, min(i + 3, len(ss))):
                    a, b = ss[i][0], ss[j][1]
                    if b < s0 - 6 or a > e0 + 6:
                        continue
                    t = norm(''.join(x[2] for x in ss[i:j + 1]))
                    sm = difflib.SequenceMatcher(None, jt, t)
                    q = sm.ratio()
                    # ★한 구간에 여러 줄이 든 경우(뉴스 S037_1) 줄 하나는 비율이 낮다 → 줄 글자가 구간에 «들어 있는» 정도도 봄
                    cv = sum(m.size for m in sm.get_matching_blocks()) / max(1, len(jt))
                    if i == j and len(jt) >= 6 and cv >= 0.8:
                        q = max(q, 0.45 + 0.1 * cv)
                    if q > best[0]:
                        best = (q, (a, b))
            if best[0] < 0.45:
                miss.append((r[0], '%.2f' % best[0], r[2], r[3], r[4], r[5])); continue
            a, b = best[1]
            nko = len(re.sub(r'\s', '', r[5]))
            r[2] = '%.2f' % a
            r[3] = '%.2f' % max(b + 0.4, a + max(1.2, 0.12 * nko))
            span[r[0]] = (a, b)
            moved.append((r[0], s0, a))
        # ★받아쓰기 한 구간에 자막 여러 줄이 걸리면(뉴스 S037_1 57.84‥66.34 에 08·09·10) 그 구간을 원문 글자 수 비율로 나눔
        #   — 안 나누면 셋이 같은 시작을 받고 «다음 줄 전에 끝» 처리로 둘이 0.3초로 잘려 자막이 한참 빈다(2026-10-13 실기)
        # ★받아쓰기 한 구간에 자막 여러 줄이 걸리거나(뉴스 S037_1 08·09·10) 순서가 뒤집힌 줄(S090_1_23 이 20 과 같은 시작)은
        #   ID 순으로 «앞 줄보다 0.5초 넘게 뒤가 아닌» 줄까지를 한 묶음으로 → 묶음 구간을 원문 글자 수 비율로 나눔
        #   — 안 나누면 같은 시작을 받고 «다음 줄 전에 끝» 처리로 0.3초로 잘려 자막이 한참 빈다(2026-10-13 실기)
        al = [r for r in body if r[1] == v and len(r) > 5 and r[5].strip() and '제외' not in (r[6] if len(r) > 6 else '')]
        cl = list(range(len(al)))                     # 묶음 첫 줄 번호
        for j in range(len(al)):
            for i in range(j):
                if float(al[i][2]) >= float(al[j][2]) - 0.5:
                    for k in range(i, j + 1):
                        cl[k] = min(cl[k], cl[i])
                    break
        for k in range(len(al)):
            cl[k] = cl[cl[k]]
        for c0 in sorted(set(cl)):
            g = [al[k] for k in range(len(al)) if cl[k] == c0]
            if len(g) < 2:
                continue
            nx = [float(al[k][2]) for k in range(len(al)) if cl[k] > c0 and float(al[k][2]) > min(float(x[2]) for x in g)]
            A = min(float(x[2]) for x in g)
            need = sum(max(1.2, 0.12 * len(re.sub(r'\s', '', x[5]))) for x in g)
            B = max(max(float(x[3]) for x in g), A + need)
            if nx:
                B = min(B, max(max(float(x[3]) for x in g), min(nx) - 0.05))
            ln = [max(1, len(norm(x[4]))) for x in g]; t = A
            for x, n in zip(g, ln):
                d = (B - A) * n / sum(ln)
                x[2] = '%.2f' % t; x[3] = '%.2f' % (t + d); t += d
        rs = sorted([r for r in body if r[1] == v and len(r) > 5 and r[5].strip() and '제외' not in (r[6] if len(r) > 6 else '')], key=lambda r: float(r[2]))
        for x, y in zip(rs, rs[1:]):                  # 다음 줄 시작 전에 끝
            if float(x[3]) > float(y[2]) - 0.05:
                x[3] = '%.2f' % max(float(x[2]) + 0.3, float(y[2]) - 0.05)
    with open(P, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n'); w.writerow(head); w.writerows(body)
    os.makedirs(os.path.join(ROOT, 'work', 'check'), exist_ok=True)
    with open(os.path.join(ROOT, 'work', 'check', 'retime_miss2.tsv' if VAD else 'retime_miss.tsv'), 'w', encoding='utf-8') as f:
        for m in miss:
            f.write('\t'.join(m) + '\n')
    sh = [a - s for _, s, a in moved]
    print('다시 잡은 줄 %d · 못 찾은 줄 %d · 시작이 늦춰진 평균 %.2f초(최대 %.2f)' % (len(moved), len(miss), sum(sh) / max(1, len(sh)), max(sh or [0])))


if __name__ == '__main__':
    main()

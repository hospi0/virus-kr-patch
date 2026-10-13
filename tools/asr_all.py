# -*- coding: utf-8 -*-
r"""동영상 음성 받아쓰기(faster-whisper large-v3, VAD 끔 — 짧은 외침이 버려지는 문제 피함)
  입력 work/movie/list.tsv · wav/<해시>.wav  → work/movie/asr2.tsv (wav·시작·끝·글·무음확률·평균로그확률·압축비), 이미 된 wav 는 건너뜀.
  C:\claude\utils\whisper-venv\Scripts\python.exe tools/asr_all.py [--vad]
  --vad → asr_vad.tsv (VAD 켬). VAD 끈 판은 음악 위에서 «ご視聴ありがとう» 를 지어내며 대사를 통째로 놓치고(S498_1·S424_1),
  VAD 켠 판은 짧은 외침을 버린다 → 두 판을 다 만들고 movie_tsv.py 가 영상마다 고른다.
"""
import os, sys, wave
import numpy as np
from faster_whisper import WhisperModel
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
MV = os.path.join(ROOT, 'work', 'movie')
VAD = '--vad' in sys.argv
OUT = os.path.join(MV, 'asr_vad.tsv' if VAD else 'asr2.tsv')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    order = []
    for ln in list(open(os.path.join(MV, 'list.tsv'), encoding='utf-8'))[1:]:
        w = ln.rstrip('\n').split('\t')[4]
        if w != '-' and w not in order:
            order.append(w)
    done = set()
    if os.path.exists(OUT):
        done = {ln.split('\t')[0] for ln in open(OUT, encoding='utf-8')}
    else:
        open(OUT, 'w', encoding='utf-8').write('wav\t시작\t끝\t글\t무음확률\t평균로그확률\t압축비\n')
    m = WhisperModel('large-v3', device='cuda', compute_type='float16')
    for k, w in enumerate(order):
        if w in done:
            continue
        f = wave.open(os.path.join(MV, 'wav', w + '.wav'))
        a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
        seg, _ = m.transcribe(a, language='ja', beam_size=5, condition_on_previous_text=False, vad_filter=VAD,
                              vad_parameters=dict(min_silence_duration_ms=300) if VAD else None)
        lines = ['%s\t%.2f\t%.2f\t%s\t%.3f\t%.3f\t%.2f\n' % (w, s.start, s.end, s.text.strip().replace('\t', ' '),
                                                       s.no_speech_prob, s.avg_logprob, s.compression_ratio) for s in seg]
        if not lines:
            lines = ['%s\t\t\t\t\t\t\n' % w]    # 말 없음도 기록(다시 돌리지 않게)
        with open(OUT, 'a', encoding='utf-8') as o:
            o.writelines(lines)
        print('%d/%d %s %d줄' % (k + 1, len(order), w, len(lines)), flush=True)


if __name__ == '__main__':
    main()

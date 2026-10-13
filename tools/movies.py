# -*- coding: utf-8 -*-
r"""동영상(AVI, Duck TrueMotion 1 + IMA ADPCM) 꺼내기 + 받아쓰기용 16 kHz 모노 wav.
  work/movie/d1‥d3/<이름>.AVI · work/movie/wav/<md5 앞 8자리>.wav (세 디스크에 같은 내용은 한 번)
  work/movie/list.tsv = 디스크·이름·길이(초)·md5·wav
  python tools/movies.py
"""
import hashlib, importlib, os, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
FF = r'C:\claude\utils\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe'
MV = os.path.join(ROOT, 'work', 'movie')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    rows = []; done = set()
    os.makedirs(os.path.join(MV, 'wav'), exist_ok=True)
    for n in (1, 2, 3):
        os.environ['VDISC'] = str(n)
        import disc; importlib.reload(disc)
        d = disc.Disc(disc.ROM)
        od = os.path.join(MV, 'd%d' % n); os.makedirs(od, exist_ok=True)
        for p, l, sz in sorted(d.walk(), key=lambda x: x[1]):
            if not p.upper().endswith('.AVI'):
                continue
            b = d.read(l, sz)
            us, = struct.unpack_from('<I', b, 0x20); fr, = struct.unpack_from('<I', b, 0x30)
            h = hashlib.md5(b).hexdigest()
            ap = os.path.join(od, p.replace('/', '_'))
            if not os.path.exists(ap):
                open(ap, 'wb').write(b)
            wv = os.path.join(MV, 'wav', h[:8] + '.wav')
            if h not in done and not os.path.exists(wv):
                r = subprocess.run([FF, '-v', 'error', '-y', '-i', ap, '-vn', '-ac', '1', '-ar', '16000', wv], capture_output=True)
                if r.returncode and os.path.exists(wv):
                    os.remove(wv)                # 소리 트랙 없는 영상
            done.add(h)
            rows.append((n, p, us * fr / 1e6, h, h[:8] if os.path.exists(wv) else '-'))
    with open(os.path.join(MV, 'list.tsv'), 'w', encoding='utf-8', newline='') as f:
        f.write('디스크\t이름\t길이\tmd5\twav\n')
        for r in rows:
            f.write('%d\t%s\t%.2f\t%s\t%s\n' % r)
    uniq = {r[3]: r[2] for r in rows}
    print('소리 없는 영상 %d개' % len({r[3] for r in rows if r[4] == '-'}))
    print('AVI %d개 · 고유 내용 %d개 · 고유 길이 %.1f분' % (len(rows), len(uniq), sum(uniq.values()) / 60))


if __name__ == '__main__':
    main()

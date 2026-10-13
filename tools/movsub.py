# -*- coding: utf-8 -*-
r"""동영상 자막 일괄 — data/movie_ko.tsv → 자막 겹침 → tools/tm1sub.exe enc → work/build/d<N>/<이름>.AVI (같은 내용 사본 디스크 전부).
  자막: 영상 폭 320 = 나눔고딕 ExtraBold 14px, 폭 120 = 갈무리11 12px. 흰 글자 + 검은 테두리, 아래 가운데.
  한 화면 최대 2줄 — 넘치면 줄 묶음(2줄씩)으로 나눠 글자 수 비율로 시간을 쪼갬. 띠(y0 아래)만 재부호화.
  제외: 번역 빈칸·비고에 «제외»(가사·확신 낮음 영상).
  python tools/movsub.py [영상ID …]   (예: d1:S042_1 — 없으면 전부)  --preview = 자막 첫 장면 PNG 만(work/movsub/prev)
"""
import collections, csv, os, struct, subprocess, sys, time
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tm1avi

EXE = os.path.join(HERE, 'tm1sub.exe')
WORK = os.path.join(ROOT, 'work', 'movsub')
BUILD = os.path.join(ROOT, 'work', 'build')
STYLE = {   # 폭 → (글꼴, 크기, 줄 높이, 테두리, y0)
    320: (r'C:\claude\utils\font\nanum-gothic\NanumGothicExtraBold.ttf', 14, 17, 2, 144),
    120: (r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11.ttf', 12, 14, 1, 88),
}
MAXL = 2


def cues_of():
    rows = list(csv.reader(open(os.path.join(ROOT, 'data', 'movie_ko.tsv'), encoding='utf-8'), delimiter='\t'))[1:]
    by = collections.OrderedDict()
    for r in rows:
        if not r[5].strip() or '제외' in r[6]:
            continue
        by.setdefault(r[1], []).append((float(r[2]), float(r[3]), r[5].strip()))
    return by


def wrap(text, font, maxw, d):
    words = text.split(' '); lines = []; cur = ''
    for w in words:
        t = (cur + ' ' + w) if cur else w
        if d.textlength(t, font=font) <= maxw:
            cur = t; continue
        if cur:
            lines.append(cur); cur = ''
        while d.textlength(w, font=font) > maxw:          # 낱말 하나가 넘치면 글자로
            k = len(w)
            while k > 1 and d.textlength(w[:k], font=font) > maxw:
                k -= 1
            lines.append(w[:k]); w = w[k:]
        cur = w
    if cur:
        lines.append(cur)
    return lines


def split_cues(cues, font, maxw):
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    out = []
    for s, e, t in cues:
        ls = wrap(t, font, maxw, d)
        groups = [ls[i:i + MAXL] for i in range(0, len(ls), MAXL)]
        n = [sum(len(x) for x in g) for g in groups]; tot = sum(n); a = s
        for g, k in zip(groups, n):
            b = a + (e - s) * k / tot
            out.append((a, b, g)); a = b
    return out


def render(lines, W, BH, st):
    f = ImageFont.truetype(st[0], st[1])
    im = Image.new('RGBA', (W, BH), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    y = BH - 2 - st[2] * len(lines)
    for ln in lines:
        x = (W - d.textlength(ln, font=f)) / 2
        d.text((round(x), y), ln, font=f, fill=(255, 255, 255, 255), stroke_width=st[3], stroke_fill=(0, 0, 0, 255))
        y += st[2]
    return im


def overlay(src, cues, out, prev=None):
    b = open(src, 'rb').read()
    ch = tm1avi.walk(b)
    us, = struct.unpack_from('<I', b, [x for x in ch if x[0] == b'avih'][0][1])
    vids = [x for x in ch if x[0][2:] in (b'dc', b'db') and x[0][:2].isdigit()]
    h0 = [tm1avi.header(b[o:o + sz]) for _, o, sz, _ in vids if sz][0]
    W, H = h0['xsize'], h0['ysize']
    st = STYLE[W]; y0 = st[4]; BH = H - y0
    f = ImageFont.truetype(st[0], st[1])
    sc = split_cues(cues, f, W - 8)
    imgs = {}; shown = 0
    with open(out, 'wb') as o:
        for k in range(len(vids)):
            t = k * us / 1e6
            c = next((c for c in sc if c[0] <= t < c[1]), None)
            if not c:
                o.write(b'\0'); continue
            key = tuple(c[2])
            if key not in imgs:
                im = render(c[2], W, BH, st); px = im.load(); buf = bytearray()
                for y in range(BH):
                    for x in range(W):
                        r, g, bb, a = px[x, y]
                        buf += struct.pack('<HB', (r >> 3) << 10 | (g >> 3) << 5 | (bb >> 3), a)
                imgs[key] = (bytes(buf), im)
            o.write(b'\1'); o.write(imgs[key][0]); shown += 1
    if prev:
        for i, (key, (_, im)) in enumerate(list(imgs.items())[:3]):
            bg = Image.new('RGBA', im.size, (40, 60, 80, 255)); bg.alpha_composite(im)
            bg.resize((im.width * 2, im.height * 2), Image.NEAREST).save('%s_%d.png' % (prev, i))
    return y0, len(vids), shown, len(sc), W, H


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    preview = '--preview' in sys.argv
    by = cues_of()
    os.makedirs(WORK, exist_ok=True); os.makedirs(os.path.join(WORK, 'prev'), exist_ok=True)
    log = []
    for vid, cues in by.items():
        copies = [c.split(':') for c in vid.split()]
        if args and not any('%s:%s' % (n, nm) in args or nm in args for n, nm in copies):
            continue
        n0, nm = copies[0]
        src = os.path.join(ROOT, 'work', 'movie', n0, nm + '.AVI')
        ov = os.path.join(WORK, nm + '.ovl'); tmp = os.path.join(WORK, nm + '.AVI')
        t0 = time.time()
        y0, nf, shown, ncue, W, H = overlay(src, cues, ov, os.path.join(WORK, 'prev', nm))
        if preview:
            print('%-10s %dx%d 자막 %d장면 · 프레임 %d/%d' % (nm, W, H, ncue, shown, nf)); continue
        r = subprocess.run([EXE, 'enc', src, ov, str(y0), tmp], capture_output=True)
        msg = (r.stdout + r.stderr).decode('utf-8', 'replace').strip().replace('\n', ' / ')
        if r.returncode:
            print('⛔ %s: %s' % (nm, msg)); log.append((nm, 'ERR', msg)); continue
        a, bsz = os.path.getsize(src), os.path.getsize(tmp)
        for n, cn in copies:      # ★사본은 디스크마다 이름이 다를 수 있음(d2:S287_1 = d3:R01_AP1) — 각자 이름으로
            dd = os.path.join(BUILD, n); os.makedirs(dd, exist_ok=True)
            with open(tmp, 'rb') as fi, open(os.path.join(dd, cn + '.AVI'), 'wb') as fo:
                fo.write(fi.read())
        os.remove(ov)
        print('%-10s %s %dx%d 자막 %d장면 · %d/%d프레임 · %d → %d B (%+.0f%%) · %.0fs · %s' % (
            nm, ','.join(n for n, _ in copies), W, H, ncue, shown, nf, a, bsz, (bsz / a - 1) * 100, time.time() - t0, msg[-80:]))
        log.append((nm, a, bsz))
    if log and not preview:
        ok = [x for x in log if x[1] != 'ERR']
        print('완료 %d · 실패 %d · 원래 %.1f MB → %.1f MB' % (len(ok), len(log) - len(ok),
              sum(x[1] for x in ok) / 1e6, sum(x[2] for x in ok) / 1e6))


if __name__ == '__main__':
    main()

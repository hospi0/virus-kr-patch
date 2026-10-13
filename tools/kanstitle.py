# -*- coding: utf-8 -*-
r"""장 제목 카드 «感染＃0N『…』» → «감염＃0N『…』» (SKANS01‥06.BIN).
  SKANS = [u32 크기][자료] 묶음. 장 제목 글자 묶음 = 압축(방식 1) 항목: [u16 개수] + 개수 × [u16 0x0400][u16 가로][u16 세로][8bpp 화소].
  글자 스프라이트는 뒤 배경이 구워진 네모(투명 아님) → 앞 두 글자(感·染)만: 밝은 글자 화소를 지우고 주변 배경 색으로 메운 뒤
  나눔고딕 ExtraBold 흰 글자(안티에일리어싱)를 얹어 팔레트(항목 1 의 [2:514], RGB555 BE)에서 가장 가까운 색으로.
  영어 부제(Blue Metal 등)·＃·숫자는 그대로. 다시 압축(compress_opt) 해 원래 항목 자리 안에 + 0 채움 → 파일 크기 불변.
  python tools/kanstitle.py → work/build/SKANS0N.BIN + work/view_kans_ko.png
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import vcomp
from PIL import Image, ImageDraw, ImageFont

FONT = r'C:\claude\utils\font\nanum-gothic\NanumGothicExtraBold.ttf'
NEW = '감염'


def glyph_entry(es):
    for k, e in enumerate(es):
        if e[0] != 1:
            continue
        try:
            o = vcomp.decompress(e)
        except Exception:
            continue
        cnt, = struct.unpack_from('>H', o, 0); p = 2; recs = []
        try:
            for _ in range(cnt):
                f, w, h = struct.unpack_from('>HHH', o, p)
                if f & 0xFF00 != 0x0400:
                    raise ValueError
                recs.append((p + 6, w, h)); p += 6 + w * h
        except Exception:
            continue
        if p == len(o) and recs and recs[0][1] == 24:
            return k, bytearray(o), recs
    raise SystemExit('장 제목 글자 묶음 없음')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    os.makedirs(os.path.join(ROOT, 'work', 'build'), exist_ok=True)
    sheet = []
    for n in range(1, 7):
        name = 'SKANS%02d.BIN' % n
        b = bytearray(open(os.path.join(ROOT, 'work', name), 'rb').read())
        es = vcomp.entries(bytes(b))
        k, o, recs = glyph_entry(es)
        pal = [((v & 31) * 8, ((v >> 5) & 31) * 8, ((v >> 10) & 31) * 8) for v in struct.unpack_from('>256H', es[1], 2)]
        L = [sum(c) for c in pal]
        cache = {}
        NT = None

        TT = {i for i, cc in enumerate(pal) if cc[0] >= 200 and cc[1] <= 40 and cc[2] >= 200}

        def near(c):
            key = tuple(x // 4 for x in c)
            if key not in cache:
                cache[key] = min((i for i in range(256) if i not in TT), key=lambda i: sum((pal[i][j] - c[j]) ** 2 for j in range(3)))
            return cache[key]
        before = bytes(o)
        for gi, ch in enumerate(NEW):
            p, w, h = recs[gi]
            px = [[o[p + y * w + x] for x in range(w)] for y in range(h)]
            T = {i for i, c in enumerate(pal) if c[0] >= 200 and c[1] <= 40 and c[2] >= 200}   # 자홍 = 투명
            trans = sum(1 for r in px for v in r if v in T) > w * h * 0.3
            if trans:
                # 투명 바탕(5·6장): 바탕 그대로 두고 흰 글자 + 어두운 테두리 1px
                tidx = max(T, key=lambda i: sum(1 for r in px for v in r if v == i))
                size = h + 2
                while True:
                    f = ImageFont.truetype(FONT, size)
                    bb = f.getbbox(ch)
                    if bb[2] - bb[0] <= w - 4 and bb[3] - bb[1] <= h - 3:
                        break
                    size -= 1
                a = Image.new('L', (w, h), 0)
                ImageDraw.Draw(a).text(((w - (bb[2] - bb[0])) // 2 - bb[0], (h - (bb[3] - bb[1])) // 2 - bb[1]), ch, font=f, fill=255)
                A = a.load()
                for y in range(h):
                    for x in range(w):
                        al = A[x, y] / 255
                        if al > 0.35:
                            v = near(tuple(int(16 + 232 * al) for _ in range(3)))
                        elif any(0 <= x + dx < w and 0 <= y + dy < h and A[x + dx, y + dy] > 90 for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                            v = near((16, 16, 16))
                        else:
                            v = tidx
                        o[p + y * w + x] = v
                continue
            # 글자 화소 = 밝기 합 ≥ 330(투명 색 빼고) + 둘레 1px
            ink = {(x, y) for y in range(h) for x in range(w) if L[px[y][x]] >= 330 and px[y][x] not in T}
            mask = {(x + dx, y + dy) for (x, y) in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1) if 0 <= x + dx < w and 0 <= y + dy < h}
            rgb = {(x, y): pal[px[y][x]] for y in range(h) for x in range(w)}
            todo = set(mask)
            while todo:
                done = {}
                for (x, y) in todo:
                    nb = [rgb[q] for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if q in rgb and q not in todo and px[q[1]][q[0]] not in T]
                    if nb:
                        done[(x, y)] = tuple(sum(c[i] for c in nb) // len(nb) for i in range(3))
                if not done:
                    for q in todo:
                        done[q] = (16, 16, 16)
                for q, v in done.items():
                    rgb[q] = v; todo.discard(q)
            # 한글
            size = h + 2
            while True:
                f = ImageFont.truetype(FONT, size)
                bb = f.getbbox(ch)
                if bb[2] - bb[0] <= w - 2 and bb[3] - bb[1] <= h - 2:
                    break
                size -= 1
            a = Image.new('L', (w, h), 0)
            ImageDraw.Draw(a).text(((w - (bb[2] - bb[0])) // 2 - bb[0], (h - (bb[3] - bb[1])) // 2 - bb[1]), ch, font=f, fill=255)
            A = a.load()
            for y in range(h):
                for x in range(w):
                    c = rgb[(x, y)]; al = A[x, y] / 255
                    if al > 0.05:
                        c = tuple(int(c[i] * (1 - al) + 248 * al) for i in range(3))
                    if px[y][x] in T and al <= 0.05:
                        continue
                    o[p + y * w + x] = near(c) if ((x, y) in mask or al > 0.05) else px[y][x]
        c = vcomp.compress_opt(bytes(o)); assert vcomp.decompress(c) == bytes(o)
        # 항목 k 의 자리
        pos = 0
        for i in range(k):
            pos += 4 + struct.unpack_from('>I', b, pos)[0]
        size0, = struct.unpack_from('>I', b, pos)
        if len(c) > size0:
            sys.exit('⛔ %s 압축 %d > 자리 %d' % (name, len(c), size0))
        b[pos + 4:pos + 4 + size0] = c + bytes(size0 - len(c))
        assert vcomp.decompress(vcomp.entries(bytes(b))[k]) == bytes(o)
        open(os.path.join(ROOT, 'work', 'build', name), 'wb').write(b)
        print('%s 항목 %d 글자 %d개 · 압축 %d / %d' % (name, k, len(recs), len(c), size0))
        for src in (before, bytes(o)):
            row = Image.new('RGB', (sum(w + 2 for _, w, _ in recs[:6]), 22))
            x0 = 0
            for p, w, h in recs[:6]:
                g = Image.new('RGB', (w, h)); g.putdata([pal[v] for v in src[p:p + w * h]]); row.paste(g, (x0, 0)); x0 += w + 2
            sheet.append(row)
    W = max(r.width for r in sheet); im = Image.new('RGB', (W, 24 * len(sheet)))
    for i, r in enumerate(sheet):
        im.paste(r, (0, i * 24))
    im.resize((W * 4, im.height * 4), Image.NEAREST).save(os.path.join(ROOT, 'work', 'view_kans_ko.png'))


if __name__ == '__main__':
    main()

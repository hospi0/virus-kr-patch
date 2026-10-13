# -*- coding: utf-8 -*-
r"""자막 겹침 파일(tm1sub enc 입력) 만들기.
  python tools/mkoverlay.py <in.avi> <자막.tsv|-> <y0> <out.bin> [미리보기.png]
  자막.tsv = 시작초\t끝초\t글(\n 줄바꿈) ; «-» 면 시험 문구 하나(2초~6초)
  프레임 시각 = 영상 청크 순서 × avih 프레임 간격(빈 청크도 한 프레임).
  글자: 나눔고딕 ExtraBold, 흰 글자 + 검은 테두리 2px, 띠(320×(180-y0)) 가운데 아래 정렬.
"""
import os, struct, sys
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tm1avi
FONT = r'C:\claude\utils\font\nanum-gothic\NanumGothicExtraBold.ttf'


def render(text, W, BH, px=14):
    f = ImageFont.truetype(FONT, px)
    im = Image.new('RGBA', (W, BH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines = text.split('\\n')
    lh = px + 3
    y = BH - 2 - lh * len(lines)
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = (W - w) / 2
        d.text((x, y), ln, font=f, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
        y += lh
    return im


def main():
    src, subs, y0, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    b = open(src, 'rb').read()
    ch = tm1avi.walk(b)
    avih = [x for x in ch if x[0] == b'avih'][0]
    us, = struct.unpack_from('<I', b, avih[1])
    vids = [x for x in ch if x[0][2:] in (b'dc', b'db') and x[0][:2].isdigit()]
    hdr = [tm1avi.header(b[o:o + sz]) for _, o, sz, _ in vids if sz]
    W, H = hdr[0]['xsize'], hdr[0]['ysize']
    BH = H - y0
    if subs == '-':
        cues = [(2.0, 6.0, '시험 자막입니다, 사지!\\n한글이 잘 나오나요?')]
    else:
        cues = []
        for ln in open(subs, encoding='utf-8'):
            s, e, t = ln.rstrip('\n').split('\t')[:3]
            cues.append((float(s), float(e), t))
    imgs = {}
    o = open(out, 'wb'); shown = 0; prev = None
    for k in range(len(vids)):
        t = k * us / 1e6
        cue = next((c for c in cues if c[0] <= t < c[1]), None)
        if not cue:
            o.write(b'\0'); continue
        if cue[2] not in imgs:
            imgs[cue[2]] = render(cue[2], W, BH)
        im = imgs[cue[2]]
        o.write(b'\1')
        px = im.load(); buf = bytearray()
        for y in range(BH):
            for x in range(W):
                r, g, bb, a = px[x, y]
                v = (r >> 3) << 10 | (g >> 3) << 5 | (bb >> 3)
                buf += struct.pack('<HB', v, a)
        o.write(buf); shown += 1; prev = im
    o.close()
    if len(sys.argv) > 5 and prev:
        prev.save(sys.argv[5])
    print('프레임 %d · 자막 프레임 %d · 간격 %.1f ms · %dx%d 띠 %d줄' % (len(vids), shown, us / 1000, W, H, BH))


if __name__ == '__main__':
    main()

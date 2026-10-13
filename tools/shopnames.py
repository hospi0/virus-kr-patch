# -*- coding: utf-8 -*-
r"""상점 목록 품목 이름 한글화 (2026-10-14) — 목록 이름은 글이 아니라 «구운 셀 그림»이다.
  SHOP.BIN = vcomp.entries 71개:
    21‥64 = 품목 줄 배치표(228B = [u16 폭 28][u16 높이 2] + 2워드 PN 56개 — 아래 16비트 = 셀 번호×2, 0x4000_0000 = 좌우 뒤집기)
            짝수 = 밝은 판(화소값 2 = 흰색), 홀수 = 회색 판(화소값 1 = 회색) · 22품목 × 2
    65    = «何も売るものがありません。» 줄
    69    = 셀 그림(방식 1 압축, [u16 32B 단위 수 0x3FC] + 8bpp 8×8 셀 510개) → VDP2 0x32400(셀 0x1920‥), 팔레트 뱅크 2
  이름 칸(열 0‥13)과 65번 줄에만 쓰인 셀을 비우고, 한글 이름(갈무리9, 원본처럼 숫자·로마자 반각)을 그려 중복 없이 다시 배정.
  ×·가격·M 칸(열 14‥)과 배치표에 안 쓰인 셀(가격 숫자 — 게임이 실행 중 씀)은 그대로.
  python tools/shopnames.py [--png]  → work/build/SHOP.BIN (+ work/shop/shop_ko.png 미리보기)
"""
import os, struct, sys
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disc, vcomp

FONT = r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri9.ttf'
NAMES = ['리폼25', '리폼100', '액셀라25', '액셀라100', '백신탄', '매그넘 탄', '벅샷탄', '슬러그탄', '피어싱탄',
         '넷 폭탄', '크러셔 폭탄', '넷 플래시', '기다기연 주식', '애플레사 주식', '레이벡스사 주식', 'SAGE사 주식',
         '스미타마 주식', '마크로소프트주식', '로나미사 주식', 'SOMY사 주식', '스쿼에사 주식', '차이넬사 주식']
EMPTY = '팔 수 있는 물건이 없습니다.'
NAMECOLS = 14                      # 이름 칸 = 열 0‥13 (× 는 열 14)
TOP = 6                            # 원본 글자 잉크 = 16px 줄의 6‥15


def read_orig():
    d = disc.Disc(disc.ROM)
    for p, l, s in d.walk():
        if p == 'SHOP.BIN':
            return d.read(l, s)


def render(text, val, width):
    """글 → 16×width 화소(값 val). 잉크 아래끝을 15 에 맞춤."""
    f = ImageFont.truetype(FONT, 10)
    im = Image.new('L', (width, 24), 0)
    ImageDraw.Draw(im).text((0, 0), text, font=f, fill=255)
    ref = Image.new('L', (40, 24), 0); ImageDraw.Draw(ref).text((0, 0), '한', font=f, fill=255)
    bb = ref.getbbox()
    dy = 15 - (bb[3] - 1)
    out = Image.new('L', (width, 16), 0); out.paste(im, (0, dy))
    px = out.load()
    w = out.getbbox()[2] if out.getbbox() else 0
    return [[val if px[x, y] > 127 else 0 for x in range(width)] for y in range(16)], w


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    raw = read_orig(); E = vcomp.entries(raw)
    assert len(E) == 71
    cells = vcomp.decompress(E[69]); hdr, sheet = cells[:2], bytearray(cells[2:])
    n = len(sheet) // 64; assert n == 510
    recs = {k: bytearray(E[k]) for k in range(21, 66)}
    pn = lambda k, i: struct.unpack_from('>I', recs[k], 4 + i * 4)[0]
    name_c, other_c = set(), set()
    for k in recs:
        for i in range(56):
            c = (pn(k, i) & 0xFFFF) // 2
            (name_c if (k == 65 or i % 28 < NAMECOLS) else other_c).add(c)
    blank = bytes(64)
    assert sheet[0:64] == blank                     # 셀 0 = 빈칸(배치표 0)
    free = sorted(c for c in name_c - other_c if c != 0)
    for c in free:
        sheet[c * 64:(c + 1) * 64] = blank
    have = {}                                       # 셀 그림 → 번호(재사용)
    for c in range(n):
        if c not in free:
            have.setdefault(bytes(sheet[c * 64:(c + 1) * 64]), c)
    fi = iter(free); used = 0

    def place(k, text, val, cols, x0=0):
        nonlocal used
        px, w = render(text, val, cols * 8)
        assert w + x0 <= cols * 8, (text, w)
        if x0:
            px = [[0] * x0 + r[:cols * 8 - x0] for r in px]
        for row in range(2):
            for col in range(cols):
                cell = bytes(px[row * 8 + y][col * 8 + x] for y in range(8) for x in range(8))
                if cell not in have:
                    c = next(fi); used += 1
                    sheet[c * 64:(c + 1) * 64] = cell; have[cell] = c
                struct.pack_into('>I', recs[k], 4 + (row * 28 + col) * 4, have[cell] * 2)
        return w

    for j, nm in enumerate(NAMES):
        for k, val in ((21 + 2 * j, 2), (22 + 2 * j, 1)):
            place(k, nm, val, NAMECOLS)
    # 65번 = 원본 잉크 가운데에 맞춰 가운데 정렬
    px, w = render(EMPTY, 2, 28 * 8)
    place(65, EMPTY, 2, 28, x0=(28 * 8 - w) // 2)
    print('셀: 비운 %d · 새로 쓴 %d · 남음 %d' % (len(free), used, len(free) - used))
    E2 = list(E)
    for k, r in recs.items():
        E2[k] = bytes(r)
    E2[69] = vcomp.compress_opt(hdr + bytes(sheet))
    assert vcomp.decompress(E2[69]) == hdr + bytes(sheet)
    out = b''.join(struct.pack('>I', len(e)) + e for e in E2)
    out += raw[sum(4 + len(e) for e in E):]           # 꼬리(있으면) 그대로
    assert vcomp.entries(out)[69] == E2[69]
    assert len(out) <= 0x10000, len(out)              # 0x280000 에 실림, 다음 SYSFONT 0x290000
    open(os.path.join(ROOT, 'work', 'build', 'SHOP.BIN'), 'wb').write(out)
    print('SHOP.BIN %d → %d B' % (len(raw), len(out)))
    if '--png' in sys.argv:
        pal = {0: (0, 0, 0), 1: (120, 120, 120), 2: (255, 255, 255), 3: (255, 0, 0)}
        ks = list(range(21, 66))
        im = Image.new('RGB', (28 * 8, len(ks) * 18), (30, 30, 30))
        for r, k in enumerate(ks):
            for i in range(56):
                v = pn(k, i); c = (v & 0xFFFF) // 2
                for p in range(64):
                    x, y = p % 8, p // 8
                    if v & 0x40000000:
                        x = 7 - x
                    im.putpixel(((i % 28) * 8 + x, (i // 28) * 8 + y + r * 18), pal.get(sheet[c * 64 + p], (0, 255, 0)))
        im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(os.path.join(ROOT, 'work', 'shop', 'shop_ko.png'))


if __name__ == '__main__':
    main()

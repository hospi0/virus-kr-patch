# -*- coding: utf-8 -*-
r"""VIRUS 한글 글꼴·부호화.
  FONT.DAT = 16×16 1bpp 32B × 3,456칸, JIS 정의 글자만 JIS 순으로 빈틈없이:
    0‥452 = 비한자(1행 94 · 2행 앞 14 · 숫자·로마자 62 · 히라가나 83 · 가타카나 · 그리스 · 키릴),
    453‥ = 1수준 한자 16행 1칸(亜)부터 행마다 94칸(47행은 51칸) → 칸 = 453 + (행−16)×94 + (칸−1).  (夷=500 화면 확인)
  한글(및 cp932 에 없는 글자)은 1수준 한자 칸을 빈도 순으로 차지 → 그 칸의 SJIS 코드로 부호화. 나머지 한자 칸은 빈칸으로 지움
  («가나·한자 칸 전부 덮어쓰기» — 남은 일본어 그림이 안 나오게).
  ★원본 글꼴은 16×16 칸의 왼쪽 위 12×12 만 쓰고 화면엔 12×12 로 찍힌다(축소 아님 — 2026-10-13 NBG2 대조).
  글꼴: 갈무리11(12px 크기, 잉크 11×11) 를 칸 (0,0)에 1bpp — 잉크가 0‥10 열·1‥11 행.
"""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FONTTTF = r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11.ttf'
KANJI0 = 453
SUBST = {'·': '・', '—': '―', '،': '、', 'ㅡ': 'ー'}


def kanji_slots():
    """1수준 한자 칸 → SJIS 코드 바이트"""
    out = []
    for row in range(16, 48):
        for cell in range(1, 95):
            if row == 47 and cell > 51:
                break
            out.append(bytes([row + 0xA0, cell + 0xA0]).decode('euc_jp').encode('cp932'))
    return out


SLOTS = kanji_slots()
assert SLOTS[0].decode('cp932') == '亜' and SLOTS[47].decode('cp932') == '夷'


def build_map(texts):
    """번역 글들 → {글자: SJIS 2B} (한글·cp932 없는 글자, 빈도 순)"""
    import collections
    c = collections.Counter()
    for t in texts:
        for ch in re.sub(r'<[^<>]*>', '', t):
            ch = SUBST.get(ch, ch)
            if ('\uac00' <= ch <= '\ud7a3') or ('\u3131' <= ch <= '\u318e') or not _cp(ch):
                c[ch] += 1
    chars = [ch for ch, _ in c.most_common()]
    if len(chars) > len(SLOTS):
        raise SystemExit('⛔ 한글 %d자 > 한자 칸 %d' % (len(chars), len(SLOTS)))
    return {ch: SLOTS[i] for i, ch in enumerate(chars)}


def _cp(ch):
    try:
        ch.encode('cp932'); return True
    except UnicodeEncodeError:
        return False


def in_font(ch):
    """FONT.DAT 에 있는 글자인가 — JIS X 0208 1‥47행(비한자 + 1수준 한자). ★cp932 로 인코딩된다고 글꼴에 있는 게 아니다
    (＇＂= EEFB·EEFC IBM 확장 → 그 대사에서 튕김, 2026-10-13). －～ 는 cp932↔euc 대응이 달라 따로."""
    if ch in '－～＼｜':
        return True
    try:
        e = ch.encode('euc_jp')
    except UnicodeEncodeError:
        return False
    return len(e) == 2 and e[0] >= 0xA1 and e[1] >= 0xA1 and e[0] - 0xA0 <= 47


def encode(t, cmap, allow=frozenset()):
    """allow = 원문에 이미 있는 글꼴 밖 글자(Ⅱ 등 — 원래 게임이 쓰므로 그대로 둠)"""
    out = bytearray()
    for part in re.split(r'(<[^<>]*>)', t):
        if part.startswith('<') and part.endswith('>') and len(part) >= 2:
            out += part[1:-1].encode('ascii')
            continue
        for ch in part:
            ch = SUBST.get(ch, ch)
            if ch in cmap:
                out += cmap[ch]
            else:
                if not in_font(ch) and ch not in allow:
                    raise ValueError('글꼴 밖 글자 %r (U+%04X) in %r — 튕긴다' % (ch, ord(ch), t))
                b = ch.encode('cp932')
                if len(b) != 2:
                    raise ValueError('반각/알 수 없는 글자 %r in %r' % (ch, t))
                out += b
    return bytes(out)


def render_font(cmap, orig):
    """원본 FONT.DAT → 한자 칸을 한글로(쓰지 않는 칸은 빈칸)"""
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(FONTTTF, 12)
    out = bytearray(orig)
    inv = {v: k for k, v in cmap.items()}
    for i, code in enumerate(SLOTS):
        idx = KANJI0 + i
        g = bytearray(32)
        ch = inv.get(code)
        if ch:
            im = Image.new('1', (16, 16), 0); dr = ImageDraw.Draw(im); dr.fontmode = '1'
            bb = f.getbbox(ch); w = bb[2] - bb[0]
            dr.text(((11 - w) // 2 - bb[0] if w < 11 else -bb[0], 0), ch, font=f, fill=1)
            px = im.load()
            for y in range(16):
                for x in range(16):
                    if px[x, y]:
                        g[y * 2 + x // 8] |= 0x80 >> (x % 8)
        out[idx * 32:idx * 32 + 32] = g
    return bytes(out)

# -*- coding: utf-8 -*-
r"""VIRUS 번역 글 다듬기(검사·빌드 공통).
  · 제어 코드: 원문의 ASCII 는 전부 <…> 안(extract.show). 한 <…> 안에 여러 코드가 붙어 있음(<m0420c1}1> 등).
    코드 비교는 «루비(}1 }2 })·줄바꿈(n) 뺀 나머지» 를 이어 붙여서.
  · 루비 <}1>본문<}2>루비<}> → 본문(루비) (사용자 2026-10-13).
  · 글자 칸: 글꼴이 전각뿐 → 번역의 반각 글자는 전각으로(공백 ' ' → '　'). 부호 뒤 공백은 지움.
  · 흘리기: 줄 칸 21. 줄바꿈은 공백·부호 뒤에서만, 이어지는 줄 머리 «　» 들여쓰기는 원문 꼴을 따름.
"""
import re

WIDTH = 21
PUNCT = '、。，．！？：；）」』…‥・〜～'
RUBY = re.compile(r'<\}1>(.*?)<\}2>(.*?)<\}>')
BR = re.compile(r'<([^<>]*)>')


def split_tags(t):
    """루비 코드가 다른 코드와 붙은 꼴(<u}1> <}c7n>)만 떼어 표준 꼴로(괄호 바꾸기 전)"""
    return deruby_tags(t, paren=False)


def deruby_tags(t, paren=True):
    """원문·번역 공통: 루비 코드가 다른 코드와 붙은 꼴(<u}1> <}c7n>)을 떼어 표준 꼴로."""
    def split(m):
        s = m.group(1); out = []; cur = ''
        i = 0
        while i < len(s):
            if s[i] == '}':
                if cur: out.append(cur); cur = ''
                if i + 1 < len(s) and s[i + 1] in '12':
                    out.append('}' + s[i + 1]); i += 2
                else:
                    out.append('}'); i += 1
            else:
                cur += s[i]; i += 1
        if cur: out.append(cur)
        return ''.join('<%s>' % x for x in out)
    t = BR.sub(split, t)
    if not paren:
        return t
    return RUBY.sub(lambda m: '%s(%s)' % (m.group(1), m.group(2)), t)


def codes(t):
    """비교용 코드 열(루비·n 빼고)"""
    out = []
    for c in BR.findall(t):
        c = re.sub(r'\}[12]?', '', c).replace('n', '')
        if c:
            out.append(c)
    return ''.join(out)


def full(s):
    """제어 코드 밖의 반각 → 전각
    ★' " 를 +0xFEE0 하면 ＇＂(cp932 EEFB·EEFC, IBM 확장) — 글꼴 밖이라 그 대사에서 튕긴다 → ‘’ “” 여닫기 번갈아."""
    parts = re.split(r'(<[^<>]*>)', s)
    qn = {"'": 0, '"': 0}
    for i, p in enumerate(parts):
        if p.startswith('<'):
            continue
        q = []
        for ch in p:
            o = ord(ch)
            if ch in "'＇":
                q.append('‘’'[qn["'"] % 2]); qn["'"] += 1
            elif ch in '"＂':
                q.append('“”'[qn['"'] % 2]); qn['"'] += 1
            elif ch == ' ':
                q.append('　')
            elif 0x21 <= o <= 0x7E:
                q.append(chr(o + 0xFEE0))
            else:
                q.append(ch)
        parts[i] = ''.join(q)
    s = ''.join(parts)
    return re.sub('([' + re.escape(PUNCT) + '])　(?!　)', r'\1', s)   # 부호 뒤 공백 1칸 지움


def split_lines(t):
    """→ [(줄 글, 그 줄 뒤에 붙은 코드)] — 줄 = n 을 포함한 <…> 로 끊음"""
    parts = re.split(r'(<[^<>]*n[^<>]*>)', t)
    return parts


def width(s):
    return len(re.sub(r'<[^<>]*>', '', s))

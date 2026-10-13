/* Duck TrueMotion 1 (16비트, 압축 8 = RGB16H 2x2) — 디코더 + «자막 띠» 재부호화기
 *
 *  tm1sub dec <in.avi> <out.rgb>                  모든 영상 프레임을 RGB555(u16 LE) 로 (ffmpeg 대조용)
 *  tm1sub enc <in.avi> <overlay.bin> <y0> <out.avi> [skip_thr]
 *       overlay.bin = 프레임(00dc 순서)마다 u8 플래그(0/1) + 플래그 1이면 w*(h-y0) 개의 (u16 RGB555 LE, u8 알파 0..255)
 *       y0 = 띠 시작 줄(4의 배수). 줄 y0 위는 원래 바이트를 그대로 두고, y0..h-1 만 «원래 화면+자막» 에 맞춰 새로 부호화.
 *       한 번 띠를 건드리면 그 뒤 프레임은 끝까지 띠를 계속 새로 부호화한다(원래 바이트는 원래 띠 화면을 전제로 하므로).
 *
 *  형식 = ffmpeg libavcodec/truemotion1.c (표: work/tm1ref/truemotion1data.h, LGPL) 그대로 흉내. 새로 만든 프레임은
 *  같은 디코더로 다시 풀어 인코더가 계산한 화면과 비트 단위로 같은지 확인한다(다르면 중단).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdint.h>
#include "../work/tm1ref/truemotion1data.h"

static uint32_t ytab[1024], ctab[1024];
static int Y0[1024], Y1[1024], CR[1024], CB[1024];   /* 표 항목의 채널별 값(쌍 두 화소 y, 색차 r·b) */

static void die(const char *m) { fprintf(stderr, "오류: %s\n", m); exit(1); }

static int cur_ds = -1, cur_vt = -1;
static void make_tables(int deltaset, int vectable)
{
    cur_ds = deltaset; cur_vt = vectable;
    int16_t ydt[8], cdt[8];
    memcpy(ydt, ydts[deltaset], 16); memcpy(cdt, cdts[deltaset], 16);
    for (int i = 0; i < 8; i++) { ydt[i] &= 0xFFFE; ydt[i] /= 2; }
    const uint8_t *t = tables[vectable - 1];
    memset(ytab, 0, sizeof ytab); memset(ctab, 0, sizeof ctab);
    for (int i = 0; i < 1024; i += 4) {
        int len = *t++ / 2, j;
        for (j = 0; j < len; j++) {
            uint8_t dp = *t++;
            int p1 = dp >> 4, p2 = dp & 15;
            int lo = ydt[p1]; lo += lo * 32 + lo * 1024;
            int hi = ydt[p2]; hi += hi * 32 + hi * 1024;
            ytab[i + j] = 0xfffffffe & (uint32_t)((lo + hi * 65536) * 2);
            Y0[i + j] = ydt[p1]; Y1[i + j] = ydt[p2]; CR[i + j] = cdt[p1]; CB[i + j] = cdt[p2];
            int b = cdt[p2], r = cdt[p1] * 1024, l2 = b + r;
            ctab[i + j] = 0xfffffffe & (uint32_t)((l2 + l2 * 65536) * 2);
        }
        ytab[i + j - 1] |= 1; ctab[i + j - 1] |= 1;
    }
}

/* ---------------- AVI ---------------- */
typedef struct { char id[5]; long off; uint32_t size; int movi; } Chunk;   /* off = 데이터 시작 */
static uint8_t *file; static long flen;
static Chunk *ck; static int nck, cap;
static long movi_list_off = -1;   /* «LIST» 위치 */

static void walk(long off, long end, int in_movi)
{
    while (off + 8 <= end) {
        uint32_t sz; memcpy(&sz, file + off + 4, 4);
        if (!memcmp(file + off, "LIST", 4) || !memcmp(file + off, "RIFF", 4)) {
            int mv = !memcmp(file + off + 8, "movi", 4);
            if (mv) movi_list_off = off;
            if (nck == cap) { cap = cap ? cap * 2 : 1024; ck = realloc(ck, cap * sizeof *ck); }
            Chunk c; memcpy(c.id, file + off, 4); c.id[4] = 0; c.off = off + 8; c.size = sz; c.movi = in_movi;
            ck[nck++] = c;                       /* 목록 머리도 기록(다시 쓸 때 크기 고침) */
            walk(off + 12, off + 8 + sz, in_movi || mv);
        } else {
            if (nck == cap) { cap = cap ? cap * 2 : 1024; ck = realloc(ck, cap * sizeof *ck); }
            Chunk c; memcpy(c.id, file + off, 4); c.id[4] = 0; c.off = off + 8; c.size = sz; c.movi = in_movi;
            ck[nck++] = c;
        }
        off += 8 + sz + (sz & 1);
    }
}

static void load(const char *p)
{
    FILE *f = fopen(p, "rb"); if (!f) die("입력 열기");
    fseek(f, 0, SEEK_END); flen = ftell(f); fseek(f, 0, SEEK_SET);
    file = malloc(flen); if (fread(file, 1, flen, f) != (size_t)flen) die("읽기"); fclose(f);
    walk(0, flen, 0);
}

static int is_video(const Chunk *c) { return c->movi && (!memcmp(c->id + 2, "dc", 2) || !memcmp(c->id + 2, "db", 2)) && isdigit((unsigned char)c->id[0]); }

/* ---------------- 프레임 머리 ---------------- */
typedef struct { int hs, compression, deltaset, vectable, xsize, ysize, keyframe; } Hdr;
static int parse_hdr(const uint8_t *b, int size, Hdr *h)
{
    if (size < 1 || b[0] < 0x10) return -1;
    h->hs = ((b[0] >> 5) | (b[0] << 3)) & 0x7f;
    if (h->hs + 1 > size) return -1;
    uint8_t hb[128] = {0};
    for (int i = 1; i < h->hs; i++) hb[i - 1] = b[i] ^ b[i + 1];
    h->compression = hb[0]; h->deltaset = hb[1]; h->vectable = hb[2];
    h->ysize = hb[3] | hb[4] << 8; h->xsize = hb[5] | hb[6] << 8;
    int version = hb[9], htype = hb[10], flags = hb[11];
    if (version >= 2 && (htype == 2 || htype == 3)) { if (!(flags & 8)) flags |= 16; }
    else flags = 16;
    h->keyframe = (flags & 16) != 0;
    return 0;
}

/* ---------------- 블록 방식(ffmpeg compression_types, RGB16H 만) ----------------
   8 = 2x2: 0·2 줄 C-Y C-Y · 4 = 4x2: 0·2 줄 C-Y Y · 2 = 4x4: 0 줄 C-Y Y, 2 줄 Y Y. 1·3 줄은 늘 Y Y. */
static int comp_ok(int c) { return c == 8 || c == 4 || c == 2; }
static void cslots(int c, int t, int *c1, int *c2)
{
    *c1 = (c == 2 && t == 2) ? 0 : 1;
    *c2 = c == 8;
}

/* ---------------- 디코더 ---------------- */
typedef struct {
    int w, h, pw;            /* pw = 줄당 화소 쌍 수 */
    uint32_t *frame;         /* pw*h */
    uint32_t *vert;          /* pw */
} Dec;

typedef struct {             /* 띠 시작 직전 상태 */
    int y0;
    int consumed;            /* 읽은 색인 바이트 수 */
    int index;               /* 다음 칸이 쓸 항목 */
    int got;
} Trace;

typedef struct { const uint8_t *s; int n, pos, oob; } IStream;
static inline int getidx(IStream *is) { if (is->pos >= is->n) { is->oob++; return 0; } return is->s[is->pos++] * 4; }

/* 슬롯 하나 적용(ffmpeg APPLY_?_PREDICTOR 와 같음) */
static inline void apply(const uint32_t *tab, uint32_t *horiz, int *index, IStream *is, int *err)
{
    uint32_t pp = tab[*index];
    *horiz += pp >> 1;
    if (pp & 1) {
        *index = getidx(is);
        if (!*index) {
            *index = getidx(is);
            pp = tab[*index];
            *horiz += (pp >> 1) * 5;
            if (pp & 1) *index = getidx(is);
            else { if (*index >= 1023) (*err)++; else (*index)++; }
        }
    } else { if (*index >= 1023) (*err)++; else (*index)++; }
}

/* 프레임 풀기. tr 이 있으면 줄 tr->y0 시작 직전 상태를 적는다 */
static int decode(Dec *d, const uint8_t *buf, int size, Trace *tr)
{
    Hdr h; if (parse_hdr(buf, size, &h)) return -1;
    if (h.compression == 0) return 0;                 /* NOP: 화면 그대로 */
    if (!comp_ok(h.compression)) return -2;
    if (h.deltaset != cur_ds || h.vectable != cur_vt) make_tables(h.deltaset, h.vectable);   /* OPA 처럼 중간에 바뀜 */
    if (h.xsize != d->w || h.ysize != d->h) return -3;
    int rowsz = ((d->w >> 2) + 7) >> 3;
    const uint8_t *mb = buf + h.hs;
    IStream is; is.s = h.keyframe ? mb : mb + rowsz * (d->h >> 2); is.n = size - (int)(is.s - buf); is.pos = 0; is.oob = 0;
    int err = 0, index;
    memset(d->vert, 0, d->pw * 4);
    index = getidx(&is);
    for (int y = 0; y < d->h; y++) {
        if (tr && y == tr->y0) { tr->consumed = is.pos; tr->index = index; tr->got = 1; }
        uint32_t horiz = 0, *cur = d->frame + y * d->pw, *vp = d->vert;
        int mi = 0; uint8_t mbyte = 0, mask = 1;
        if (!h.keyframe) mbyte = mb[mi++];
        for (int x = 0; x < d->pw; x += 2) {
            if (h.keyframe || !(mbyte & mask)) {
                int t = y & 3;
                if (t == 0 || t == 2) {
                    int c1, c2; cslots(h.compression, t, &c1, &c2);
                    if (c1) apply(ctab, &horiz, &index, &is, &err);
                    apply(ytab, &horiz, &index, &is, &err);
                    *cur = *vp + horiz; *vp++ = *cur++;
                    if (c2) apply(ctab, &horiz, &index, &is, &err);
                    apply(ytab, &horiz, &index, &is, &err);
                    *cur = *vp + horiz; *vp++ = *cur++;
                } else {
                    apply(ytab, &horiz, &index, &is, &err); *cur = *vp + horiz; *vp++ = *cur++;
                    apply(ytab, &horiz, &index, &is, &err); *cur = *vp + horiz; *vp++ = *cur++;
                }
            } else {
                *vp++ = *cur++;
                horiz = *cur - *vp;
                *vp++ = *cur++;
            }
            if (!h.keyframe) { mask <<= 1; if (!mask) { mbyte = mb[mi++]; mask = 1; } }
        }
        if (((y + 1) & 3) == 0) mb += rowsz;
    }
    if (err) return -4;
    /* 마지막 벡터 끝에서 다음 바이트를 미리 읽는 것은 허용(스트림 끝 1회) */
    if (is.oob > 1) return -5;
    return is.pos;
}

/* ---------------- 인코더(띠) ---------------- */
/* 사건: 0=C 슬롯, 1=Y 슬롯, 2=출력(pair), 3=건너뜀(pair 2개), 4=줄 시작(horiz=0) */
typedef struct { uint8_t t; int16_t pair; int16_t y; } Ev;

static Ev *ev; static int nev;
static uint32_t *TGT;      /* 목표 화면 pair 값(pw*h) — 띠 부분만 의미 */
static uint32_t *ORIG_BIT; /* 원래 pair 값(비트15 보존 비교용) */

static inline int pix_err(uint32_t v, uint32_t t)
{
    int e = 0;
    for (int k = 0; k < 2; k++) {
        uint32_t a = (v >> (16 * k)) & 0xffff, b = (t >> (16 * k)) & 0xffff;
        int dr = (int)((a >> 10) & 31) - (int)((b >> 10) & 31);
        int dg = (int)((a >> 5) & 31) - (int)((b >> 5) & 31);
        int db = (int)(a & 31) - (int)(b & 31);
        e += dr * dr * 3 + dg * dg * 4 + db * db * 2;
        /* 비트 15 는 덧셈 자리올림 찌꺼기(원래 영상 화소 25% 가 1) — 재생기가 안 쓰므로 비교하지 않는다 */
    }
    return e;
}

/* ★채널별 추적(2026-10-13 시험판 9): 화소 쌍은 32비트에 묶여 더해지는데 채널 값이 0‥31 을 벗어나면 옆 채널로 자리올림이 번진다.
   PC(ffmpeg)는 R·G·B, 새턴은 B·G·R 순으로 묶으므로 범위를 벗어난 값은 ffmpeg 에선 비슷해 보여도 새턴에선 원색 잡음.
   원본 스트림은 범위 밖 0(OPA 2.1억 채널 중 7) — 인코더도 모든 출력 채널이 0‥31 인 선택만 허용. hc = 쌍의 두 화소 r,g,b 누적 */
typedef struct { int ev; uint32_t horiz; int index; int hc[6]; } St;
static long INFEAS;          /* 범위를 지킬 수 없어 범위 밖을 고른 횟수(프레임마다 0 이어야 함) */
#define BIG 1000000000L
static inline int fld(uint32_t v, int k, int c) { return (v >> (16 * k + 10 - 5 * c)) & 31; }
static inline void addc(int *hc, const uint32_t *tab, int idx, int mul)
{
    if (tab == ytab) { for (int c = 0; c < 3; c++) { hc[c] += Y0[idx] * mul; hc[3 + c] += Y1[idx] * mul; } }
    else { hc[0] += CR[idx] * mul; hc[2] += CB[idx] * mul; hc[3] += CR[idx] * mul; hc[5] += CB[idx] * mul; }
}
static inline int out_ok(uint32_t vert, const int *hc)
{
    for (int k = 0; k < 2; k++) for (int c = 0; c < 3; c++) { int x = fld(vert, k, c) + hc[k * 3 + c]; if (x < 0 || x > 31) return 0; }
    return 1;
}
static inline void skip_hc(int *hc, uint32_t b, uint32_t vprev)
{
    for (int k = 0; k < 2; k++) for (int c = 0; c < 3; c++) hc[k * 3 + c] = fld(b, k, c) - fld(vprev, k, c);
}
/* 미리보기에서 쓴 vert 덮어쓰기(작은 목록) */
typedef struct { int pair; uint32_t v; } Ov;

static uint32_t *VERT, *FRM; static int PW;

static inline uint32_t vget(Ov *ov, int nov, int p) { for (int i = nov - 1; i >= 0; i--) if (ov[i].pair == p) return ov[i].v; return VERT[p]; }

/* 상태 s 에서, 현재 index 가 가리키는 벡터를 끝(마지막 항목)까지 적용하고, 그 뒤 «다음 슬롯 전까지»의 출력·건너뜀도 진행.
   ⚠마지막 항목 뒤 출력을 비용에서 빼면 길이 2 벡터들이 모두 비용 0 이 되어 아무거나 고른다(2026-10-12 띠가 잡음으로 무너짐).
   돌려줌: 비용, s 는 다음 슬롯 직전 상태(ev 는 그 슬롯), *ended = 벡터 끝까지 갔는지 */
static long sim_vector(St *s, Ov *ov, int *nov, int *ended)
{
    long cost = 0; *ended = 0;
    while (s->ev < nev) {
        Ev e = ev[s->ev];
        if (e.t == 4) { s->horiz = 0; memset(s->hc, 0, sizeof s->hc); s->ev++; continue; }
        if (e.t == 2) {
            uint32_t vp = vget(ov, *nov, e.pair), v = vp + s->horiz;
            cost += pix_err(v, TGT[e.y * PW + e.pair]);
            if (!out_ok(vp, s->hc)) return BIG;      /* ★바로 돌려줌 — 쌓으면 32비트 long 이 넘쳐 음수(Windows LLP64) */
            ov[(*nov)++] = (Ov){ e.pair, v };
            s->ev++; continue;
        }
        if (e.t == 3) {      /* 건너뜀: 앞 화면 복사 */
            uint32_t a = FRM[e.y * PW + e.pair], b = FRM[e.y * PW + e.pair + 1];
            ov[(*nov)++] = (Ov){ e.pair, a };
            uint32_t vp1 = vget(ov, *nov, e.pair + 1);
            s->horiz = b - vp1; skip_hc(s->hc, b, vp1);
            ov[(*nov)++] = (Ov){ e.pair + 1, b };
            s->ev++; continue;
        }
        if (*ended) return cost;           /* 다음 슬롯 — 여기서 멈춤 */
        const uint32_t *tab = e.t == 0 ? ctab : ytab;
        uint32_t pp = tab[s->index];
        s->horiz += pp >> 1; addc(s->hc, tab, s->index, 1);
        s->ev++;
        if (pp & 1) *ended = 1;
        else s->index++;
    }
    return cost;
}

static uint8_t *OUT; static int nout, capout;
static void emit(int b) { if (nout == capout) { capout = capout ? capout * 2 : 65536; OUT = realloc(OUT, capout); } OUT[nout++] = (uint8_t)b; }

/* 결정: s 는 «마지막 항목 적용 직후». 탈출(현재 슬롯에 5배 추가) 여부 + 다음 벡터 바이트를 고른다.
   cur_tab = 방금 슬롯의 표(탈출 값은 같은 표에서) */
static long LAMBDA = 0;   /* 바이트 하나의 비용(오차 단위) — 클수록 작고 거칠게 */
static const uint32_t *ETAB;   /* 탈출 값의 표(= 방금 슬롯 표) */
static long eval_opt(const St *s, uint32_t extra, int ek, int index, Ov *ov, int nov0)
{
    St t = *s; t.horiz += extra; t.index = index; int nov = nov0, ended;
    if (ek >= 0) addc(t.hc, ETAB, ek, 5);
    return sim_vector(&t, ov, &nov, &ended);
}

/* ★한 단계 더 내다보기(2026-10-13): 색차 슬롯에서 벡터가 끝나면 «C → Y → 출력» 의 출력은 시뮬레이션 밖이라,
   C 값이 R·B 를 끝으로 밀어 두면 Y(세 채널 같이)로 못 되돌리는 막다른 길이 생긴다(S042_1 79프레임 실패).
   후보의 끝 상태에서 다음 출력까지 남은 슬롯(Y 하나 / C+Y)을 «표에 있는 값 아무거나»로 채워 범위를 지킬 수 있는지 본다. */
static int YP[1024][2], NYP, CP[1024][2], NCP, PDS = -1, PVT = -1;
static void build_pairs(void)
{
    NYP = NCP = 0;
    for (int i = 0; i < 1024; i++) {
        int dup = 0;
        for (int j = 0; j < NYP; j++) if (YP[j][0] == Y0[i] && YP[j][1] == Y1[i]) { dup = 1; break; }
        if (!dup) { YP[NYP][0] = Y0[i]; YP[NYP][1] = Y1[i]; NYP++; }
        dup = 0;
        for (int j = 0; j < NCP; j++) if (CP[j][0] == CR[i] && CP[j][1] == CB[i]) { dup = 1; break; }
        if (!dup) { CP[NCP][0] = CR[i]; CP[NCP][1] = CB[i]; NCP++; }
    }
    PDS = cur_ds; PVT = cur_vt;
}
static int y_fits(const int base[6])
{
    int lo0 = -99, hi0 = 99, lo1 = -99, hi1 = 99;
    for (int c = 0; c < 3; c++) {
        if (-base[c] > lo0) lo0 = -base[c];
        if (31 - base[c] < hi0) hi0 = 31 - base[c];
        if (-base[3 + c] > lo1) lo1 = -base[3 + c];
        if (31 - base[3 + c] < hi1) hi1 = 31 - base[3 + c];
    }
    if (lo0 > hi0 || lo1 > hi1) return 0;
    for (int j = 0; j < NYP; j++) if (YP[j][0] >= lo0 && YP[j][0] <= hi0 && YP[j][1] >= lo1 && YP[j][1] <= hi1) return 1;
    return 0;
}
static int look_ok(const St *t, Ov *ov, int nov)
{
    int nslot = 0, types[4];
    for (int i = t->ev; i < nev; i++) {
        Ev e = ev[i];
        if (e.t == 4 || e.t == 3) return 1;          /* 줄 시작·건너뜀 → 누적이 새로 잡힘 */
        if (e.t == 2) {
            uint32_t vp = vget(ov, nov, e.pair); int base[6];
            for (int k = 0; k < 2; k++) for (int c = 0; c < 3; c++) base[k * 3 + c] = fld(vp, k, c) + t->hc[k * 3 + c];
            if (nslot == 1 && types[0] == 1) return y_fits(base);
            if (nslot == 2 && types[0] == 0 && types[1] == 1) {
                for (int j = 0; j < NCP; j++) {
                    int b2[6]; memcpy(b2, base, sizeof b2);
                    b2[0] += CP[j][0]; b2[3] += CP[j][0]; b2[2] += CP[j][1]; b2[5] += CP[j][1];
                    if (y_fits(b2)) return 1;
                }
                return 0;
            }
            return 1;
        }
        if (nslot < 4) types[nslot] = e.t;
        nslot++;
    }
    return 1;
}
typedef struct { long cost; int bk, bb, ek, index; uint32_t extra; } Cand;
static int cand_cmp(const void *a, const void *b) { long x = ((const Cand *)a)->cost, y = ((const Cand *)b)->cost; return x < y ? -1 : x > y; }

static void decide(St *s, const uint32_t *cur_tab, int allow_escape, Ov *ov, int *nov_io)
{
    long best = -1; int bk = -1, bb = -1; /* bk=-1 이면 탈출 없음, bb=-2 이면 k 의 나머지 항목으로 이어감 */
    int nov0 = *nov_io; ETAB = cur_tab;
    if (PDS != cur_ds || PVT != cur_vt) build_pairs();
    static Cand cand[4096]; int nc = 0;
    /* (가) 탈출 없이 바이트 b */
    for (int b = (allow_escape ? 1 : 0); b < 256; b++) {
        long c = eval_opt(s, 0, -1, b * 4, ov, nov0) + LAMBDA;
        cand[nc++] = (Cand){ c, -1, b, -1, b * 4, 0 };
        if (best < 0 || c < best) { best = c; bk = -1; bb = b; }
    }
    if (allow_escape) {
        /* (나) 탈출 0,k — 첫 항목이 마지막이 아닌 k: k 의 나머지로 이어감(정밀 평가 256번) */
        for (int k = 1; k < 256; k++)   /* k=0 도 원본엔 없음 */ {
            uint32_t pp = cur_tab[k * 4];
            if (pp & 1) continue;
            long cc = eval_opt(s, (pp >> 1) * 5, k * 4, k * 4 + 1, ov, nov0) + 2 * LAMBDA + 1;
            cand[nc++] = (Cand){ cc, k, -2, k * 4, k * 4 + 1, (pp >> 1) * 5 };
            if (cc < best) { best = cc; bk = k; bb = -2; }
        }
        /* (다) 첫 항목이 마지막인 k: 5배 값 종류별로 «0 벡터(바이트 1)» 를 붙인 대략 비용 → 상위 6 값만 날바이트 c 전부 평가 */
        uint32_t vals[256]; int vk[256], nv = 0; long proxy[256];
        for (int k = 1; k < 256; k++) {
            uint32_t pp = cur_tab[k * 4];
            if (!(pp & 1)) continue;
            uint32_t v = (pp >> 1) * 5; int dup = 0;
            for (int j = 0; j < nv; j++) if (vals[j] == v) { dup = 1; break; }
            if (dup) continue;
            vals[nv] = v; vk[nv] = k; proxy[nv] = eval_opt(s, v, k * 4, 1 * 4, ov, nov0); nv++;
        }
        for (int i = 0; i < nv && i < 6; i++) for (int j = i + 1; j < nv; j++) if (proxy[j] < proxy[i]) {
            long tp = proxy[i]; proxy[i] = proxy[j]; proxy[j] = tp;
            uint32_t tv = vals[i]; vals[i] = vals[j]; vals[j] = tv; int tk = vk[i]; vk[i] = vk[j]; vk[j] = tk;
        }
        /* ★c = 0 금지: 탈출 바로 뒤 색인 0 은 ffmpeg 는 «벡터 0» 이지만 새턴 재생기는 다시 탈출로 읽음
           (원본 스트림엔 0회 — 2026-10-13 시험판 8 OPA 띠가 통째로 깨짐) */
        for (int i = 0; i < nv && i < 6; i++)
            for (int c = 1; c < 256; c++) {
                long cc = eval_opt(s, vals[i], vk[i] * 4, c * 4, ov, nov0) + 3 * LAMBDA + 2;
                cand[nc++] = (Cand){ cc, vk[i], c, vk[i] * 4, c * 4, vals[i] };
                if (cc < best) { best = cc; bk = vk[i]; bb = c; }
            }
    }
    /* 비용순으로 «다음 출력까지 범위 지킬 수 있는» 첫 후보 */
    qsort(cand, nc, sizeof *cand, cand_cmp);
    for (int i = 0; i < nc && cand[i].cost < BIG; i++) {
        St t = *s; t.horiz += cand[i].extra; t.index = cand[i].index; int nov = nov0, ended;
        if (cand[i].ek >= 0) addc(t.hc, ETAB, cand[i].ek, 5);
        sim_vector(&t, ov, &nov, &ended);
        if (look_ok(&t, ov, nov)) { best = cand[i].cost; bk = cand[i].bk; bb = cand[i].bb; break; }
    }
    /* 확정 */
    if (best >= BIG) INFEAS++;
    if (bk < 0) { emit(bb); s->index = bb * 4; }
    else {
        emit(0); emit(bk);
        uint32_t pp = cur_tab[bk * 4];
        s->horiz += (pp >> 1) * 5; addc(s->hc, cur_tab, bk * 4, 5);
        if (pp & 1) { emit(bb); s->index = bb * 4; }
        else s->index = bk * 4 + 1;
    }
}

/* 띠 부호화: 사건 목록을 따라 진행(실제 VERT/FRM 갱신) */
static void encode_events(St st)
{
    static Ov ov[8192]; int nov = 0;      /* 미리보기 덮어쓰기 — 건너뛴 블록이 이어지면 줄 전체(160)를 넘을 수 있다 */
    while (st.ev < nev) {
        Ev e = ev[st.ev];
        if (e.t == 4) { st.horiz = 0; memset(st.hc, 0, sizeof st.hc); st.ev++; continue; }
        if (e.t == 2) {
            if (!out_ok(VERT[e.pair], st.hc)) { if (!INFEAS && getenv("TMDBG")) fprintf(stderr, "범위밖 y%d p%d vert %08x hc %d %d %d %d %d %d\n", e.y, e.pair, VERT[e.pair], st.hc[0], st.hc[1], st.hc[2], st.hc[3], st.hc[4], st.hc[5]); INFEAS++; }
            uint32_t v = VERT[e.pair] + st.horiz;
            FRM[e.y * PW + e.pair] = v; VERT[e.pair] = v; st.ev++; continue;
        }
        if (e.t == 3) {
            VERT[e.pair] = FRM[e.y * PW + e.pair];
            st.horiz = FRM[e.y * PW + e.pair + 1] - VERT[e.pair + 1]; skip_hc(st.hc, FRM[e.y * PW + e.pair + 1], VERT[e.pair + 1]);
            VERT[e.pair + 1] = FRM[e.y * PW + e.pair + 1];
            st.ev++; continue;
        }
        const uint32_t *tab = e.t == 0 ? ctab : ytab;
        uint32_t pp = tab[st.index];
        st.horiz += pp >> 1; addc(st.hc, tab, st.index, 1);
        st.ev++;
        if (pp & 1) { nov = 0; decide(&st, tab, 1, ov, &nov); }
        else st.index++;
    }
}

int main(int argc, char **argv)
{
    if (argc < 4) { fprintf(stderr, "쓰는 법: tm1sub dec in.avi out.rgb | enc in.avi overlay.bin y0 out.avi [skip_thr]\n"); return 1; }
    load(argv[2]);
    /* 첫 영상 프레임 머리로 크기·표 */
    int W = 0, H = 0, ds = -1, vt = -1;
    for (int i = 0; i < nck; i++) if (is_video(&ck[i]) && ck[i].size) {
        Hdr h; if (!parse_hdr(file + ck[i].off, ck[i].size, &h) && h.compression) { W = h.xsize; H = h.ysize; ds = h.deltaset; vt = h.vectable; break; }
    }
    if (!W) die("영상 프레임 없음");
    make_tables(ds, vt);
    Dec d = { W, H, W / 2, calloc(W / 2 * H, 4), calloc(W / 2, 4) };

    if (!strcmp(argv[1], "dec")) {
        FILE *o = fopen(argv[3], "wb");
        int n = 0;
        for (int i = 0; i < nck; i++) if (is_video(&ck[i])) {
            if (ck[i].size) { int r = decode(&d, file + ck[i].off, ck[i].size, NULL); if (r < 0) { fprintf(stderr, "프레임 %d 오류 %d\n", n, r); } }
            for (int k = 0; k < d.pw * H; k++) { uint32_t v = d.frame[k]; uint16_t a = v & 0xffff, b = v >> 16; fwrite(&a, 2, 1, o); fwrite(&b, 2, 1, o); }
            n++;
        }
        fclose(o); printf("프레임 %d개 %dx%d\n", n, W, H); return 0;
    }

    if (strcmp(argv[1], "enc") || argc < 6) die("인수");
    FILE *fo = fopen(argv[3], "rb"); if (!fo) die("overlay 열기");
    int y0 = atoi(argv[4]); if (y0 % 4 || y0 <= 0 || y0 >= H) die("y0 는 4의 배수");
    int skip_thr = argc > 6 ? atoi(argv[6]) : 1;
    long lam0 = argc > 7 ? atol(argv[7]) : 8;
    /* 프레임 상한 = max(32000, 원본 최대 영상 청크). 원본이 32KB 넘는 영상은 avih 권장 버퍼도 그 크기(재생기가 이미 받음)
       — 2026-10-13 OPA·S384_1 등 16개가 32000 고정 상한에서 실패 */
    int CAP = 32000;
    for (int i = 0; i < nck; i++) if (is_video(&ck[i]) && (int)ck[i].size > CAP) CAP = ck[i].size;
    /* ★속도 예산(2026-10-13 시험판 7 오프닝 지지직→멈춤): 재생기는 CD 2배속으로 읽으며 선행 버퍼가 작다(원본 대부분 30~40KB).
       원본의 «누적 바이트 − 읽기 속도×시간» 최대값 D 를 넘지 않게: 프레임 k 까지 늘린 양 E(k) ≤ min_{j≥k}(D − (cum_orig(j) − R·j·dt)).
       (늘린 양은 뒤로 계속 남으므로 앞으로의 최소 여유가 한도) */
    double RATE = 307200.0 * 0.95, dt = 1.0 / 15;
    for (int i = 0; i < nck; i++) if (!memcmp(ck[i].id, "avih", 4)) { uint32_t us; memcpy(&us, file + ck[i].off, 4); if (us) dt = us / 1e6; break; }
    int nvid = 0; for (int i = 0; i < nck; i++) if (is_video(&ck[i])) nvid++;
    double *MS = malloc((nvid + 1) * sizeof(double));
    {
        double cum = 0, D = 0; int v = 0;
        for (int i = 0; i < nck; i++) {
            if (!ck[i].movi || !memcmp(ck[i].id, "LIST", 4)) continue;
            cum += ck[i].size + 8 + (ck[i].size & 1);
            if (is_video(&ck[i])) { MS[v] = cum - RATE * v * dt; if (MS[v] > D) D = MS[v]; v++; }
        }
        MS[nvid] = 1e18;
        for (int k = nvid - 1; k >= 0; k--) { double s = D - MS[k]; MS[k] = s < MS[k + 1] ? s : MS[k + 1]; }
        if (getenv("TMDBG")) fprintf(stderr, "D %.0f · 첫 여유 %.0f\n", D, MS[0]);
    }
    long long EXTRA = 0;
    int bh = H - y0;

    Dec od = { W, H, W / 2, calloc(W / 2 * H, 4), calloc(W / 2, 4) };   /* 원래 */
    Dec nd = { W, H, W / 2, calloc(W / 2 * H, 4), calloc(W / 2, 4) };   /* 새것(검증용 다시 풀기) */
    uint32_t *our = calloc(W / 2 * H, 4);                                   /* 인코더가 아는 새 화면 */
    TGT = calloc(W / 2 * H, 4); PW = W / 2;
    ev = malloc(sizeof(Ev) * (W * bh * 4 + bh + 16));
    uint8_t *ovl = malloc(W * bh * 3);

    /* 새 청크 데이터 모음 */
    uint8_t **nb = calloc(nck, sizeof *nb); uint32_t *nsz = calloc(nck, 4);
    int dirty = getenv("TMFORCE") ? 1 : 0, fno = 0, reenc = 0, nfall = 0; long long sse = 0, npx = 0; long long grow = 0; uint32_t maxsz = 0;
    for (int i = 0; i < nck; i++) {
        if (!is_video(&ck[i])) continue;
        int flag = fgetc(fo); if (flag == EOF) die("overlay 프레임 수 모자람");
        int has = flag == 1;
        if (has && fread(ovl, 1, W * bh * 3, fo) != (size_t)(W * bh * 3)) die("overlay 읽기");
        const uint8_t *src = file + ck[i].off; int sz = ck[i].size;
        if (getenv("TMDBG")) fprintf(stderr, "f%d sz%d has%d dirty%d\n", fno, sz, has, dirty);
        Hdr h; int nop = !sz || parse_hdr(src, sz, &h) || h.compression == 0;
        Trace tr = { y0, 0, 0, 0 };
        if (!nop) { int r = decode(&od, src, sz, &tr); if (r < 0) { fprintf(stderr, "원래 프레임 %d 풀기 오류 %d\n", fno, r); exit(1); } }
        if (nop || (!dirty && !has)) {
            nb[i] = NULL;
            /* ★원래 바이트 프레임 = 재생기 화면(nd) 그대로 따라감. 복원 프레임의 작은 오차가 건너뜀 블록으로 남아 있으므로
               our 를 원본(od)으로 두면 다음 자막 구간 첫 프레임이 «불일치»(2026-10-13 S042_1 프레임 84) */
            if (!nop) { int r = decode(&nd, src, sz, NULL); (void)r; memcpy(our, nd.frame, PW * H * 4); }
            fno++; continue;
        }
        /* 목표 화면: 원래 + 자막 */
        memcpy(TGT, od.frame, PW * H * 4);
        if (has) for (int y = 0; y < bh; y++) for (int x = 0; x < W; x++) {
            const uint8_t *p = ovl + (y * W + x) * 3; int a = p[2]; if (!a) continue;
            uint16_t c = p[0] | p[1] << 8;
            uint32_t *pp = &TGT[(y0 + y) * PW + x / 2]; int sh = (x & 1) * 16;
            uint16_t o = (*pp >> sh) & 0xffff;
            int r = ((o >> 10 & 31) * (255 - a) + (c >> 10 & 31) * a + 127) / 255;
            int g = ((o >> 5 & 31) * (255 - a) + (c >> 5 & 31) * a + 127) / 255;
            int b = ((o & 31) * (255 - a) + (c & 31) * a + 127) / 255;
            uint16_t nv = (o & 0x8000) | r << 10 | g << 5 | b;
            *pp = (*pp & ~(0xffffu << sh)) | (uint32_t)nv << sh;
        }
        /* 위쪽 줄은 원래와 같으므로 our 의 위쪽 = 원래(이전 프레임 위쪽도 원래였음) */
        memcpy(our, od.frame, PW * y0 * 4);
        /* 새 청크: 머리 + 변화 비트 + 원래 색인 [0,consumed) + 새 띠 */
        int rowsz = ((W >> 2) + 7) >> 3;
        int mbbytes = h.keyframe ? 0 : rowsz * (H >> 2);
        static uint32_t *SAVE; if (!SAVE) SAVE = malloc(PW * H * 4);
        memcpy(SAVE, our, PW * H * 4);
        uint8_t *c = NULL; int nsize = 0; uint8_t *mbits = NULL; int fallback = 0;
        for (int att = 0; ; att++) {
        long lam = lam0 << (2 * att); int thr = skip_thr + att;
        if (att) { memcpy(our, SAVE, PW * H * 4); free(c); free(mbits); }
        nout = 0;
        mbits = malloc(mbbytes + 1);
        if (mbbytes) memcpy(mbits, src + h.hs, mbbytes);
        /* 띠 변화 비트: 우리 이전 화면 블록이 목표와 (거의) 같으면 건너뜀 */
        nev = 0;
        for (int y = y0; y < H; y++) {
            ev[nev++] = (Ev){ 4, 0, (int16_t)y };
            for (int x = 0; x < PW; x += 2) {
                int blk = x / 2, skip = 0;
                if (!h.keyframe) {
                    int g = y >> 2;
                    if ((y & 3) == 0) {
                        int maxd = 0;
                        for (int yy = y; yy < y + 4; yy++) for (int xx = x; xx < x + 2; xx++) {
                            uint32_t a = our[yy * PW + xx], b = TGT[yy * PW + xx];
                            for (int k = 0; k < 2; k++) {
                                uint32_t aa = a >> (16 * k) & 0xffff, bb = b >> (16 * k) & 0xffff;

                                int d1 = abs((int)(aa >> 10 & 31) - (int)(bb >> 10 & 31)); if (d1 > maxd) maxd = d1;
                                d1 = abs((int)(aa >> 5 & 31) - (int)(bb >> 5 & 31)); if (d1 > maxd) maxd = d1;
                                d1 = abs((int)(aa & 31) - (int)(bb & 31)); if (d1 > maxd) maxd = d1;
                            }
                        }
                        uint8_t *mb = &mbits[g * rowsz + blk / 8];
                        if (maxd <= thr) *mb |= 1 << (blk & 7); else *mb &= ~(1 << (blk & 7));
                    }
                    skip = (mbits[g * rowsz + blk / 8] >> (blk & 7)) & 1;
                }
                if (skip) ev[nev++] = (Ev){ 3, (int16_t)x, (int16_t)y };
                else {
                    int t = y & 3;
                    if (t == 0 || t == 2) {
                        int c1, c2; cslots(h.compression, t, &c1, &c2);
                        if (c1) ev[nev++] = (Ev){ 0, 0, 0 };
                        ev[nev++] = (Ev){ 1, 0, 0 }; ev[nev++] = (Ev){ 2, (int16_t)x, (int16_t)y };
                        if (c2) ev[nev++] = (Ev){ 0, 0, 0 };
                        ev[nev++] = (Ev){ 1, 0, 0 }; ev[nev++] = (Ev){ 2, (int16_t)(x + 1), (int16_t)y };
                    } else {
                        ev[nev++] = (Ev){ 1, 0, 0 }; ev[nev++] = (Ev){ 2, (int16_t)x, (int16_t)y };
                        ev[nev++] = (Ev){ 1, 0, 0 }; ev[nev++] = (Ev){ 2, (int16_t)(x + 1), (int16_t)y };
                    }
                }
            }
        }
        /* 원래 색인 앞부분 */
        const uint8_t *is0 = src + h.hs + mbbytes;
        if (!tr.got) die("띠 시작 상태 없음");
        for (int k = 0; k < tr.consumed; k++) emit(is0[k]);
        /* 띠 위 마지막 줄 상태: our 의 y0-1 줄 = vert */
        static uint32_t *VB; if (!VB) VB = malloc(PW * 4);
        LAMBDA = lam;
        memcpy(VB, our + (y0 - 1) * PW, PW * 4);
        VERT = VB; FRM = our;
        St st = { 0, 0, tr.index };
        INFEAS = 0;
        encode_events(st);
        /* 마지막 벡터가 끝났으면 디코더가 한 바이트 더 읽는다 — 안전하게 하나 붙임 */
        emit(1);
        /* 청크 조립 */
        nsize = h.hs + mbbytes + nout;
        c = malloc(nsize + 1);
        memcpy(c, src, h.hs); if (mbbytes) memcpy(c + h.hs, mbits, mbbytes); memcpy(c + h.hs + mbbytes, OUT, nout);
        long capf = CAP; { double b = sz + MS[fno] - EXTRA - 1024;   /* 1KB 여유(청크 패딩 등) */ if (b < capf) capf = (long)b; }
        if (nsize <= capf && !INFEAS) break;
        if (att >= 8 || capf <= sz) { fallback = 1; break; }
        }
        if (fallback) {
            /* 상한을 못 맞춤(원래부터 큰 장면 전환 프레임) → 이 한 장은 원래 바이트(자막 빠짐), 화면은 재생기 따라감,
               다음 프레임부터 다시 띠 부호화(dirty). 2026-10-13 OPA·S090_1 등 11개 */
            free(c); free(mbits); nb[i] = NULL;
            decode(&nd, src, sz, NULL); memcpy(our, nd.frame, PW * H * 4);
            nfall++; dirty = 1; fno++; continue;
        }
        nb[i] = c; nsz[i] = nsize; free(mbits);
        if ((uint32_t)nsize > maxsz) maxsz = nsize;
        grow += nsize - sz; EXTRA += nsize - sz;
        /* 검증: 새 청크를 따로 풀어 our 와 같은지 */
        int r = decode(&nd, c, nsize, NULL);
        if (r < 0) { fprintf(stderr, "새 프레임 %d 풀기 오류 %d\n", fno, r); exit(1); }
        if (memcmp(nd.frame, our, PW * H * 4)) {
            for (int k = 0; k < PW * H; k++) if (nd.frame[k] != our[k]) {
                fprintf(stderr, "프레임 %d 불일치 @%d,%d (풀림 %08x 인코더 %08x 목표 %08x · 키 %d 압축 %d ds %d vt %d · 띠 시작 색인 %d)\n", fno, (k % PW) * 2, k / PW,
                        nd.frame[k], our[k], TGT[k], h.keyframe, h.compression, h.deltaset, h.vectable, tr.index);
                break; }
            exit(1);
        }
        for (int y = y0; y < H; y++) for (int x = 0; x < PW; x++) { sse += pix_err(our[y * PW + x], TGT[y * PW + x]); npx += 2; }
        reenc++;
        /* 자막이 있으면 계속 띠를 새로 부호화. 자막이 없는 프레임 = «복원»(목표 = 원래 띠) 한 장 → 다음부터 원래 바이트.
           원래 바이트의 건너뜀 블록은 이 복원본을 베끼므로 오차(평균 1~2단계)가 정지 화면에 남을 수 있다 */
        dirty = has || getenv("TMFORCE");
        fno++;
    }
    if (fgetc(fo) != EOF) fprintf(stderr, "경고: overlay 가 프레임보다 많음\n");
    /* AVI 다시 쓰기 */
    FILE *w = fopen(argv[5], "wb"); if (!w) die("출력");
    /* 원래 바이트를 순서대로 복사하되 바뀐 영상 청크는 새 크기로, 목록 크기·idx1 은 나중에 고침 */
    uint8_t *ob = malloc(flen + grow + 1024 * 1024); long op = 0;
    long *newpos = calloc(nck, sizeof(long));
    /* 재귀 없이: 파일을 처음부터 다시 걷기 */
    long stack_off[16], stack_new[16]; int sp = 0;
    long ip = 0;
    /* 간단히: 청크 목록(파일 순서) 을 따라 쓰기 */
    for (int i = 0; i < nck; i++) {
        long hdr = ck[i].off - 8;
        /* 앞 목록들 끝 처리 */
        while (sp && hdr >= stack_off[sp - 1]) {   /* stack_off = 원래 목록 끝 */
            sp--; uint32_t nsz2 = (uint32_t)(op - stack_new[sp] - 8); memcpy(ob + stack_new[sp] + 4, &nsz2, 4);
        }
        /* 청크 사이 빈틈(패딩) 복사 */
        if (hdr > ip) { memcpy(ob + op, file + ip, hdr - ip); op += hdr - ip; }
        newpos[i] = op;
        if (!strcmp(ck[i].id, "LIST") || !strcmp(ck[i].id, "RIFF")) {
            memcpy(ob + op, file + hdr, 12); op += 12; ip = hdr + 12;
            stack_off[sp] = ck[i].off + ck[i].size; stack_new[sp] = newpos[i]; sp++;
            continue;
        }
        if (nb[i]) {
            memcpy(ob + op, file + hdr, 4); memcpy(ob + op + 4, &nsz[i], 4); op += 8;
            memcpy(ob + op, nb[i], nsz[i]); op += nsz[i];
            if (nsz[i] & 1) ob[op++] = 0;
            ip = ck[i].off + ck[i].size + (ck[i].size & 1);
        } else {
            long len = 8 + ck[i].size + (ck[i].size & 1);
            memcpy(ob + op, file + hdr, len); op += len; ip = hdr + len;
        }
    }
    if (ip < flen) { memcpy(ob + op, file + ip, flen - ip); op += flen - ip; }
    while (sp) { sp--; uint32_t nsz2 = (uint32_t)(op - stack_new[sp] - 8); memcpy(ob + stack_new[sp] + 4, &nsz2, 4); }
    /* idx1: 오프셋 = movi «movi» 글자 위치 기준(원래 규약 확인: 첫 항목 4) */
    long movi_new = -1; for (int i = 0; i < nck; i++) if (ck[i].off - 8 == movi_list_off) movi_new = newpos[i];
    /* ★VIRUS 영상의 색인은 파일 «앞»의 iddx(형식은 idx1 과 같음) — 재생기가 이걸로 읽는다.
       2026-10-13 시험판 7·8: iddx 를 안 고쳐 옛 오프셋·크기로 읽혀 오프닝 지지직→멈춤 */
    for (int i = 0; i < nck; i++) if (!strcmp(ck[i].id, "idx1") || !strcmp(ck[i].id, "iddx")) {
        uint8_t *p = ob + newpos[i] + 8; int n = ck[i].size / 16;
        /* 원래 각 항목 → 같은 청크를 찾아 새 위치·크기 */
        int vi = 0;
        for (int k = 0; k < n; k++) {
            uint32_t off, sz2; memcpy(&off, p + k * 16 + 8, 4);
            long orig_hdr = movi_list_off + 8 + off;     /* movi 글자 = LIST+8 */
            /* 이 위치의 청크 찾기 */
            int found = -1;
            for (int j = vi; j < nck; j++) if (ck[j].off - 8 == orig_hdr) { found = j; break; }
            if (found < 0) for (int j = 0; j < nck; j++) if (ck[j].off - 8 == orig_hdr) { found = j; break; }
            if (found < 0) die("idx1 항목의 청크를 못 찾음");
            vi = found;
            uint32_t noff = (uint32_t)(newpos[found] - (movi_new + 8));
            sz2 = nb[found] ? nsz[found] : ck[found].size;
            memcpy(p + k * 16 + 8, &noff, 4); memcpy(p + k * 16 + 12, &sz2, 4);
        }
    }
    /* 검산: 색인 항목마다 «movi+8+오프셋» 자리 청크 이름·크기가 항목과 같은지 */
    for (int i = 0; i < nck; i++) if (!strcmp(ck[i].id, "idx1") || !strcmp(ck[i].id, "iddx")) {
        const uint8_t *p = ob + newpos[i] + 8; int n = ck[i].size / 16;
        for (int k = 0; k < n; k++) {
            uint32_t off, s2, s3; memcpy(&off, p + k * 16 + 8, 4); memcpy(&s2, p + k * 16 + 12, 4);
            long h = movi_new + 8 + off;
            memcpy(&s3, ob + h + 4, 4);
            if (h + 8 > op || memcmp(ob + h, p + k * 16, 4) || s3 != s2) { fprintf(stderr, "%s 항목 %d 불일치\n", ck[i].id, k); exit(1); }
        }
    }
    fwrite(ob, 1, op, w); fclose(w);
    printf("프레임 %d · 띠 다시 부호화 %d · 크기 %+lld B (%ld → %ld) · 가장 큰 영상 청크 %u · 띠 오차 평균 %.2f\n",
           fno, reenc, grow, flen, op, maxsz, npx ? (double)sse / npx : 0.0);
    if (nfall) printf("자막 빠진 프레임(상한 초과 → 원래 바이트) %d\n", nfall);
    return 0;
}

# -*- coding: utf-8 -*-
r"""VIRUS 3장 디스크 빌드: 원본 트랙 1 사본에 바꾼 파일을 제자리로 쓰고 MODE1 EDC/ECC 재계산.
  바꾼 파일: work/build/<이름>  → 그 파일이 있는 모든 디스크에(SKANS·VIRUS.BIN 처럼 세 장 공통인 것)
             work/build/d<N>/<이름> → 그 디스크에만(AVI 처럼 장마다 다른 것) — 공통보다 우선
  크기: 원래 섹터 안이면 제자리(크기가 바뀌면 디렉터리 레코드 크기 갱신), 넘치면 트랙 1 끝에 새 섹터로 옮기고
        디렉터리 레코드(LBA·크기)·PVD 볼륨 크기 갱신(MODE1 머리 MSF·EDC/ECC 새로). 트랙 2 는 따로 된 파일이라 그대로.
  출력: dist/build/Virus (Japan) (Disc N)/ (트랙 1 패치본 + 원본 트랙 2·cue 복사), 되읽어 검산.
  python tools/discbuild.py [--install] [--disc 1,2,3] [--text-only]
    --install = F:\hospi\roms\ss roms\Virus (Japan)\…(Disc N) 트랙 1 덮어쓰기(설치본)
"""
import hashlib, os, shutil, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import disc
from cdrom_ecc import recalc_sector

BUILD = os.path.join(ROOT, 'work', 'build')
OUT = os.path.join(ROOT, 'dist', 'build')
F_DIR = r'F:\hospi\roms\ss roms\Virus (Japan)'


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 22), b''):
            h.update(c)
    return h.hexdigest()


def changes(n, fs):
    """디스크 n 에 쓸 {경로: 바이트}"""
    out = {}
    for f in sorted(os.listdir(BUILD)):
        p = os.path.join(BUILD, f)
        if os.path.isfile(p) and f in fs:
            out[f] = open(p, 'rb').read()
    dd = os.path.join(BUILD, 'd%d' % n)
    if os.path.isdir(dd) and '--text-only' not in sys.argv:     # --text-only = 디스크별 파일(AVI) 빼고
        only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None   # 디스크별 파일 중 이것만
        for f in sorted(os.listdir(dd)):
            if only is not None and f not in only:
                continue
            if f not in fs:
                sys.exit('⛔ 디스크 %d 에 %s 없음' % (n, f))
            out[f] = open(os.path.join(dd, f), 'rb').read()
    return out


def dir_records(fh, lba, size, base=''):
    """ISO 디렉터리 → {경로: (레코드 섹터, 섹터 안 자리)}"""
    out = {}
    for si in range((size + 2047) // 2048):
        fh.seek((lba + si) * 2352 + 16); d = fh.read(2048); p = 0
        while p < 2048:
            L = d[p]
            if L == 0:
                break
            el, sz, fl = struct.unpack_from('<I', d, p + 2)[0], struct.unpack_from('<I', d, p + 10)[0], d[p + 25]
            nm = d[p + 33:p + 33 + d[p + 32]]
            if nm not in (bytes([0]), bytes([1])):
                name = nm.decode('ascii', 'replace').split(';')[0]
                if fl & 2:
                    out.update(dir_records(fh, el, sz, base + name + '/'))
                else:
                    out[base + name] = (lba + si, p)
            p += L
    return out


def put_sector(fh, lba, data2048, template):
    sec = bytearray(template)
    m = lba + 150; mm, ss, ff = m // 4500, (m // 75) % 60, m % 75
    bcd = lambda x: (x // 10) << 4 | (x % 10)
    sec[12:16] = bytes([bcd(mm), bcd(ss), bcd(ff), 1])
    sec[16:2064] = data2048 + bytes(2048 - len(data2048))
    fh.seek(lba * 2352); fh.write(recalc_sector(bytes(sec)))


def patch_record(fh, rec, lba, size):
    rs, ro = rec
    fh.seek(rs * 2352); sec = bytearray(fh.read(2352))
    struct.pack_into('<I', sec, 16 + ro + 2, lba); struct.pack_into('>I', sec, 16 + ro + 6, lba)
    struct.pack_into('<I', sec, 16 + ro + 10, size); struct.pack_into('>I', sec, 16 + ro + 14, size)
    fh.seek(rs * 2352); fh.write(recalc_sector(bytes(sec)))


def build(n, install):
    name = 'Virus (Japan) (Disc %d)' % n
    src_dir = os.path.join(disc.ROMDIR, name)
    rom = os.path.join(src_dir, name + ' (Track 1).bin')
    fs = {p: (l, s) for p, l, s in disc.Disc(rom).walk()}
    ch = changes(n, fs)
    od = os.path.join(OUT, name); os.makedirs(od, exist_ok=True)
    for x in os.listdir(src_dir):
        if 'Track 1' not in x:
            shutil.copyfile(os.path.join(src_dir, x), os.path.join(od, x))
    t1 = os.path.join(od, name + ' (Track 1).bin')
    shutil.copyfile(rom, t1)
    newpos = {}
    with open(t1, 'r+b') as fh:
        fh.seek(16 * 2352); pvd = bytearray(fh.read(2352))
        rlba, rsz = struct.unpack_from('<I', pvd, 16 + 156 + 2)[0], struct.unpack_from('<I', pvd, 16 + 156 + 10)[0]
        recs = dir_records(fh, rlba, rsz)
        fh.seek(0, 2); end = fh.tell() // 2352
        fh.seek(16 * 2352); template = fh.read(2352)
        # 넘치는 파일: 옮겨 가는 파일들의 원래 자리를 빈 곳으로 모아 큰 것부터 best-fit, 안 맞으면 트랙 끝
        #   (2026-10-13 자막 AVI 가 전부 트랙 끝에 붙으면 디스크 3 이 80분 한도 360,000섹터를 넘음)
        sec_of = lambda b: (b + 2047) // 2048
        movers = [f for f, data in ch.items() if len(data) > sec_of(fs[f][1]) * 2048]
        holes = sorted([fs[f][0], fs[f][0] + sec_of(fs[f][1])] for f in movers)
        place = {}
        for f in sorted(movers, key=lambda f: -len(ch[f])):
            need = sec_of(len(ch[f]))
            fit = [h for h in holes if h[1] - h[0] >= need]
            if fit:
                h = min(fit, key=lambda h: h[1] - h[0]); place[f] = (h[0], '옛 자리 재사용'); h[0] += need
            else:
                place[f] = (end, '트랙 끝으로 옮김'); end += need
        for f, data in ch.items():
            lba, size = fs[f]
            alloc = (size + 2047) // 2048 * 2048
            if f not in place:
                wlba = lba; how = '제자리'
                pad = data + bytes((size if len(data) <= size else len(data)) - len(data))
            else:
                wlba, how = place[f]
                pad = data
            nsec = (len(pad) + 2047) // 2048; changed = 0
            for i in range(nsec):
                chunk = pad[i * 2048:(i + 1) * 2048]
                if wlba == lba:
                    fh.seek((lba + i) * 2352); sec = bytearray(fh.read(2352))
                    if sec[16:16 + len(chunk)] == chunk:
                        continue
                    sec[16:16 + len(chunk)] = chunk
                    fh.seek((lba + i) * 2352); fh.write(recalc_sector(bytes(sec)))
                else:
                    put_sector(fh, wlba + i, chunk, template)
                changed += 1
            if wlba != lba or len(data) != size:
                patch_record(fh, recs[f], wlba, len(data))
            newpos[f] = (wlba, len(data))
            print('  디스크 %d %-14s %s LBA %7d · %d B · 섹터 %d 바뀜' % (n, f, how, wlba, len(data), changed))
        # 볼륨 크기
        vol = struct.unpack_from('<I', pvd, 16 + 80)[0]
        if end > vol:
            struct.pack_into('<I', pvd, 16 + 80, end); struct.pack_into('>I', pvd, 16 + 84, end)
            fh.seek(16 * 2352); fh.write(recalc_sector(bytes(pvd)))
    d2 = disc.Disc(t1); fs2 = {p: (l, s) for p, l, s in d2.walk()}
    for f, data in ch.items():
        l, s = fs2[f]
        assert (l, s) == newpos[f] and d2.read(l, s) == data, f
    m = md5(t1)
    print('디스크 %d 트랙 1 md5 %s (원본 %s) · 섹터 %d' % (n, m, md5(rom), os.path.getsize(t1) // 2352))
    if install:
        dst = os.path.join(F_DIR, name, name + ' (Track 1).bin')
        shutil.copyfile(t1, dst)
        print('  F: 설치', '✅' if md5(dst) == m else '⛔ md5 불일치', dst)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    discs = [1, 2, 3]
    if '--disc' in sys.argv:
        discs = [int(x) for x in sys.argv[sys.argv.index('--disc') + 1].split(',')]
    for n in discs:
        build(n, '--install' in sys.argv)


if __name__ == '__main__':
    main()

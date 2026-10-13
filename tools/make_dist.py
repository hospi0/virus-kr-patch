# -*- coding: utf-8 -*-
r"""배포 묶음 — dist/<NAME>/ : 디스크별 트랙 1 xdelta 3개 + xdelta.exe + readme.txt(CP949) + 한글패치_적용.bat(CP949)
  (코튼2 tools/make_dist.py 를 3장짜리로)
  바뀌는 트랙: 디스크마다 트랙 1 만(나머지 트랙·cue 는 원본 그대로 — discbuild 가 복사만 함)
  검증: 원본 트랙 1 → xdelta 적용 → md5 = 빌드(dist/build) 트랙 1 md5.
  python tools/make_dist.py   (먼저 python tools/discbuild.py [--install])
  readme 본문 = tools/dist_readme.txt
"""
import hashlib, os, shutil, subprocess, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

VER = 'v0.8'
XDELTA = r'C:\claude\utils\xdelta.exe'
SRC = r'C:\claude\roms\ss\Virus (Japan)'
OUT = os.path.join(ROOT, 'dist', 'build')
NAME = 'Virus_KR_' + VER
TITLE = 'VIRUS (세가 새턴 일본판, 3장) 한글 패치 ' + VER


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest().upper()


README = open(os.path.join(HERE, 'dist_readme.txt'), encoding='utf-8').read()

BAT_HEAD = '@echo off\nchcp 949 >nul\nset "XD=%~dp0xdelta.exe"\nset OK=0\n'
BAT_ONE = r"""if exist "%~dp0{bin}" (
  "%XD%" -d -f -s "%~dp0{bin}" "%~dp0{patch}" "%~dp0{kbin}"
  if errorlevel 1 (
    echo   [오류] 디스크 {n} 패치 실패 - 원본이 다를 수 있습니다 - readme 의 원본md5 확인.
  ) else (
    echo   완료: "{kbin}"
    set OK=1
  )
)
"""
BAT_TAIL = r"""if "%OK%"=="0" echo   [오류] 원본 트랙 1 파일을 이 폴더에 넣어 주세요 - readme 참고.
pause
"""


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    d = os.path.join(ROOT, 'dist', NAME)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    bat = BAT_HEAD; md = {}
    for n in (1, 2, 3):
        rom = 'Virus (Japan) (Disc %d)' % n
        b = '%s (Track 1).bin' % rom
        src, out = os.path.join(SRC, rom, b), os.path.join(OUT, rom, b)
        patch = '%s_Disc%d_Track1.xdelta' % (NAME, n); pp = os.path.join(d, patch)
        subprocess.run([XDELTA, '-e', '-9', '-B', '1073741824', '-f', '-s', src, out, pp], check=True)
        chk = os.path.join(d, '_check.bin')
        subprocess.run([XDELTA, '-d', '-f', '-s', src, pp, chk], check=True)
        o, want, got = md5(src), md5(out), md5(chk)
        os.remove(chk)
        assert got == want, ('패치 적용 결과가 빌드와 다름', n, got, want)
        md['o%d' % n], md['d%d' % n] = o, want
        print('디스크 %d 트랙 1 원본md5 %s → 패치md5 %s · %s %d B' % (n, o, want, patch, os.path.getsize(pp)), flush=True)
        bat += BAT_ONE.format(n=n, bin=b, patch=patch, kbin='%s (Track 1) [KR].bin' % rom)
    bat += BAT_TAIL
    shutil.copy2(XDELTA, os.path.join(d, 'xdelta.exe'))
    readme = README.format(title=TITLE, line='=' * 60, name=NAME, **md)
    open(os.path.join(d, 'readme.txt'), 'wb').write(readme.replace('\n', '\r\n').encode('cp949'))
    open(os.path.join(d, '한글패치_적용.bat'), 'wb').write(bat.replace('\n', '\r\n').encode('cp949'))
    z = os.path.join(ROOT, 'dist', NAME + '.zip')
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(d)):
            zf.write(os.path.join(d, f), NAME + '/' + f)
    print('✅', d)
    for f in sorted(os.listdir(d)):
        print('  %-56s %12d' % (f, os.path.getsize(os.path.join(d, f))))
    print('  zip %s %d B · md5 %s' % (os.path.basename(z), os.path.getsize(z), md5(z)))


if __name__ == '__main__':
    main()

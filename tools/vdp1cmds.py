import sys; sys.path.insert(0,'tools')
from mdfnstate import sections, swap16
import struct
for fn in sys.argv[1:]:
    s=sections(open(fn,'rb').read()); v=swap16(s['VDP1']['VRAM'])
    print('==',fn)
    a=0; n=0
    while a<0x80000 and n<2000:
        c=struct.unpack_from('>16H',v,a); ctrl=c[0]
        if ctrl&0x8000: break
        jp=(ctrl>>12)&7; cm=ctrl&15
        if not (ctrl&0x4000) and cm in (0,1,2):
            w=((c[5]>>8)&0x3f)*8; h=c[5]&0xff
            x=struct.unpack('>h',struct.pack('>H',c[6]))[0]; y=struct.unpack('>h',struct.pack('>H',c[7]))[0]
            print('%05X cm%d mode%04X col%04X src%05X %dx%d @%d,%d'%(a,cm,c[2],c[3],c[4]*8,w,h,x,y))
        nxt=a+0x20
        if jp==1: nxt=c[1]*8
        elif jp==2: nxt=c[1]*8  # call (approx)
        a=nxt; n+=1

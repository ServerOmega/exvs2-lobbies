# usage: riprefs.py 0xTARGET [...] -- brute-force rip-relative disp32 refs in .text (insn end = disp_end + 0..4)
import sys, numpy as np, relib
for name,va,vs,raw,rs in [s[:5] for s in relib.secs()]:
    if name.startswith('.text'): break
buf=np.frombuffer(relib.data()[raw:raw+rs],dtype=np.uint8)
n=len(buf)-4
d=(buf[:n].astype(np.int64)|(buf[1:n+1].astype(np.int64)<<8)|(buf[2:n+2].astype(np.int64)<<16)|(buf[3:n+3].astype(np.int64)<<24))
d=np.where(d>=2**31,d-2**32,d)
pos=np.arange(n,dtype=np.int64)+va  # va of disp start
for t in [int(x,16) for x in sys.argv[1:]]:
    out=set()
    for extra in range(0,5):
        hit=np.nonzero(pos+4+extra+d==t)[0]
        for h in hit:
            for back in range(1,8):
                a=int(pos[h])-back
                try:
                    ins=relib.dis(a,a+16)
                except Exception: continue
                if ins and ins[0].address==a and ins[0].address+ins[0].size==int(pos[h])+4+extra and '0x%x'%t in relib.fmt(ins[0]):
                    f=relib.func_of(a); out.add((a,f[0] if f else 0,relib.fmt(ins[0]))); break
    for a,f,s in sorted(out): print(hex(t),'fn',hex(f),s)

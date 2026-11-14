import sys, relib
# usage: strs.py START END  -> per function: string refs + lea of code pointers (states)
a=int(sys.argv[1],16); b=int(sys.argv[2],16)
for f0,f1 in relib.funcs():
    if f0<a or f0>=b: continue
    out=[]
    for i in relib.dis(f0,f1):
        r=relib.ripref(i)
        if r is None: continue
        if relib.isstr(r): out.append('"%s"'%relib.cstr(r)[:70])
        elif i.mnemonic=='lea' and relib.func_of(r) and relib.func_of(r)[0]==r: out.append('&%x'%r)
    print(hex(f0),hex(f1-f0),' | '.join(out)[:600])

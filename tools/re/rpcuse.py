import sys, relib
for n in sys.argv[1:]:
    for vt,col,off in relib.rtti(n):
        refs=relib.xrefs(vt)
        fs=sorted(set(hex((relib.func_of(s) or (s,))[0]) for s,k in refs))
        print(n.split('@U')[1].split('@')[0], hex(vt), fs)

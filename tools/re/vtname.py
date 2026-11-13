"""usage: vtname.py 0xFUNC ... -> which RTTI class vtable(s) reference the function (and enclosing function if not a vtable entry)."""
import sys, struct, relib
IB = relib.IB
def colname(vt):
    col = relib.q(vt - 8)
    try:
        td = IB + relib.d(col + 12)
        return relib.cstr(td + 16)
    except Exception: return None
for a in sys.argv[1:]:
    f = int(a, 16); fn = relib.func_of(f); f0 = fn[0] if fn else f
    out = []
    for src, kind in relib.xrefs(f0):
        if kind == 'ptr':
            # walk back to vtable start (entry whose preceding qword is a COL pointer in .rdata)
            p = src
            for _ in range(200):
                n = colname(p)
                if n and n.startswith('.?AV'): out.append((n, (src - p) // 8)); break
                p -= 8
        else:
            out.append(('code-ref from %#x' % src, kind))
    print(hex(f0), out[:6])

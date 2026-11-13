"""RE helpers for vsac29_Release.exe (capstone + pefile). Rebuilt 2026-11-13."""
import os, struct, bisect, pickle, functools
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, '..', '..', 'binaries', 'vsac29_Release.exe')
IB = 0x140000000
_D = None; _SECS = None; _F = None; _X = None
md = Cs(CS_ARCH_X86, CS_MODE_64)
def data():
    global _D
    if _D is None: _D = open(EXE, 'rb').read()
    return _D
def secs():
    global _SECS
    if _SECS is None:
        d = data(); pe = struct.unpack_from('<I', d, 0x3c)[0]
        n = struct.unpack_from('<H', d, pe + 6)[0]; opt = struct.unpack_from('<H', d, pe + 20)[0]
        o = pe + 24 + opt; _SECS = []
        for i in range(n):
            name = d[o:o+8].rstrip(b'\0').decode(); vs, va, rs, ro = struct.unpack_from('<IIII', d, o + 8)
            _SECS.append((name, IB + va, vs, ro, rs)); o += 40
    return _SECS
def va2off(va):
    for n, v, vs, ro, rs in secs():
        if v <= va < v + max(vs, rs): return va - v + ro
    raise ValueError(hex(va))
def off2va(off):
    for n, v, vs, ro, rs in secs():
        if ro <= off < ro + rs: return off - ro + v
    raise ValueError(hex(off))
def read(va, n): o = va2off(va); return data()[o:o+n]
def q(va): return struct.unpack('<Q', read(va, 8))[0]
def d(va): return struct.unpack('<I', read(va, 4))[0]
def cstr(va, maxn=512):
    b = read(va, maxn); return b.split(b'\0')[0].decode('latin1')
def text(): return [s for s in secs() if s[0] == '.text'][0]
def funcs():
    global _F
    if _F is None:
        p = [s for s in secs() if s[0] == '.pdata'][0]
        raw = data()[p[3]:p[3]+p[2]]; fs = set()
        for i in range(0, len(raw) - 11, 12):
            b, e, u = struct.unpack_from('<III', raw, i)
            if b and e > b: fs.add((IB + b, IB + e))
        _F = sorted(fs)
    return _F
_starts = None
def func_of(va):
    global _starts
    F = funcs()
    if _starts is None: _starts = [f[0] for f in F]
    i = bisect.bisect_right(_starts, va) - 1
    if i >= 0 and F[i][0] <= va < F[i][1]: return F[i]
    return None
def dis(start, end=None, n=None):
    if end is None and n is None:
        f = func_of(start); end = f[1] if f else start + 0x200
    code = read(start, (end - start) if end else n * 15)
    out = []
    for i in md.disasm(code, start):
        out.append(i)
        if n and len(out) >= n: break
    return out
def ripref(i):
    s = i.op_str
    if 'rip + ' in s:
        k = s.index('rip + ') + 6; v = s[k:].split(']')[0]
        return i.address + i.size + int(v, 16)
    if 'rip - ' in s:
        k = s.index('rip - ') + 6; v = s[k:].split(']')[0]
        return i.address + i.size - int(v, 16)
    return None
def isstr(r):
    try:
        b = read(r, 64)
    except Exception: return False
    s = b.split(b'\0')[0]
    return len(s) >= 4 and all(32 <= c < 127 for c in s)
def fmt(i):
    s = '  %x: %s %s' % (i.address, i.mnemonic, i.op_str)
    r = ripref(i)
    if r:
        if isstr(r): s += '   ; "%s"' % cstr(r)[:60]
        s += '   ; ->%#x' % r
    return s
def pr(start, end=None, n=None):
    for i in dis(start, end, n): print(fmt(i))
def xdb():
    global _X
    if _X is None: _X = pickle.load(open(os.path.join(HERE, 'xrefs.pkl'), 'rb'))
    return _X
def xrefs(t): return xdb().get(t, [])
def find_bytes(b):
    dd = data(); out = []; i = dd.find(b)
    while i != -1:
        try: out.append(off2va(i))
        except ValueError: pass
        i = dd.find(b, i + 1)
    return out
def find_str(s): return find_bytes(s.encode() + b'\0')
def rtti(name):
    res = []; dd = data(); ro = [x for x in secs() if x[0] == '.rdata'][0]
    for nva in find_bytes(name.encode() + b'\0'):
        td = nva - 0x10; pat = struct.pack('<I', td - IB)
        i = dd.find(pat, ro[3], ro[3] + ro[4])
        while i != -1:
            sig, off = struct.unpack('<II', dd[i-0xc:i-0x4])
            if sig == 1:
                colva = off2va(i - 0xc); p = struct.pack('<Q', colva)
                j = dd.find(p, ro[3], ro[3] + ro[4])
                while j != -1:
                    res.append((off2va(j) + 8, colva, off)); j = dd.find(p, j + 1, ro[3] + ro[4])
            i = dd.find(pat, i + 1, ro[3] + ro[4])
    return res
def vtable(vt, maxn=80):
    t = text(); out = []
    for k in range(maxn):
        p = q(vt + 8 * k)
        if not (t[1] <= p < t[1] + t[2]): break
        if k > 0 and xrefs(vt + 8 * k): break
        out.append(p)
    return out
def callers(fva):
    return sorted(set(((func_of(s) or (s,))[0], s, k) for s, k in xrefs(fva)))

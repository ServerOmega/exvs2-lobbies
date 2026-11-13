"""Build xrefs.pkl: target -> [(src, kind)] for rel32 call/jmp/jcc and rip-relative operands, plus abs64 pointers in data."""
import pickle, struct, relib
from multiprocessing import Pool
def work(ch):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    md = Cs(CS_ARCH_X86, CS_MODE_64); out = []
    for b, e in ch:
        for i in md.disasm(relib.read(b, e - b), b):
            m = i.mnemonic
            if (m == 'call' or m.startswith('j')) and i.op_str.startswith('0x'):
                out.append((int(i.op_str, 16), i.address, m))
            else:
                r = relib.ripref(i)
                if r: out.append((r, i.address, m))
    return out
if __name__ == '__main__':
    fs = [(f[0], f[1]) for f in relib.funcs()]
    db = {}
    with Pool(8) as p:
        for o in p.imap_unordered(work, [fs[i::64] for i in range(64)]):
            for t, s, k in o: db.setdefault(t, []).append((s, k))
    # abs pointers in .rdata/.data to .text
    t = relib.text(); dd = relib.data()
    for n, v, vs, ro, rs in relib.secs():
        if n in ('.rdata', '.data'):
            for off in range(ro, ro + rs - 7, 8):
                p = struct.unpack_from('<Q', dd, off)[0]
                if t[1] <= p < t[1] + t[2]: db.setdefault(p, []).append((v + off - ro, 'ptr'))
    pickle.dump(db, open('xrefs.pkl', 'wb')); print(len(db))

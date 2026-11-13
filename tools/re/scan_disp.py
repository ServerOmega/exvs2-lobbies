import sys, relib
from multiprocessing import Pool
disps = [int(x, 16) for x in sys.argv[1].split(',')]
lo = int(sys.argv[2], 16); hi = int(sys.argv[3], 16)
def work(ch):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86 import X86_OP_MEM
    md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True; out = []
    for b, e in ch:
        for i in md.disasm(relib.read(b, e - b), b):
            for op in i.operands:
                if op.type == X86_OP_MEM and op.mem.disp in disps and op.mem.base != 0:
                    out.append((b, i.address, i.mnemonic + ' ' + i.op_str))
    return out
if __name__ == '__main__':
    fs = [f for f in relib.funcs() if lo <= f[0] < hi]
    with Pool(8) as p:
        for o in p.imap(work, [fs[i::32] for i in range(32)]):
            for b, a, s in o: print(hex(b), hex(a), s)

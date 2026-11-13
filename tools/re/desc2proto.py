"""Render a serialized FileDescriptorProto (extracted from the exe) as .proto text. usage: desc2proto.py in.desc > out.proto"""
import sys
from google.protobuf import descriptor_pb2 as p
F = p.FieldDescriptorProto
TN = {v: k[5:].lower() for k, v in F.Type.items()}
LB = {1: 'optional', 2: 'required', 3: 'repeated'}
def enum(e, ind):
    out = [ind + 'enum %s {' % e.name]
    out += [ind + '  %s = %d;' % (v.name, v.number) for v in e.value]
    return out + [ind + '}']
def msg(m, ind):
    out = [ind + 'message %s {' % m.name]
    for f in m.field:
        t = f.type_name.lstrip('.') if f.type_name else TN[f.type]
        opt = ' [default = %s]' % f.default_value if f.HasField('default_value') else ''
        out.append(ind + '  %s %s %s = %d%s;' % (LB[f.label], t, f.name, f.number, opt))
    for e in m.enum_type: out += enum(e, ind + '  ')
    for n in m.nested_type: out += msg(n, ind + '  ')
    return out + [ind + '}']
f = p.FileDescriptorProto(); f.ParseFromString(open(sys.argv[1], 'rb').read())
out = ['syntax = "%s";' % (f.syntax or 'proto2'), '', 'package %s;' % f.package, '']
for e in f.enum_type: out += enum(e, '') + ['']
for m in f.message_type: out += msg(m, '') + ['']
print('\n'.join(out))

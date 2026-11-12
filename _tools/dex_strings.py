"""Dump string pool from every classes*.dex in an APK to a UTF-8 text file."""
import sys, zipfile, struct, io

def uleb128(buf, off):
    result = 0; shift = 0
    while True:
        b = buf[off]; off += 1
        result |= (b & 0x7f) << shift
        if not b & 0x80: return result, off
        shift += 7

def dex_strings(data):
    if data[:4] != b'dex\n': return []
    string_ids_size, string_ids_off = struct.unpack_from('<II', data, 56)
    out = []
    for i in range(string_ids_size):
        off = struct.unpack_from('<I', data, string_ids_off + i*4)[0]
        n, p = uleb128(data, off)
        end = data.index(b'\x00', p)
        try:
            out.append(data[p:end].decode('utf-8', 'replace'))
        except Exception:
            pass
    return out

apk, dst = sys.argv[1], sys.argv[2]
lines = []
with zipfile.ZipFile(apk) as z:
    for name in z.namelist():
        if name.startswith('classes') and name.endswith('.dex'):
            lines.extend(dex_strings(z.read(name)))
with open(dst, 'w', encoding='utf-8', errors='replace') as f:
    f.write('\n'.join(lines))
print(f'{apk}: {len(lines)} strings -> {dst}')

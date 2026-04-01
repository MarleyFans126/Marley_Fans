import struct
import zlib

def create_png(width, height, r, g, b):
    def crc32(data):
        return zlib.crc32(data) & 0xffffffff

    def make_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', crc32(c))

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr = make_chunk(b'IHDR', ihdr_data)

    raw = b''
    for _ in range(height):
        raw += b'\x00' + (struct.pack('BBB', r, g, b) * width)

    idat = make_chunk(b'IDAT', zlib.compress(raw))
    iend = make_chunk(b'IEND', b'')

    return sig + ihdr + idat + iend

png = create_png(128, 128, 37, 211, 102)
path = r'c:\Users\ruthi\OneDrive\Desktop\Odoo 19\odoo19\custom\whatsapp_core_community\static\description\icon.png'
with open(path, 'wb') as f:
    f.write(png)
print('Icon created successfully at', path)

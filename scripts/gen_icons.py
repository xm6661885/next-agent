"""Generate the pixel-crab PWA icons (pure Python, no Pillow). Run: python3 scripts/gen_icons.py"""
import struct, zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"
CLAY, EYE = (0xD9, 0x77, 0x57), (0x2A, 0x1E, 0x1A)
TOP, BOTTOM = (0xFC, 0xD6, 0xDE), (0xF7, 0xB4, 0xC4)
# 18 x 10 crab grid, same shape as web/src/components/crab.tsx: (x, y, w, h, color)
CRAB = [(3, 0, 12, 8, CLAY), (1, 4, 2, 2, CLAY), (15, 4, 2, 2, CLAY),
        (4, 8, 1, 2, CLAY), (6, 8, 1, 2, CLAY), (11, 8, 1, 2, CLAY), (13, 8, 1, 2, CLAY),
        (5, 2, 1, 2, EYE), (12, 2, 1, 2, EYE)]

def png(path, size, crab_frac):
    px = [[None] * size for _ in range(size)]
    for y in range(size):
        t = y / (size - 1)
        c = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(size):
            px[y][x] = c
    cell = max(1, int(size * crab_frac / 18))
    ox, oy = (size - 18 * cell) // 2, (size - 10 * cell) // 2 + cell // 2
    for (x, y, w, h, col) in CRAB:
        for yy in range(oy + y * cell, oy + (y + h) * cell):
            for xx in range(ox + x * cell, ox + (x + w) * cell):
                px[yy][xx] = col
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)

OUT.mkdir(parents=True, exist_ok=True)
png(OUT / "apple-touch-icon.png", 180, 0.62)
png(OUT / "icon-192.png", 192, 0.62)
png(OUT / "icon-512.png", 512, 0.62)
png(OUT / "icon-maskable-512.png", 512, 0.48)
print("icons written to", OUT)

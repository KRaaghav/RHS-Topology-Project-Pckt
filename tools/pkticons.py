#!/usr/bin/env python3
"""
pkticons.py - the pictures of the things in the lab that Packet Tracer has no icon for

Packet Tracer has no smartboard, school bell or vending machine. In the lab they are PCs
(they get an address and answer ping like the real thing), and pktlayout.py gives each one
a picture from here so the canvas shows what it is. The pictures are drawn by the code
below, pixel by pixel, and saved inside the .pkt file. No image files, nothing to install.

  python3 pkticons.py <folder>     write every picture as a .png file, to look at them

To change a picture, change its list of shapes in ICONS. A shape is
(kind, numbers, colour) on a 64 x 64 grid, later shapes are drawn over earlier ones:

  ("box", (left, top, right, bottom), colour)
  ("oval", (left, top, right, bottom), colour)
  ("line", (x1, y1, x2, y2, thickness), colour)
"""

import os
import struct
import sys
import zlib

SIZE = 64
FINE = 3                        # every pixel is worked out from 3 x 3 points, for smooth edges

INK = (40, 48, 60)
WHITE, GREY, DARK = (255, 255, 255), (198, 204, 212), (92, 102, 116)
RED, GREEN, BLUE, YELLOW = (226, 68, 62), (52, 178, 96), (56, 128, 226), (247, 200, 52)
BROWN, ORANGE, BLACK = (150, 100, 60), (240, 140, 50), (24, 28, 34)


def seven(x, y, digit, colour):
    """A digit like on a scoreboard, 9 wide and 16 high, made of up to seven bars."""
    bars = {"a": (x, y, x + 9, y + 2), "g": (x, y + 7, x + 9, y + 9), "d": (x, y + 14, x + 9, y + 16),
            "f": (x, y, x + 2, y + 9), "b": (x + 7, y, x + 9, y + 9),
            "e": (x, y + 7, x + 2, y + 16), "c": (x + 7, y + 7, x + 9, y + 16)}
    lit = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
           "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abfgcd"}[digit]
    return [("box", bars[bar], colour) for bar in lit]


ICONS = {
    # a white board in a frame on two legs, with something scribbled on it
    "smartboard": [("box", (9, 48, 12, 60), DARK), ("box", (52, 48, 55, 60), DARK), ("box", (5, 58, 16, 61), DARK),
                   ("box", (48, 58, 59, 61), DARK),
                   ("box", (2, 6, 62, 50), INK), ("box", (5, 9, 59, 47), WHITE),
                   ("line", (10, 36, 18, 22, 3), BLUE), ("line", (18, 22, 26, 34, 3), BLUE),
                   ("line", (26, 34, 34, 18, 3), BLUE), ("line", (34, 18, 42, 30, 3), BLUE),
                   ("line", (40, 40, 54, 40, 2.4), RED), ("line", (40, 34, 50, 34, 2.4), RED),
                   ("oval", (49, 12, 56, 19), YELLOW)],
    # a grey box with a sheet going in at the top and coming out at the front
    "printer": [("box", (16, 4, 48, 26), INK), ("box", (18, 6, 46, 26), WHITE),
                ("box", (4, 22, 60, 48), INK), ("box", (6, 24, 58, 46), GREY),
                ("box", (12, 40, 52, 60), INK), ("box", (14, 42, 50, 58), WHITE),
                ("line", (19, 47, 45, 47, 2), DARK), ("line", (19, 52, 39, 52, 2), DARK),
                ("oval", (48, 28, 54, 34), GREEN), ("box", (10, 29, 26, 33), DARK)],
    # a dome camera under its ceiling plate
    "camera": [("box", (10, 8, 54, 16), INK), ("box", (12, 10, 52, 14), GREY),
               ("oval", (10, -8, 54, 50), INK), ("oval", (13, -5, 51, 47), WHITE), ("box", (8, -10, 56, 9), None),
               ("box", (10, 8, 54, 16), INK), ("box", (12, 10, 52, 14), GREY),
               ("oval", (20, 16, 44, 40), INK), ("oval", (25, 21, 39, 35), BLUE), ("oval", (28, 23, 33, 28), WHITE),
               ("oval", (44, 18, 49, 23), RED)],
    # a bell with its clapper, ringing
    "bell": [("oval", (27, 4, 37, 14), INK), ("oval", (14, 10, 50, 52), INK), ("box", (14, 31, 50, 48), INK),
             ("oval", (17, 13, 47, 49), YELLOW), ("box", (17, 31, 47, 45), YELLOW),
             ("box", (8, 44, 56, 51), INK), ("box", (10, 46, 54, 49), YELLOW),
             ("oval", (26, 49, 38, 61), INK), ("oval", (29, 52, 35, 58), ORANGE),
             ("line", (4, 14, 10, 20, 2.5), DARK), ("line", (60, 14, 54, 20, 2.5), DARK),
             ("line", (2, 28, 9, 28, 2.5), DARK), ("line", (62, 28, 55, 28, 2.5), DARK)],
    # a door with a window, and the badge reader next to it showing green
    "door": [("box", (6, 4, 44, 62), INK), ("box", (9, 7, 41, 62), BROWN), ("box", (15, 12, 35, 30), INK),
             ("box", (17, 14, 33, 28), (176, 216, 244)), ("oval", (33, 36, 39, 42), YELLOW),
             ("box", (48, 22, 62, 46), INK), ("box", (50, 24, 60, 44), GREY), ("oval", (52, 27, 58, 33), GREEN),
             ("line", (52, 38, 58, 38, 1.6), DARK), ("line", (52, 41, 58, 41, 1.6), DARK)],
    # a cash register: screen on a pole, keys, and the drawer
    "register": [("box", (34, 4, 60, 22), INK), ("box", (36, 6, 58, 20), (150, 230, 170)), ("box", (45, 22, 49, 30), INK),
                 ("box", (6, 26, 58, 48), INK), ("box", (8, 28, 56, 46), GREY),
                 ("box", (2, 46, 62, 60), INK), ("box", (4, 48, 60, 58), DARK), ("box", (26, 51, 38, 55), YELLOW)] +
                [("box", (12 + 9 * i, 31 + 7 * j, 18 + 9 * i, 36 + 7 * j), WHITE if (i, j) != (4, 1) else RED)
                 for i in range(5) for j in range(2)],
    # a vending machine: snacks behind glass, buttons, and the flap at the bottom
    "vending": [("box", (10, 2, 54, 62), INK), ("box", (12, 4, 52, 60), RED), ("box", (15, 8, 40, 44), INK),
                ("box", (17, 10, 38, 42), (214, 236, 250)),
                ("box", (43, 10, 49, 18), WHITE), ("box", (43, 22, 49, 25), YELLOW), ("box", (43, 28, 49, 31), YELLOW),
                ("box", (43, 34, 49, 37), YELLOW), ("box", (16, 49, 48, 57), INK), ("box", (18, 51, 46, 55), DARK)] +
               [("oval", (19 + 7 * i, 12 + 10 * j, 24 + 7 * i, 18 + 10 * j), (YELLOW, GREEN, ORANGE, BLUE)[(i + j) % 4])
                for i in range(3) for j in range(3)] +
               [("line", (17, 20.5 + 10 * j, 38, 20.5 + 10 * j, 1.4), DARK) for j in range(3)],
    # the scoreboard of the gym: home 21, guests 17
    "scoreboard": ([("box", (1, 10, 63, 50), INK), ("box", (3, 12, 61, 48), BLACK),
                    ("box", (30, 50, 34, 62), INK), ("box", (20, 59, 44, 62), INK),
                    ("oval", (30, 22, 34, 26), YELLOW), ("oval", (30, 33, 34, 37), YELLOW)]
                   + seven(6, 21, "2", RED) + seven(18, 21, "1", RED) + seven(37, 21, "1", GREEN)
                   + seven(49, 21, "7", GREEN)),
}


def inside(kind, numbers, x, y):
    if kind == "box":
        left, top, right, bottom = numbers
        return left <= x < right and top <= y < bottom
    if kind == "oval":
        left, top, right, bottom = numbers
        rx, ry = (right - left) / 2, (bottom - top) / 2
        return ((x - left - rx) / rx) ** 2 + ((y - top - ry) / ry) ** 2 <= 1
    x1, y1, x2, y2, thick = numbers                 # a line: how far is the point from it?
    dx, dy = x2 - x1, y2 - y1
    along = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return (x - x1 - along * dx) ** 2 + (y - y1 - along * dy) ** 2 <= (thick / 2) ** 2


def pixels(shapes):
    """SIZE rows of SIZE (red, green, blue, alpha) values. A shape with colour None rubs out."""
    rows = []
    for py in range(SIZE):
        row = []
        for px in range(SIZE):
            total = [0, 0, 0, 0]
            for sy in range(FINE):
                for sx in range(FINE):
                    x, y = px + (sx + 0.5) / FINE, py + (sy + 0.5) / FINE
                    colour = None
                    for kind, numbers, shape_colour in shapes:
                        if inside(kind, numbers, x, y):
                            colour = shape_colour
                    if colour:
                        total = [total[0] + colour[0], total[1] + colour[1], total[2] + colour[2], total[3] + 1]
            hits = total[3]
            row.append((total[0] // hits, total[1] // hits, total[2] // hits, 255 * hits // FINE ** 2) if hits
                       else (0, 0, 0, 0))
        rows.append(row)
    return rows


def png(kind):
    """The picture of one kind of thing as the bytes of a .png file."""
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
    raw = b"".join(b"\x00" + bytes(value for pixel in row for value in pixel) for row in pixels(ICONS[kind]))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main(args):
    if len(args) != 1:
        print(__doc__)
        return 2
    os.makedirs(args[0], exist_ok=True)
    for kind in ICONS:
        with open(os.path.join(args[0], kind + ".png"), "wb") as f:
            f.write(png(kind))
        print(os.path.join(args[0], kind + ".png"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

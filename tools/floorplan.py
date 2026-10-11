#!/usr/bin/env python3
"""
floorplan.py - draw the floor plan of the school with the network in it (SVG)

  python3 floorplan.py            writes ../floorplan.svg

It is the same plan pktlayout.py puts on the canvas of the lab, as a picture for the
README: the rooms, walls and halls come from pktlayout.plan(), the cables from the lab
file. The building is made up. It is NOT the real floor plan of Redmond High School.
The rooms come from inventory.csv: E230 is wing E, floor 2.

Only uses the Python standard library, nothing to install.
"""

import html
import os
import sys

import labtest
import pktlayout
from pktconfig import HERE, LAB, Problem

OUT = os.path.join(HERE, "..", "floorplan.svg")
WIDTH = 1600                    # of the picture on the page, the plan is scaled to fit
INK = "#18212b"
THING_COLOURS = {"smartboard": "#3880e2", "printer": "#5c6674", "camera": "#e2443e", "bell": "#e0a800",
                 "door": "#966432", "register": "#34b260", "vending": "#f08c32", "scoreboard": "#18212b"}


def rgb(colour):
    return "#%02x%02x%02x" % colour


def text(x, y, words, size, weight="400", anchor="start", colour=INK):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'fill="{colour}">{html.escape(words)}</text>')


def cable_parts(plan, p):
    """The cables: thick orange between routers and switches, thin grey to what is plugged in."""
    thin, thick = [], []
    for a, a_port, b, b_port in p.links:
        if a in plan.where and b in plan.where:
            (x1, y1), (x2, y2) = plan.where[a], plan.where[b]
            if a in p.configs and b in p.configs:
                thick.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#d9822b" stroke-width="5" '
                             f'opacity="0.75"/>')
            else:
                thin.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#44515e" stroke-width="1.5" '
                            f'opacity="0.3"/>')
    return thin + thick


def device_parts(plan, p, kinds):
    """Every device where the plan puts it. kinds is {device name: its type in the inventory}."""
    parts = []
    for name, (x, y) in plan.where.items():
        kind = kinds.get(name, "")
        if name in p.configs:                                      # a router or switch: a box with its name
            box = len(name) * 15 + 30
            parts.append(f'<g class="node" data-name="{html.escape(name)}"><rect x="{x - box / 2}" y="{y - 24}" '
                         f'width="{box}" height="48" rx="10" fill="#ffffff" stroke="{INK}" stroke-width="3"/>'
                         + text(x, y + 9, name, 25, "700", "middle") + "</g>")
        elif kind in THING_COLOURS:                                # a building thing: a dot in its colour
            parts.append(f'<circle cx="{x}" cy="{y}" r="24" fill="{THING_COLOURS[kind]}" stroke="#ffffff" stroke-width="4"/>')
            parts.append(text(x, y + 50, name, 17, "400", "middle"))
        elif kind == "server" or name == "INET-SRV":
            parts.append(f'<rect x="{x - 20}" y="{y - 30}" width="40" height="60" rx="4" fill="#44515e"/>')
            parts.append(text(x, y + 54, name, 19, "600", "middle"))
        else:                                                      # a PC
            parts.append(f'<rect x="{x - 22}" y="{y - 18}" width="44" height="32" rx="4" fill="#ffffff" '
                         f'stroke="#44515e" stroke-width="3"/>')
    return parts


def svg(lab_path=LAB):
    """The whole picture as SVG text."""
    plan = pktlayout.plan()
    p = labtest.Picture(lab_path)
    kinds = {row["name"]: row["type"] for row in pktlayout.inventory()}
    width, height = plan.size
    # the long notes are left out, only the room next to the C wing where they stand is not needed
    cut = min(y for x, y, words in plan.big_notes if x > pktlayout.LEFT + 10) - 40
    height = max([box[3] for box in plan.floors + plan.walls] + [cut]) + 60 if False else \
        max(box[3] for box in plan.floors + plan.walls) + 150
    width = max(box[2] for box in plan.floors + plan.walls) + pktlayout.LEFT
    parts = []
    for left, top, right, bottom, colour in plan.floors:
        parts.append(f'<rect x="{left}" y="{top}" width="{right - left}" height="{bottom - top}" fill="{rgb(colour)}"/>')
    for left, top, right, bottom, colour in plan.walls + plan.extras:
        parts.append(f'<rect x="{left}" y="{top}" width="{right - left}" height="{bottom - top}" fill="{rgb(colour)}"/>')
    for left, top, right, bottom, colour in plan.ovals:
        parts.append(f'<ellipse cx="{(left + right) / 2}" cy="{(top + bottom) / 2}" rx="{(right - left) / 2}" '
                     f'ry="{(bottom - top) / 2}" fill="{rgb(colour)}"/>')
    long_notes = {(x, y) for x, y, words in plan.big_notes}
    for x, y, words in plan.notes:
        if (x, y) not in long_notes:
            for n, line in enumerate(words.split("\n")):
                parts.append(text(x, y + 22 + pktlayout.LINE * n, line, 22, "700" if n == 0 else "400"))

    parts += cable_parts(plan, p) + device_parts(plan, p, kinds)

    # what the dots mean
    used = [kind for kind in THING_COLOURS if kind in kinds.values()]
    key_y = height - 70
    parts.append(text(pktlayout.LEFT, key_y + 8, "Building things (VLAN 40):", 26, "700"))
    for n, kind in enumerate(used):
        x = pktlayout.LEFT + 400 + 250 * n
        parts.append(f'<circle cx="{x}" cy="{key_y}" r="18" fill="{THING_COLOURS[kind]}"/>')
        parts.append(text(x + 30, key_y + 8, kind, 26))
    x = pktlayout.LEFT + 400 + 250 * len(used)
    parts.append(f'<line x1="{x}" y1="{key_y}" x2="{x + 80}" y2="{key_y}" stroke="#d9822b" stroke-width="6"/>')
    parts.append(text(x + 95, key_y + 8, "cable between switches and routers", 26))

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{WIDTH}" '
            f'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif">\n'
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>\n' + "\n".join(parts) + "\n</svg>\n")


def main(args):
    if args:
        print(__doc__)
        return 2
    try:
        picture = svg()
    except Problem as err:
        print("Problem:", err)
        return 1
    with open(OUT, "w") as f:
        f.write(picture)
    print("Written to", os.path.normpath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

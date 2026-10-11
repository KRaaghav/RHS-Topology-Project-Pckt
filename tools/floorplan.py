#!/usr/bin/env python3
"""
floorplan.py - draw a sketch of the school building with the network in it (SVG)

  python3 floorplan.py            writes ../floorplan.svg

The building is made up: three wings (E, C, B) with two floors each, coming off a main
hall with the office, the server room (MDF), the commons and the gym. It is NOT the real
floor plan of Redmond High School. The rooms that are in the lab come from inventory.csv:
E230 is wing E, floor 2. They are drawn in colour with their switch and the cable run
back to the MDF. Grey rooms are only there to make it look like a school, they are not
in the lab.

Only uses the Python standard library, nothing to install.
"""

import html
import os
import sys

import pktlayout
from pktconfig import HERE, Problem

OUT = os.path.join(HERE, "..", "floorplan.svg")
FLOOR_WIDTH, FLOOR_HEIGHT = 900, 640
HALL = 170                      # width of the main hall on the left of every floor
SLOT = 118                      # width of one room in a wing
SLOTS = 6                       # rooms on each side of a wing corridor
WING_HEIGHT, ROOM_HEIGHT, CORRIDOR = 180, 66, 34
INK, SOFT, WALL = "#18212b", "#5f6c7a", "#44515e"
CABLE = "#d9822b"
# what is in the main hall on each floor: (name, second line, colour, part of the height)
MAIN_HALL = {"1": [("Main office", "+ counseling, nurse", "#d0f8d0", 0.2), ("MDF server room", "+ IT office", "#b8f8f8", 0.16),
                   ("Commons", "cafeteria, kitchen", "#eceff2", 0.3), ("Gym", "lockers, PE office", "#eceff2", 0.34)],
             "2": [("Staff lounge", "workroom, copier", "#eceff2", 0.2), ("IDF closet", "riser from the MDF", "#eceff2", 0.16),
                   ("Open to commons", "below", "#f7f8fa", 0.3), ("Gym", "upper part, bleachers", "#eceff2", 0.34)]}
OTHER_ROOMS = ["Stairs", "Classroom", "Classroom", "Restrooms", "Classroom", "Classroom"]


def text(x, y, words, size=11, weight="400", anchor="middle", colour=INK):
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'fill="{colour}">{html.escape(words)}</text>')


def box(x, y, width, height, colour, stroke=WALL):
    return f'<rect x="{x:.0f}" y="{y:.0f}" width="{width:.0f}" height="{height:.0f}" fill="{colour}" stroke="{stroke}" stroke-width="1.2"/>'


def floor(number, left, top, wings, labels):
    """One floor: the main hall on the left, the wings to the right of it."""
    parts = [text(left, top - 14, f"Floor {number}", 15, "700", "start")]
    cables = []
    hall_x = left + HALL - 22                              # the cable tray runs down the main hall

    # the main hall
    y = top
    mdf = None
    for name, more, colour, share in MAIN_HALL[number]:
        height = FLOOR_HEIGHT * share
        parts.append(box(left, y, HALL - 44, height, colour))
        parts.append(text(left + (HALL - 44) / 2, y + height / 2 - 3, name, 11.5, "700"))
        parts.append(text(left + (HALL - 44) / 2, y + height / 2 + 12, more, 9.5, "400", "middle", SOFT))
        if name in ("MDF server room", "IDF closet"):
            mdf = y + height / 2
        if name == "Main office":
            parts.append(f'<circle cx="{left + 16}" cy="{y + 16}" r="6" fill="#1f6f54"/>')
            parts.append(text(left + 8, y + 36, "SW-OFFICE", 8.5, "600", "start"))
            cables.append(f'<path d="M{left + 16} {y + 16} L{hall_x} {y + 16} L{hall_x} {top + FLOOR_HEIGHT * 0.28:.0f}" />')
        if name == "MDF server room":
            parts.append(f'<circle cx="{left + 16}" cy="{y + 16}" r="6" fill="#1f6f54"/>')
            parts.append(text(left + 27, y + 20, "SW-MDF", 8.5, "600", "start"))
        y += height
    parts.append(box(left + HALL - 44, top, 44, FLOOR_HEIGHT, "#ffffff"))
    parts.append(f'<text transform="translate({left + HALL - 33} {top + FLOOR_HEIGHT / 2}) rotate(-90)" font-size="10" '
                 f'text-anchor="middle" fill="{SOFT}">main hall</text>')
    cables.append(f'<path d="M{left + HALL - 44} {mdf:.0f} L{hall_x} {mdf:.0f}" />')

    # the wings
    gap = (FLOOR_HEIGHT - len(wings) * WING_HEIGHT) / max(1, len(wings) - 1) if len(wings) > 1 else 0
    for w, (wing, floors) in enumerate(wings.items()):
        wing_top = top + w * (WING_HEIGHT + gap)
        x0 = left + HALL
        corridor_y = wing_top + ROOM_HEIGHT + 24
        parts.append(text(x0 + SLOT * SLOTS + 10, wing_top + 12, f"{wing} wing", 12, "700", "start"))
        parts.append(box(x0, corridor_y, SLOT * SLOTS, CORRIDOR, "#ffffff"))
        parts.append(text(x0 + SLOT * SLOTS / 2, corridor_y + CORRIDOR / 2 + 4, f"{wing} wing corridor, floor {number}",
                          9.5, "400", "middle", SOFT))
        in_lab = floors.get(number, [])
        # rooms of the lab take every second place, first along the top, then along the bottom
        places = [(side, slot) for side in (0, 1) for slot in (1, 3, 5, 2, 4, 0)]
        taken = dict(zip(places, in_lab))
        run_end = x0
        for side in (0, 1):
            room_y = wing_top + 24 if side == 0 else corridor_y + CORRIDOR
            for slot in range(SLOTS):
                x = x0 + slot * SLOT
                room = taken.get((side, slot))
                if room is None:
                    name = OTHER_ROOMS[(slot + 3 * side) % len(OTHER_ROOMS)]
                    parts.append(box(x, room_y, SLOT, ROOM_HEIGHT, "#eceff2"))
                    parts.append(text(x + SLOT / 2, room_y + ROOM_HEIGHT / 2 + 4, name, 9.5, "400", "middle", SOFT))
                    continue
                parts.append(box(x, room_y, SLOT, ROOM_HEIGHT, "#ffffb0"))
                parts.append(text(x + SLOT / 2, room_y + 17, room, 12, "700"))
                parts.append(text(x + SLOT / 2, room_y + 31, labels.get(room, "Classroom"), 9.5, "400", "middle", SOFT))
                parts.append(text(x + SLOT / 2, room_y + 45, "15 students + teacher", 9, "400", "middle", SOFT))
                # the switch sits by the door, the cable goes along the corridor to the main hall
                door_y = room_y + ROOM_HEIGHT - 9 if side == 0 else room_y + 9
                tray_y = corridor_y + (9 if side == 0 else CORRIDOR - 9)
                dot_x = x + SLOT - 14
                parts.append(f'<circle cx="{dot_x}" cy="{door_y}" r="5" fill="#1f6f54"/>')
                parts.append(text(dot_x - 9, door_y + 3.5, "SW-" + room, 8.5, "600", "end"))
                cables.append(f'<path d="M{dot_x} {door_y} L{dot_x} {tray_y} L{hall_x} {tray_y}" />')
                run_end = max(run_end, dot_x)
        if in_lab:
            cables.append(f'<path d="M{hall_x} {corridor_y + 9} L{hall_x} {mdf:.0f}" />')
            cables.append(f'<path d="M{hall_x} {corridor_y + CORRIDOR - 9} L{hall_x} {mdf:.0f}" />')
    return parts + [f'<g fill="none" stroke="{CABLE}" stroke-width="1.8" opacity="0.85">' + "".join(cables) + "</g>"]


def svg():
    """The whole sketch as SVG text."""
    wings = pktlayout.wings()
    labels = pktlayout.room_labels()
    floors = sorted({floor_number for floor_list in wings.values() for floor_number in floor_list} | {"1"})
    width = 40 + len(floors) * (FLOOR_WIDTH + 70)
    height = FLOOR_HEIGHT + 190
    parts = [text(30, 30, "Sketch of the building", 16, "700", "start"),
             text(30, 48, "Made up for this project. It is not the real floor plan of Redmond High School.",
                  11, "400", "start", SOFT)]
    for i, number in enumerate(floors):
        parts += floor(number, 30 + i * (FLOOR_WIDTH + 70), 100, wings, labels)

    y = FLOOR_HEIGHT + 135
    legend = [("#ffffb0", "room in the lab: a 2960 switch, 15 student PCs (VLAN 10), 1 teacher PC (VLAN 20)"),
              ("#d0f8d0", "main office: SW-OFFICE, 6 PCs (VLAN 30)"),
              ("#b8f8f8", "MDF: both edge routers, both core and both distribution switches, SW-MDF, 4 servers, 2 IT PCs"),
              ("#eceff2", "not in the lab, only drawn so it looks like a school")]
    for i, (colour, words) in enumerate(legend):
        x = 30 + (i % 2) * 760
        row_y = y + (i // 2) * 22
        parts.append(box(x, row_y - 11, 16, 13, colour))
        parts.append(text(x + 24, row_y, words, 11, "400", "start"))
    parts.append(f'<path d="M1550 {y - 5} L1590 {y - 5}" stroke="{CABLE}" stroke-width="2"/>')
    parts.append(text(1598, y, "two uplinks per room switch, one to each", 11, "400", "start"))
    parts.append(text(1598, y + 16, "distribution switch in the MDF", 11, "400", "start"))
    parts.append('<circle cx="1560" cy="%d" r="5" fill="#1f6f54"/>' % (y + 34))
    parts.append(text(1598, y + 38, "access switch", 11, "400", "start"))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">\n'
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
    print("Written to floorplan.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""
pktlayout.py - tidy the canvas of the Packet Tracer lab

It turns the logical view into a floor plan of the school, without touching any device config:

  - puts every device in its room: the server room with the routers and layer 3 switches
    in the middle, a wing with classrooms on three sides, the main office, the front
    entrance, the cafeteria and the gym next to the street
  - draws the floors, the walls with their doors, the halls with the wiring closets, and
    the things that make it a school: desks, lockers, stairs, the bus loop, the field
  - gives the smartboards, cameras, bells and the other things their own picture
  - writes the text notes on the canvas that explain what the lab does, and the same
    text into the lab description (the "i" button in Packet Tracer)

Examples:

  python3 pktlayout.py                 arrange the lab
  python3 pktlayout.py --dry-run       only say what would move

To change a note, edit the text in NOTES below and run it again. --lab "other file.pkt"
works on another file. Close the lab in Packet Tracer first. A copy of the lab from
before is kept in ../changes/backups.

Only uses the Python standard library, nothing to install.
"""

import base64
import csv
import html
import os
import re
import sys
import uuid

import pktfile
import pkticons
from pktconfig import HERE, LAB, Problem, backup_lab, packet_tracer_is_open

# ---------------------------------------------------------------- sizes and colours
# All numbers are pixels on the canvas. A device position is the middle of its icon.
# The canvas is a floor plan: every room is a coloured floor with dark walls around it.

WALL = 14                       # how thick a wall is
GAP = 50                        # the walkway between two buildings
ROOM_W, ROOM_H = 800, 760       # a classroom: three rows of five desks, the teacher in front
HALL = 560                      # the hall of the E and B wing (rooms above and below it)
HALL_C = 720                    # the hall of the C wing (rooms left and right of it)
CLOSET_W, CLOSET_H = 150, 130   # the wiring closet a room switch sits in
CORE_W = 1472                   # the building in the middle with the server room
NORTH_H = 640                   # the main office, the cafeteria and the gym
LEFT, TOP = 80, 20
LINE = 28                       # height of one line of a note
WINGS = "ECB"                   # the order of the wings, other letters come after

# colours (red, green, blue)
BRICK = (70, 78, 92)                                        # walls
YELLOW, PEACH = (255, 250, 205), (255, 232, 196)            # classroom downstairs, upstairs
SKY, MINT, LILAC = (214, 234, 255), (214, 245, 224), (232, 222, 255)   # library, computer lab, science lab
GREEN, CYAN, PURPLE = (208, 248, 208), (190, 244, 244), (228, 218, 255)
RED, BLUE, GREY = (255, 216, 216), (208, 226, 255), (232, 232, 232)
FLOOR, PATH, ORANGE = (240, 240, 236), (222, 214, 200), (255, 214, 160)   # hall, walkway outside, closet
CREAM, WOOD, COURT = (255, 240, 214), (236, 212, 170), (250, 228, 190)    # cafeteria, gym, its court
DESK, LOCKER, STEP = (226, 205, 170), (120, 160, 210), (200, 200, 196)
GRASS, TREE, ROAD, BUS, TRACK = (196, 232, 176), (96, 168, 92), (150, 154, 160), (250, 204, 60), (206, 120, 84)
NAMED = {"Library": SKY, "Computer lab": MINT, "Science lab": LILAC}

OFFICE_PCS = ["PRINCIPAL-PC", "ASST-PRINCIPAL-PC", "COUNSELOR1-PC", "COUNSELOR2-PC", "REGISTRAR-PC",
              "FRONT-OFFICE-PC"]
IT_PCS = ["IT-PC1", "IT-PC2"]
COMMONS = "A100"                # the room number of the cafeteria and the gym (one switch, no student PCs)


# ---------------------------------------------------------------- what is in the school

def inventory():
    with open(os.path.join(HERE, "inventory.csv"), newline="") as f:
        return list(csv.DictReader(f))


def room_labels():
    """{room number: its name} for rooms that have one, like C114: Library. The name is in
    the location of the switch in inventory.csv: Room C114 (Library)."""
    found = {}
    for row in inventory():
        match = re.fullmatch(r"Room (\w+) \((.+)\)", row["location"])
        if match and row["type"] == "switch 2960":
            found[match.group(1)] = match.group(2)
    return found


def classrooms():
    """The numbers of the rooms with student PCs, from the 2960 switches in inventory.csv
    (SW-E230 -> E230), in the order of the wings, then by floor and number. E230 is wing E,
    floor 2. pktbuild.py adds a line to the inventory when it adds a room, so the layout
    follows by itself."""
    rows = inventory()
    names = {row["name"] for row in rows}
    found = [row["name"][3:] for row in rows
             if row["type"] == "switch 2960" and row["name"][3:] + "-PC01" in names]
    return sorted(found, key=lambda room: (WINGS.index(room[0]) if room[0] in WINGS else len(WINGS), room))


def wings():
    """{wing letter: {floor: [rooms]}} in canvas order."""
    found = {}
    for room in classrooms():
        found.setdefault(room[0], {}).setdefault(room[1], []).append(room)
    return found


def things(place):
    """[(name, kind)] of the smartboards, printers, cameras... that inventory.csv puts in a place."""
    return [(row["name"], row["type"]) for row in inventory()
            if row["location"] == place and row["type"] in pkticons.ICONS]


def servers():
    return [row["name"] for row in inventory() if row["type"] == "server"]


def rooms():
    """(lines of the room note, access switch, colour, what is plugged in, wing) of every room
    with an access switch."""
    labels = room_labels()
    found = [("Main office + counseling\nVLAN 30 MANAGEMENT", "SW-OFFICE", GREEN,
              OFFICE_PCS + [name for place in ("Main office", "Front entrance") for name, kind in things(place)],
              "office")]
    for room in classrooms():
        name = f"Room {room} - {labels[room]}" if room in labels else f"Room {room}"
        floor = "upstairs" if room[1] != "1" else "downstairs"
        found.append((f"{name} ({floor})\n15 students VLAN 10, teacher VLAN 20\nsmartboard VLAN 40", "SW-" + room,
                      NAMED.get(labels.get(room)) or (YELLOW if room[1] == "1" else PEACH),
                      [f"{room}-PC{n:02d}" for n in range(1, 16)] + [room + "-TCHR"]
                      + [name for name, kind in things("Room " + room)], room[0]))
    if any(row["name"] == "SW-" + COMMONS for row in inventory()):
        found.append((f"Room {COMMONS} - Cafeteria and gym\nVLAN 40 BUILDING", "SW-" + COMMONS, CREAM,
                      [name for place in ("Cafeteria", "Gym", "Room " + COMMONS) for name, kind in things(place)],
                      COMMONS[0]))
    found.append(("MDF (server room) + IT office\nVLAN 70 SERVERS\nVLAN 99 NETWORK-IT", "SW-MDF", CYAN,
                  servers() + IT_PCS, "mdf"))
    return found


# ---------------------------------------------------------------- drawing the school

class Plan:
    """Everything on the canvas. floors never lie on top of each other, so it does not matter
    in which order Packet Tracer draws them. extras (desks, lockers, trees) are small things
    drawn on a floor, ovals are the round ones."""

    def __init__(self):
        self.floors = []        # (left, top, right, bottom, colour)
        self.walls = []
        self.extras = []
        self.ovals = []
        self.notes = []         # (x, y, text)
        self.where = {}         # device name: (x, y)
        self.areas = {}         # a name like "E wing hall": (left, top, right, bottom), for floorplan.py

    def floor(self, left, top, right, bottom, colour):
        self.floors.append((left, top, right, bottom, colour))

    def extra(self, left, top, right, bottom, colour):
        self.extras.append((left, top, right, bottom, colour))

    def oval(self, left, top, right, bottom, colour):
        self.ovals.append((left, top, right, bottom, colour))

    def note(self, x, y, text):
        self.notes.append((x, y, text))

    def put(self, name, x, y):
        self.where[name] = (round(x), round(y))

    def title(self, box, text):
        """A note in the bottom left corner of a room."""
        self.note(box[0] + 14, box[3] - LINE * len(text.split("\n")) - 12, text)

    def building(self, floors):
        """Add the floors of one building and put walls everywhere between and around them.
        A floor that is only as thick as a wall is a door: it makes a gap in the wall."""
        inside = [f for f in floors if min(f[2] - f[0], f[3] - f[1]) > WALL]
        left = min(f[0] for f in inside) - WALL
        top = min(f[1] for f in inside) - WALL
        right = max(f[2] for f in inside) + WALL
        bottom = max(f[3] for f in inside) + WALL
        self.floors += floors
        self.walls += [piece + (BRICK,) for piece in leftover((left, top, right, bottom), floors)]
        return left, top, right, bottom


def leftover(box, holes):
    """The part of a box that no hole covers, cut into rectangles that do not overlap."""
    xs = sorted({box[0], box[2]} | {v for h in holes for v in (h[0], h[2]) if box[0] < v < box[2]})
    ys = sorted({box[1], box[3]} | {v for h in holes for v in (h[1], h[3]) if box[1] < v < box[3]})
    rows = []
    for top, bottom in zip(ys, ys[1:]):
        runs = []
        for left, right in zip(xs, xs[1:]):
            x, y = (left + right) / 2, (top + bottom) / 2
            if any(h[0] <= x < h[2] and h[1] <= y < h[3] for h in holes):
                continue
            if runs and runs[-1][1] == left:
                runs[-1] = (runs[-1][0], right)
            else:
                runs.append((left, right))
        rows.append((top, bottom, runs))
    found = []
    open_runs = {}              # (left, right): top of the rectangle that is still growing
    for top, bottom, runs in rows + [(box[3], box[3], [])]:
        for run in list(open_runs):
            if run not in runs:
                found.append((run[0], open_runs.pop(run), run[1], top))
        for run in runs:
            open_runs.setdefault(run, top)
    return found


def classroom(plan, room, x, y, colour, title):
    """A classroom with its top left corner at x, y: smartboard and teacher in front,
    three rows of five student desks."""
    box = (x, y, x + ROOM_W, y + ROOM_H)
    plan.areas["Room " + room] = box
    plan.put(room + "-TCHR", x + 470, y + 130)
    plan.extra(x + 395, y + 92, x + 545, y + 168, DESK)
    seats = [(x + 220, y + 130), (x + 690, y + 130), (x + 90, y + 130)]
    for (name, kind), seat in zip(sorted(things("Room " + room), key=lambda t: t[1] != "smartboard"), seats):
        plan.put(name, *seat)
    plan.extra(x + 120, y + 14, x + 320, y + 26, BRICK)             # the wall the smartboard hangs on
    for n in range(15):
        px, py = x + 100 + 150 * (n % 5), y + 290 + 145 * (n // 5)
        plan.put(f"{room}-PC{n + 1:02d}", px, py)
        plan.extra(px - 60, py - 36, px + 60, py + 28, DESK)
    plan.title(box, title)
    return box + (colour,)


def wing_across(plan, wing, x, y, upstairs, downstairs, titles, colours, way_out="right"):
    """A wing with a hall from left to right: the upstairs rooms are drawn above the hall,
    the downstairs rooms below it. x, y is the top left corner of its first floor, way_out is
    the end of the hall with the door to the server room. Returns the outside of the building."""
    columns = max(len(upstairs), len(downstairs), 1)
    width = columns * ROOM_W + (columns - 1) * WALL
    hall_top = y + ROOM_H + WALL
    hall = (x, hall_top, x + width, hall_top + HALL)
    floors, closets = [], []
    for row, row_rooms in enumerate((upstairs, downstairs)):
        for column, room in enumerate(row_rooms):
            rx = x + column * (ROOM_W + WALL)
            ry = y if row == 0 else hall_top + HALL + WALL
            floors.append(classroom(plan, room, rx, ry, colours[room], titles[room]))
            # the closet with the switch stands in the hall against the wall of its room, the door next to it
            if row == 0:
                closet = (rx + 130, hall_top, rx + 130 + CLOSET_W, hall_top + CLOSET_H)
                door = (rx + 350, hall_top - WALL, rx + 450, hall_top)
            else:
                closet = (rx + ROOM_W - 130 - CLOSET_W, hall[3] - CLOSET_H, rx + ROOM_W - 130, hall[3])
                door = (rx + ROOM_W - 450, hall[3], rx + ROOM_W - 350, hall[3] + WALL)
            closets.append(closet + (ORANGE,))
            floors.append(door + (FLOOR,))
            plan.put("SW-" + room, (closet[0] + closet[2]) / 2, closet[1] + 50)
    floors += closets + [piece + (FLOOR,) for piece in leftover(hall, closets)]
    # an empty corner where a floor has fewer rooms is a little yard
    box = (x, y, x + width, hall[3] + WALL + ROOM_H)
    floors += [piece + (GRASS,) for piece in leftover(box, floors)
               if piece[2] - piece[0] > WALL and piece[3] - piece[1] > WALL]
    plan.areas[wing + " wing hall"] = hall
    # in the hall: the camera and the bell, lockers along the walls, the stairs at the far end
    middle = (hall[1] + hall[3]) // 2
    floors.append((hall[2], middle - 70, hall[2] + WALL, middle + 70, FLOOR) if way_out == "right" else
                  (hall[0] - WALL, middle - 70, hall[0], middle + 70, FLOOR))
    side = 1 if way_out == "right" else -1
    start = x + 290 if way_out == "right" else x + width - 290
    spots = [(start + side * 140 * n, middle + 70) for n in range(4)]
    for (name, kind), spot in zip(things(wing + " wing hall"), spots):
        plan.put(name, *spot)
    for column in range(columns):
        for n in range(4):
            lx = x + column * (ROOM_W + WALL) + 60 + 60 * n
            plan.extra(lx, hall[3] - 34, lx + 50, hall[3] - 6, LOCKER)
    far = x + 14 if way_out == "right" else x + width - 200
    plan.note(far, middle - LINE, f"{wing} WING hall\nstairs, lockers")
    for n in range(5):
        plan.extra(far + 22 * n, middle + 40, far + 16 + 22 * n, middle + 130, STEP)
    return plan.building(floors)


def wing_down(plan, wing, x, y, left_rooms, right_rooms, titles, colours):
    """A wing with a hall from top to bottom: downstairs rooms on the left of the hall,
    upstairs rooms on the right. x is the middle of the hall, y the top of the floors."""
    rows = max(len(left_rooms), len(right_rooms), 1)
    height = rows * ROOM_H + (rows - 1) * WALL
    hall = (x - HALL_C // 2, y, x + HALL_C // 2, y + height)
    floors, closets = [], []
    for side, side_rooms in enumerate((left_rooms, right_rooms)):
        for row, room in enumerate(side_rooms):
            ry = y + row * (ROOM_H + WALL)
            rx = hall[0] - WALL - ROOM_W if side == 0 else hall[2] + WALL
            floors.append(classroom(plan, room, rx, ry, colours[room], titles[room]))
            if side == 0:
                closet = (hall[0], ry + 110, hall[0] + CLOSET_W, ry + 110 + CLOSET_H)
                door = (hall[0] - WALL, ry + 330, hall[0], ry + 430)
            else:
                closet = (hall[2] - CLOSET_W, ry + ROOM_H - 110 - CLOSET_H, hall[2], ry + ROOM_H - 110)
                door = (hall[2], ry + ROOM_H - 430, hall[2] + WALL, ry + ROOM_H - 330)
            closets.append(closet + (ORANGE,))
            floors.append(door + (FLOOR,))
            plan.put("SW-" + room, (closet[0] + closet[2]) / 2, closet[1] + 50)
    floors += closets + [piece + (FLOOR,) for piece in leftover(hall, closets)]
    box = (hall[0] - WALL - ROOM_W, y, hall[2] + WALL + ROOM_W, y + height)
    floors += [piece + (GRASS,) for piece in leftover(box, floors)
               if piece[2] - piece[0] > WALL and piece[3] - piece[1] > WALL]
    plan.areas[wing + " wing hall"] = hall
    spots = [(hall[0] + 90 + 130 * n, hall[3] - 110) for n in range(5)]
    for (name, kind), spot in zip(things(wing + " wing hall"), spots):
        plan.put(name, *spot)
    for row in range(rows):
        for n in range(4):
            ly = y + row * (ROOM_H + WALL) + 480 + 60 * n
            plan.extra(hall[0] + 6, ly, hall[0] + 34, ly + 50, LOCKER)
    floors.append((x - 120, y - WALL, x + 120, y, FLOOR))            # the door to the server room
    plan.note(hall[0] + 250, hall[3] - 280, f"{wing} WING hall\nstairs, lockers")
    for n in range(5):
        plan.extra(hall[0] + 250 + 22 * n, hall[3] - 210, hall[0] + 266 + 22 * n, hall[3] - 150, STEP)
    return plan.building(floors)


def server_room_things(p, core_right, main_top, server_room, it_office, aisle):
    """What stands in the middle building: the rack, the servers and the desks of the IT office."""
    # things a real server room has that are not on the network
    p.extra(core_right - 190, main_top + 20, core_right - 20, main_top + 110, (120, 200, 230))
    p.note(core_right - 180, main_top + 30, "air conditioner")
    p.extra(core_right - 190, main_top + 140, core_right - 20, main_top + 230, (90, 100, 110))
    p.note(core_right - 180, main_top + 240, "UPS battery:\n15 minutes of power")
    p.extra(core_right - 190, main_top + 330, core_right - 20, main_top + 380, RED)
    p.note(core_right - 180, main_top + 390, "fire extinguisher")

    for n in range(4):                                         # the power strips of the rack are devices too
        p.put(f"Power Distribution Device{n}", core_right - 105, main_top + 520 + 80 * n)
    p.note(core_right - 190, main_top + 450, "rack power strips")

    p.put("SW-MDF", server_room[0] + 200, server_room[1] + 110)
    for n, name in enumerate(servers()):
        p.put(name, server_room[0] + 105 + 190 * (n % 2), server_room[1] + 270 + 150 * (n // 2))
    p.title(server_room, "Servers, VLAN 70\nSRV-BACKUP: copy of the files\nSRV-CAMERAS: records video")
    for n, name in enumerate(IT_PCS):
        p.put(name, it_office[0] + 105 + 190 * n, it_office[1] + 270)
        p.extra(it_office[0] + 45 + 190 * n, it_office[1] + 234, it_office[0] + 165 + 190 * n, it_office[1] + 298, DESK)
    p.extra(it_office[0] + 30, it_office[1] + 420, it_office[2] - 30, it_office[1] + 480, DESK)
    p.note(it_office[0] + 40, it_office[1] + 490, "workbench: spare switches,\ncables, a label printer")
    p.title(it_office, "IT office\nVLAN 99 NETWORK-IT")
    p.note(aisle[0] + 200, aisle[1] + 330, "the cables of the C wing\ncome up through this hall")


def office_and_entrance(p, mx, north_top):
    """The main office and the front entrance, above the server room. Returns the two boxes."""
    office = (mx - 250 - WALL - 1000, north_top, mx - 250 - WALL, north_top + NORTH_H)
    p.building([office + (GREEN,), (office[2], north_top + 420, office[2] + WALL, north_top + 520, FLOOR)])
    p.areas["Main office"] = office
    for n, name in enumerate(OFFICE_PCS):
        px, py = office[0] + 130 + 215 * (n % 3), office[1] + 130 + 170 * (n // 3)
        p.put(name, px, py)
        p.extra(px - 70, py - 36, px + 70, py + 28, DESK)
    for (name, kind), spot in zip(things("Main office"), [(office[2] - 150, office[1] + 130 + 170 * n) for n in range(3)]):
        p.put(name, *spot)
    p.put("SW-OFFICE", office[0] + 640, office[1] + NORTH_H - 130)
    p.title(office, "Main office + counseling\nVLAN 30 MANAGEMENT")

    entrance = (office[2] + WALL + 10, north_top, mx + 250 - 10, north_top + NORTH_H + WALL + GAP)
    p.floor(*entrance, PATH)
    p.areas["Front entrance"] = entrance
    for (name, kind), spot in zip(things("Front entrance"), [(entrance[0] + 60, north_top + 270 + 200 * n) for n in range(3)]):
        p.put(name, *spot)
    p.note(entrance[0] + 14, entrance[3] - 2 * LINE - 12, "FRONT ENTRANCE\nvisitors badge in here")
    return office, entrance


def cafeteria_and_gym(p, mx, north_top):
    """The cafeteria and the gym, right of the front entrance. Returns the box around the two."""
    cafeteria = (mx + 250 + WALL, north_top, mx + 250 + WALL + 800, north_top + NORTH_H)
    gym = (cafeteria[2] + WALL, north_top, cafeteria[2] + WALL + 800, north_top + NORTH_H)
    commons = p.building([cafeteria + (CREAM,), gym + (WOOD,),
                          (cafeteria[2], north_top + 280, gym[0], north_top + 380, FLOOR),
                          (cafeteria[0] - WALL, north_top + 420, cafeteria[0], north_top + 520, FLOOR)])
    p.areas["Cafeteria"], p.areas["Gym"] = cafeteria, gym
    spots = [(cafeteria[0] + 130, north_top + 130), (cafeteria[0] + 320, north_top + 130),
             (cafeteria[0] + 680, north_top + 130), (cafeteria[0] + 680, north_top + 330),
             (cafeteria[0] + 500, north_top + 130), (cafeteria[0] + 680, north_top + 500)]
    for (name, kind), spot in zip(things("Cafeteria") + things("Room " + COMMONS), spots):
        p.put(name, *spot)
    p.put("SW-" + COMMONS, cafeteria[0] + 360, north_top + NORTH_H - 130)
    for n in range(3):                                         # lunch tables with a stool on each side
        tx, ty = cafeteria[0] + 110 + 170 * n, north_top + 300
        p.oval(tx - 55, ty - 35, tx + 55, ty + 35, DESK)
        p.oval(tx - 14, ty - 62, tx + 14, ty - 40, LOCKER)
        p.oval(tx - 14, ty + 40, tx + 14, ty + 62, LOCKER)
    p.title(cafeteria, f"Room {COMMONS} - Cafeteria\nregisters, vending machine\nVLAN 40 BUILDING")
    spots = [(gym[0] + 400, north_top + 110), (gym[0] + 120, north_top + 110), (gym[0] + 680, north_top + 110),
             (gym[0] + 680, north_top + NORTH_H - 130), (gym[0] + 120, north_top + 300)]
    for (name, kind), spot in zip(sorted(things("Gym"), key=lambda t: t[1] != "scoreboard"), spots):
        p.put(name, *spot)
    court = (gym[0] + 230, north_top + 220, gym[0] + 570, north_top + 520)
    p.extra(*court, COURT)
    p.extra(court[0], (court[1] + court[3]) // 2 - 2, court[2], (court[1] + court[3]) // 2 + 2, BRICK)
    p.oval(gym[0] + 360, north_top + 330, gym[0] + 440, north_top + 410, ORANGE)
    p.title(gym, "Gym\nscoreboard, bell, door reader")
    return commons


def street(p, mx, street_bottom, north_top, right, commons):
    """The street with the internet and the bus loop, and the field next to the gym."""
    internet = (mx - 380, TOP, mx + 480, street_bottom)
    p.floor(*internet, GREY)
    p.put("ISP", mx, TOP + 100)
    p.put("INET-SRV", mx + 300, TOP + 100)
    p.note(internet[0] + 14, TOP + 10, "THE INTERNET (simulated)\ntwo fibre lines come in\nunder the street")
    road = (internet[2] + 30, TOP + 40, right, street_bottom - 20)
    p.floor(*road, ROAD)
    for n in range(8):                                         # the line in the middle of the road
        p.extra(road[0] + 60 + 220 * n, TOP + 96, road[0] + 160 + 220 * n, TOP + 104, (255, 255, 255))
    for n in range(2):                                         # school buses in the bus loop
        bx = road[0] + 500 + 420 * n
        p.extra(bx, TOP + 118, bx + 230, TOP + 168, BUS)
        p.extra(bx + 14, TOP + 126, bx + 180, TOP + 144, (60, 70, 84))
    p.note(road[0] + 20, TOP + 46, "NE 104th St - bus loop")
    # the field next to the gym
    if right - commons[2] > 300:
        field = (commons[2] + 40, north_top - WALL, right, north_top + NORTH_H + WALL)
        p.floor(*field, GRASS)
        p.oval(field[0] + 30, field[1] + 60, field[2] - 30, field[3] - 60, TRACK)
        p.oval(field[0] + 80, field[1] + 110, field[2] - 80, field[3] - 110, GRASS)
        p.note(field[0] + 150, (field[1] + field[3]) // 2 - LINE, "track and\nfootball field")


def place_notes(p, c_box, right, bottom):
    """The long notes: the introduction top left, the rest in the two corners next to the C wing."""
    count = len(classrooms())
    numbers = {"students": 15 * count, "teachers": count, "rooms": count,
               "things": sum(1 for row in inventory() if row["type"] in pkticons.ICONS)}
    columns = {"top": (LEFT, TOP), "left": (LEFT, c_box[1] + 20), "right": (c_box[2] + GAP + 20, c_box[1] + 20)}
    p.big_notes = []
    for column, text in NOTES:
        x, y = columns[column]
        text = text.format(**numbers)
        p.big_notes.append((x, y, text))
        columns[column] = (x, y + LINE * len(text.split("\n")) + 44)
    p.notes += p.big_notes
    p.size = (max(right, c_box[2] + GAP + 1400) + LEFT, max(bottom, columns["left"][1], columns["right"][1]) + 60)


def plan():
    """Work out where everything goes. The school is a cross: the server room in the middle,
    the E wing to the left, the B wing to the right, the C wing below, and the main office,
    the front entrance, the cafeteria and the gym above, next to the street."""
    p = Plan()
    labels = room_labels()
    titles, colours = {}, {}
    for title, switch, colour, plugged, wing in rooms():
        titles[switch[3:]], colours[switch[3:]] = title, colour
    found = wings()

    def floors_of(wing):
        """(upstairs rooms, downstairs rooms)"""
        by_floor = found.get(wing, {})
        return ([room for floor in sorted(by_floor) if floor != "1" for room in by_floor[floor]],
                by_floor.get("1", []))

    def width_of(wing):
        columns = max(len(floors_of(wing)[0]), len(floors_of(wing)[1]), 1)
        return columns * ROOM_W + (columns - 1) * WALL

    street_bottom = TOP + 200
    north_top = street_bottom + 70 + WALL                     # top of the floors of the office
    main_top = north_top + NORTH_H + WALL + GAP + WALL        # top of the floors of the wings
    hall_top = main_top + ROOM_H + WALL
    middle_y = hall_top + HALL // 2
    main_bottom = hall_top + HALL + WALL + ROOM_H

    # ---- the E wing, left
    e_left = LEFT + WALL
    e_box = wing_across(p, "E", e_left, main_top, *floors_of("E"), titles, colours)

    # ---- the building in the middle: the server room (MDF) with the whole backbone, the
    # ---- servers and the IT office. Its hall lines up with the halls of the three wings.
    core_left = e_box[2] + GAP + WALL
    core_right = core_left + CORE_W
    mx = (core_left + core_right) // 2
    aisle = (mx - 320, hall_top + HALL + WALL, mx + 320, main_bottom)
    backbone = (core_left, main_top, core_right, hall_top + HALL)
    server_room = (core_left, aisle[1], aisle[0] - WALL, main_bottom)
    it_office = (aisle[2] + WALL, aisle[1], core_right, main_bottom)
    core_floors = [backbone + (CYAN,), server_room + (BLUE,), it_office + (PURPLE,), aisle + (FLOOR,),
                   (mx - 120, backbone[3], mx + 120, aisle[1], FLOOR),                       # door to the aisle
                   (core_left + 150, backbone[3], core_left + 250, aisle[1], FLOOR),         # door of the server room
                   (core_right - 250, backbone[3], core_right - 150, aisle[1], FLOOR),       # door of the IT office
                   (core_left - WALL, middle_y - 70, core_left, middle_y + 70, FLOOR),       # doors to the wings
                   (core_right, middle_y - 70, core_right + WALL, middle_y + 70, FLOOR),
                   (mx - 120, main_bottom, mx + 120, main_bottom + WALL, FLOOR),
                   (mx - 120, main_top - WALL, mx + 120, main_top, FLOOR)]                   # door to the front entrance
    p.floors += core_floors
    p.walls += [piece + (BRICK,) for piece in leftover((core_left - WALL, main_top - WALL, core_right + WALL,
                                                        main_bottom + WALL), core_floors)]
    p.areas["MDF"] = backbone
    p.put("RHS-EDGE1", mx - 150, main_top + 140)
    p.put("RHS-EDGE2", mx + 150, main_top + 140)
    p.put("CORE-L3-1", mx - 150, main_top + 440)
    p.put("CORE-L3-2", mx + 150, main_top + 440)
    p.put("DIST-L3-1", mx - 130, middle_y - 90)
    p.put("DIST-L3-2", mx + 130, middle_y + 90)
    p.note(core_left + 14, main_top + 10, "MDF - the server room\nevery cable of the school ends here")
    p.note(core_left + 14, main_top + 110, "EDGE (2911)\nNAT, to the ISP")
    p.note(core_left + 14, main_top + 410, "CORE (3650)\nOSPF routing only")
    p.note(core_left + 14, middle_y - 130, "DISTRIBUTION (3650)\ngateways, HSRP, ACLs")
    server_room_things(p, core_right, main_top, server_room, it_office, aisle)

    # ---- the B wing, right
    b_left = core_right + WALL + GAP + WALL
    b_box = wing_across(p, "B", b_left, main_top, *floors_of("B"), titles, colours, way_out="left")
    # walkways between the buildings
    p.floor(e_box[2], middle_y - 70, core_left - WALL, middle_y + 70, PATH)
    p.floor(core_right + WALL, middle_y - 70, b_box[0], middle_y + 70, PATH)

    # ---- the C wing, below
    c_top = main_bottom + WALL + GAP + WALL
    up, down = floors_of("C")
    c_box = wing_down(p, "C", mx, c_top, down, up, titles, colours)
    p.floor(mx - 120, main_bottom + WALL, mx + 120, c_box[1], PATH)

    # ---- wings that are not E, C or B (a room added later with another letter) go in a row under everything
    bottom = c_box[3]
    extra_x = LEFT + WALL
    extra_top = bottom + GAP + WALL
    for wing in found:
        if wing not in WINGS:
            box = wing_across(p, wing, extra_x, extra_top, *floors_of(wing), titles, colours)
            extra_x = box[2] + GAP + WALL
            bottom = max(bottom, box[3])

    # ---- above: main office, front entrance, cafeteria and gym
    office, entrance = office_and_entrance(p, mx, north_top)
    commons = cafeteria_and_gym(p, mx, north_top)

    # ---- the street with the internet
    right = max(b_box[2], commons[2])
    street(p, mx, street_bottom, north_top, right, commons)
    # trees and the flag at the front
    for n in range(4):
        tx = office[0] - 110 - 120 * n
        if tx > LEFT + 1150:
            p.oval(tx - 40, north_top + 520, tx + 40, north_top + 600, TREE)
    p.extra(entrance[2] - 70, north_top + 30, entrance[2] - 64, north_top + 150, BRICK)
    p.extra(entrance[2] - 64, north_top + 30, entrance[2] - 14, north_top + 64, (200, 60, 60))
    # the generator behind the server room keeps it running when the power is out
    p.extra(core_left + 60, main_bottom + WALL + 6, core_left + 260, main_bottom + WALL + GAP - 6, (250, 180, 60))
    p.note(core_left + 270, main_bottom + WALL + 8, "backup generator")

    # ---- the notes: the introduction top left, the rest in the two corners next to the C wing
    place_notes(p, c_box, right, bottom)
    p.labels = labels
    return p


# ---------------------------------------------------------------- the text on the canvas
# (column, text). Lines are kept under about 72 characters. "top" is the corner above the E
# wing, "left" and "right" are the corners next to the C wing. The notes of a column are put
# under each other. {students}, {teachers}, {rooms} and {things} are filled in from the inventory.

NOTES = [
    ("top", """RHS CAMPUS NETWORK - CCNA project (Packet Tracer 9.0)
My own design for part of a high school network, using {rooms} rooms
at Redmond High School. It is NOT the real RHS network, and the
building is made up too.

WHAT THIS LAB DOES
- connects {students} student PCs, {teachers} teacher PCs, 6 office PCs, 2 IT PCs,
  6 servers and {things} building things (smartboards, cameras, bells...)
- keeps students, teachers, office staff, IT and the building
  things apart in their own VLANs, with ACLs for who can reach what
- gives every PC and thing its address from one DHCP server
- takes everyone to the internet through NAT on two edge routers
- keeps working when any one router, layer 3 switch or uplink
  cable between a room and the internet fails
Three layers like the Cisco campus model: core, distribution, access."""),

    ("top", """HOW TO READ THE MAP
It is a floor plan. Dark lines are walls, grey floors are halls.
Upstairs rooms (2xx) are drawn next to the downstairs rooms (1xx)
of their wing so both floors fit on one sheet.
Orange boxes in the halls are wiring closets, one switch per room.
Every closet has two cables to the server room in the middle,
one to each distribution switch."""),

    ("left", """INTERNET (simulated)
ISP router with loopback 8.8.8.8 as a ping target.
INET-SRV is www.example.com (198.51.100.10).
Public addresses are from the documentation ranges."""),

    ("left", """EDGE ROUTERS (2911) - RHS-EDGE1 and RHS-EDGE2
Connect the school to the ISP. Two routers and two ISP links,
so one can fail. EDGE2 is the backup (default route metric 100).
ip nat inside source list 1 interface g0/0/0 overload (PAT)
ip nat inside source static (school website 203.0.113.10)
ip access-group OUTSIDE-IN in, default-information originate"""),

    ("left", """CORE LAYER (3650) - CORE-L3-1 and CORE-L3-2
Only routes between the edge and the distribution layer.
No user VLANs and no ACLs here, so it stays simple and fast.
ip routing, no switchport + ip address on each link
router ospf 1 (area 0), channel-group 1 mode active (LACP)"""),

    ("left", """DISTRIBUTION LAYER (3650) - DIST-L3-1 and DIST-L3-2
Default gateway of every VLAN. All rules between VLANs are here.
DIST-L3-1 is HSRP active + STP root for VLAN 10, 70, 99.
DIST-L3-2 is HSRP active + STP root for VLAN 20, 30, 40.
interface vlan + standby (gateway .1), ip helper-address
ip access-list extended + ip access-group in, router ospf 1"""),

    ("left", """ACCESS LAYER - one 2960 per room, office and MDF are 3650 as layer 2
Where everything plugs in. Fa0/1-15 students, Fa0/16 teacher,
Fa0/17 smartboard, after that cameras, bells and printers.
One trunk to each distribution switch (Gi0/1 and Gi0/2).
Spanning tree blocks one of them per VLAN, so there is no loop.
switchport mode access, switchport access vlan
switchport mode trunk, switchport trunk allowed vlan 10,20,40,99"""),

    ("left", """VLANS AND SUBNETS
10  STUDENTS     10.10.8.0/22     20  TEACHERS   10.10.20.0/24
30  MANAGEMENT   10.10.30.0/24    40  BUILDING   10.10.40.0/24
70  SERVERS      10.10.70.0/24    99  NETWORK-IT 10.10.99.0/24
998 unused ports, 999 native
Gateway is always .1 (HSRP), DIST-L3-1 is .2 and DIST-L3-2 is .3.
Links between routers are /30s from 10.10.0.0, OSPF single area 0."""),

    ("left", """SERVERS (VLAN 70, static addresses)
SRV-DHCP    10.10.70.5   DHCP for VLAN 10, 20, 30, 40
SRV-DNS-WEB 10.10.70.10  DNS + www.rhs.lab
SRV-LOG     10.10.70.20  syslog + NTP
SRV-FILE    10.10.70.30  FTP for staff
SRV-BACKUP  10.10.70.31  second copy of the staff files
SRV-CAMERAS 10.10.70.40  records the security cameras
IT-PC1 10.10.99.50, IT-PC2 10.10.99.51
Switch management: 10.10.99.11-40 rooms, .21 office, .22 MDF"""),

    ("left", """LOGINS (every router and switch, console included)
user admin / RHSadmin, enable secret RHSenable
SSH from IT-PC1 after typing: crypto key generate rsa (1024)"""),

    ("right", """WHO CAN REACH WHAT (ACLs on the distribution switches)
Students:    internet, the school website and DNS only
Teachers:    servers, students, building things, internet.
             Not management or IT
Management:  everything except the IT VLAN
Network IT:  everything, and the only VLAN that may SSH to devices
Building:    DNS, time, logs and the camera recorder. No internet
Servers:     may answer, may not start a connection into the school
Internet:    only the school web server, on port 80 and 443"""),

    ("right", """BUILDING THINGS (VLAN 40) - not computers, still on the network
A smartboard in every classroom, a camera and a bell speaker in
every hall, printers in the library and the office, badge readers
at the doors, the lunch registers and the vending machine in the
cafeteria, the scoreboard in the gym.
Packet Tracer has no such devices, so each one is a PC with its
own picture. They get an address by DHCP and answer ping.
A hacked camera or vending machine cannot reach a student PC,
a teacher PC or the internet: the ACL BUILDING-IN stops it."""),

    ("right", """REDUNDANCY - what takes over when something fails
ISP link 1 or RHS-EDGE1    -> RHS-EDGE2 (OSPF default route)
a core switch              -> the other core (OSPF)
a distribution switch      -> the other one (HSRP moves gateway .1)
an uplink of a room switch -> its other uplink (Rapid PVST+)
one cable of a bundle      -> the other cable (LACP EtherChannel)
the file server            -> SRV-BACKUP has a second copy
the power                  -> UPS battery, then the generator
EtherChannels: core to core, dist to dist, SW-MDF to each dist."""),

    ("right", """SECURITY ON THE ACCESS SWITCHES
PortFast + BPDU guard and sticky port security (max 2 MACs)
DHCP snooping, only the uplinks may answer DHCP
unused ports are shut down and parked in VLAN 998
native VLAN 999 is empty, trunks do not negotiate
SSH version 2 only, and only from the IT VLAN (access-class 10)"""),

    ("right", """THINGS TO TRY (wait a minute after opening for green links)
E230-PC01: ipconfig -> 10.10.8.x, gateway 10.10.8.1
E230-PC01: ping C214-PC01 works, ping a teacher PC fails
E230-PC01: browser www.rhs.lab works, ftp 10.10.70.30 fails
E230-PC01: ping 8.8.8.8 works (NAT on the edge)
E230-TCHR: ping the address of E230-BOARD works
E230-BOARD: ipconfig -> 10.10.40.x, ping 8.8.8.8 fails (no internet)
IT-PC1: ping anything, ssh -l admin 10.10.99.11
DIST-L3-1: show standby brief, show etherchannel summary
Break it: shutdown g0/0/0 on RHS-EDGE1 while a ping -t runs"""),

    ("right", """HOW A PACKET GETS OUT (E230-PC01 opens www.example.com)
1. PC asks SRV-DHCP for an address. DIST relays it (ip helper-address)
2. PC sends to its gateway 10.10.8.1, the HSRP address on DIST-L3-1
3. ACL STUDENTS-IN on interface Vlan10 checks it: internet is allowed
4. DIST routes it to a core switch, the core to an edge router (OSPF)
5. RHS-EDGE1 swaps the 10.x address for its public one (PAT) and
   sends it to the ISP. The answer comes back the same way.
Watch it hop by hop in Simulation mode (bottom right corner)."""),

    ("right", """MORE IN THE PROJECT FOLDER
README.md explains every design choice, WALKTHROUGH.md builds it
step by step. configs/ has the config of every device with comments.
tools/ has the Python programs that check the addressing plan and
write config changes straight into this file.

CHANGE CONFIGS WITH BUTTONS (NetCheck)
Packet Tracer cannot start other programs, so this is not a real button.
1. Save and close this lab.   2. Double click "Start NetCheck.command"
(in the tools folder). The page opens at http://127.0.0.1:8765
3. Make the change there, then press "Open in Packet Tracer" on the page."""),
]


def positions():
    """{device name: (x, y)} for every device the layout knows."""
    return plan().where


def boxes():
    """(left, top, right, bottom, colour) of every rectangle, in the order they are drawn:
    floors and walls first (they never overlap), then the small things that stand on a floor."""
    p = plan()
    return p.floors + p.walls + p.extras


def big_notes():
    """The notes with the long texts, with the numbers filled in."""
    return plan().big_notes


def notes():
    """(x, y, text) of every note on the canvas."""
    return plan().notes


# ---------------------------------------------------------------- writing it into the file

def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shape_xml(kind, number, box, outlined=False):
    """A RECTANGLE or an ELLIPSE."""
    left, top, right, bottom, (red, green, blue) = box
    cluster = "RECTCLUSTERID" if kind == "RECTANGLE" else "ELLIPSECLUSTERID"
    # Packet Tracer saves the bottom right corner under the name TopLeft and the other way round
    return f"""<{kind} uuid="{{{uuid.uuid4()}}}">
    <TopLeftX>{right}</TopLeftX>
    <TopLeftY>{bottom}</TopLeftY>
    <BottomRightX>{left}</BottomRightX>
    <BottomRightY>{top}</BottomRightY>
    <Color>
     <Red>{red}</Red>
     <Green>{green}</Green>
     <Blue>{blue}</Blue>
    </Color>
    <Filled OUTLINECOLOR="#000000" OUTLINED="{'true' if outlined else 'false'}">1</Filled>
    <{cluster}>1-1</{cluster}>
    <MEM_ADDR>{140200000000000 + number * 4096}</MEM_ADDR>
    <DevicePlacement_ShapeName />
    <DevicePlacement_ShapeX>{(left + right) / 2:.1f}</DevicePlacement_ShapeX>
    <DevicePlacement_ShapeY>{(top + bottom) / 2:.1f}</DevicePlacement_ShapeY>
    <DevicePlacement_ShapeZ>0.21</DevicePlacement_ShapeZ>
   </{kind}>"""


def icon_path(kind):
    """The name a picture has inside the lab file. It only has to be the same in the list of
    pictures and on the device, there is no such file on the disk."""
    return f"C:/rhs-lab/{kind}.png"


def pictures_xml():
    """The pictures of pkticons.py, the way Packet Tracer keeps pictures inside a .pkt file."""
    images = "".join(f"""
  <IMAGE>
   <IMAGE_PATH>{icon_path(kind)}</IMAGE_PATH>
   <IMAGE_CONTENT>{base64.b64encode(pkticons.png(kind)).decode()}</IMAGE_CONTENT>
  </IMAGE>""" for kind in pkticons.ICONS)
    return f"<PIXMAPBANK>{images}\n </PIXMAPBANK>"


def note_xml(number, note):
    x, y, text = note
    return f"""<NOTE uuid="{{{uuid.uuid4()}}}">
     <X>{x}</X>
     <Y>{y}</Y>
     <Z>{40000 + 3 * number}</Z>
     <TEXT translate="true">{escape(text)}</TEXT>
     <NOTECLUSTERID>1-1</NOTECLUSTERID>
     <MEM_ADDR>{140210000000000 + number * 4096}</MEM_ADDR>
    </NOTE>"""


def description_html():
    """The same text as the notes, for the lab description window."""
    paragraph = '<p style=" margin-top:0px; margin-bottom:8px; margin-left:0px; margin-right:0px; ' \
                '-qt-block-indent:0; text-indent:0px;">'
    body = ""
    for x, y, text in big_notes():
        title, _, rest = text.partition("\n")
        body += f'{paragraph}<span style=" font-weight:700;">{escape(title)}</span><br />' + \
                escape(rest).replace("\n", "<br />") + "</p>\n"
    return ('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">\n'
            '<html><head><meta name="qrichtext" content="1" /><meta charset="utf-8" /><style type="text/css">\n'
            'p, li { white-space: pre-wrap; }\n</style></head>'
            '<body style=" font-family:\'Verdana\'; font-size:11pt; font-weight:400; font-style:normal;">\n'
            + body + '</body></html>')


def replace_once(xml, pattern, new_text, what):
    """Swap the one place in the file that matches, or stop if the file looks different."""
    result, count = re.subn(pattern, lambda match: new_text, xml, count=1, flags=re.S)
    if count != 1:
        raise Problem(f"Cannot find the {what} in the lab file, nothing was changed.")
    return result


def arrange(lab_path=LAB, write=True, backup=True):
    """Returns the lines of a short report. backup=False when the caller already kept a copy."""
    try:
        xml = pktfile.read_pkt(lab_path).decode("utf-8")
    except FileNotFoundError:
        raise Problem(f"Lab file not found: {lab_path}")
    except (ValueError, OSError) as err:
        raise Problem(f"Cannot read {os.path.basename(lab_path)}: {err}")

    drawn = plan()
    where = drawn.where
    kinds = {row["name"]: row["type"] for row in inventory()}
    report = []
    seen = set()

    def move(match):
        device = match.group(0)
        name = html.unescape(re.search(r"<NAME[^>]*>([^<]*)</NAME>", device).group(1))
        spot = re.search(r"(<LOGICAL>\s*<X>)([^<]*)(</X>\s*<Y>)([^<]*)(</Y>)", device)
        if name not in where or not spot:
            report.append(f"{name} is not in the layout, it stays where it is.")
            return device
        seen.add(name)
        x, y = where[name]
        if (round(float(spot.group(2))), round(float(spot.group(4)))) != (x, y):
            report.append(f"{name:<18} {spot.group(2):>5},{spot.group(4):<5} -> {x},{y}")
        device = device[:spot.start()] + f"{spot.group(1)}{x}{spot.group(3)}{y}{spot.group(5)}" + device[spot.end():]
        # a thing that is not a computer gets its own picture
        picture = icon_path(kinds[name]) if kinds.get(name) in pkticons.ICONS else ""
        return re.sub(r"<CUSTOM_IMAGE_LOGICAL>[^<]*</CUSTOM_IMAGE_LOGICAL>|<CUSTOM_IMAGE_LOGICAL />",
                      f"<CUSTOM_IMAGE_LOGICAL>{picture}</CUSTOM_IMAGE_LOGICAL>" if picture else "<CUSTOM_IMAGE_LOGICAL />",
                      device, count=1)

    xml = re.sub(r"<DEVICE>.*?</DEVICE>", move, xml, flags=re.S)
    moved = len(report)
    for name in sorted(set(where) - seen):
        report.append(f"{name} is in the layout but not in the lab.")

    all_boxes = "\n   ".join(shape_xml("RECTANGLE", i, b) for i, b in enumerate(boxes()))
    all_ovals = "\n   ".join(shape_xml("ELLIPSE", 5000 + i, b) for i, b in enumerate(drawn.ovals))
    all_notes = "\n    ".join(note_xml(i, n) for i, n in enumerate(drawn.notes))
    xml = replace_once(xml, r"\n <RECTANGLES>.*?</RECTANGLES>|\n <RECTANGLES />",
                       f"\n <RECTANGLES>\n   {all_boxes}\n  </RECTANGLES>", "coloured boxes")
    xml = replace_once(xml, r"\n <ELLIPSES>.*?</ELLIPSES>|\n <ELLIPSES />",
                       f"\n <ELLIPSES>\n   {all_ovals}\n  </ELLIPSES>", "round shapes")
    xml = replace_once(xml, r"<PIXMAPBANK>.*?</PIXMAPBANK>|<PIXMAPBANK />", pictures_xml(), "list of pictures")
    xml = replace_once(xml, r"(?<=</GRID_COLOR>)(\s*)(?:<NOTES>.*?</NOTES>|<NOTES />)",
                       f"\n   <NOTES>\n    {all_notes}\n    </NOTES>", "canvas notes")
    xml = replace_once(xml, r"(?<=<SHAPETESTS />)(\s*)<DESCRIPTION translate=\"true\">.*?</DESCRIPTION>",
                       f'\n   <DESCRIPTION translate="true">{escape(description_html())}</DESCRIPTION>',
                       "lab description")
    report.append(f"{moved} device(s) moved, {len(boxes())} boxes, {len(drawn.ovals)} round shapes, "
                  f"{len(drawn.notes)} notes, {len(pkticons.ICONS)} pictures, description written.")

    if write:
        kept = backup_lab(lab_path) if backup else None
        pktfile.write_pkt(lab_path + ".tmp", xml.encode("utf-8"))
        os.replace(lab_path + ".tmp", lab_path)
        report.append(f"Written to {os.path.basename(lab_path)}." +
                      (f" The file from before is in changes/backups/{kept}" if kept else ""))
        if packet_tracer_is_open():
            report.append("Note: Packet Tracer is running. If this lab is open in it, close the lab WITHOUT "
                          "saving and open it again.")
    else:
        report.append("Dry run, nothing was written.")
    return report


def main(args):
    lab_path = LAB
    if "--lab" in args:
        at = args.index("--lab")
        if at + 1 >= len(args):
            print("--lab needs a file name")
            return 2
        lab_path = args[at + 1]
        args = args[:at] + args[at + 2:]
    if args not in ([], ["--dry-run"]):
        print(__doc__)
        return 2
    try:
        print("\n".join(arrange(lab_path, write=not args)))
    except Problem as err:
        print("Problem:", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

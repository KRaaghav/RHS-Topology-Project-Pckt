#!/usr/bin/env python3
"""
diagram.py - draw the topology of the lab as a picture (SVG)

  python3 diagram.py              writes ../topology.svg

The picture is made from the cables and configs inside the .pkt file and from plan.csv,
so it is never out of date: add a room with pktbuild.py, run this again, and the room is
on it. The Overview tab of netcheck_ui.py shows the same picture.

Only uses the Python standard library, nothing to install.
"""

import html
import os
import sys

import labtest
import pktlayout
from pktconfig import HERE, LAB, Problem

OUT = os.path.join(HERE, "..", "topology.svg")
WIDTH = 1620
ROWS = [("Internet", 60, ["ISP", "INET-SRV"]),
        ("Edge (2911)\nNAT, default route", 160, ["RHS-EDGE1", "RHS-EDGE2"]),
        ("Core (3650)\nOSPF routing only", 260, ["CORE-L3-1", "CORE-L3-2"]),
        ("Distribution (3650)\ngateways, HSRP, ACLs", 360, ["DIST-L3-1", "DIST-L3-2"])]
ACCESS_Y = 500
COLOURS = {"Internet": "#e8e8e8", "Edge": "#ffd8d8", "Core": "#e4daff", "Distribution": "#d0e2ff",
           "room": "#ffffb0", "office": "#d0f8d0", "mdf": "#b8f8f8"}
VLAN_COLOURS = {"10": "#f2c94c", "20": "#f2994a", "30": "#6fcf97", "40": "#eb5757", "70": "#56ccf2", "99": "#bb6bd9"}


def text(x, y, words, size=12, weight="400", anchor="middle", colour="#18212b"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'fill="{colour}">{html.escape(words)}</text>')


def node(name, x, y, colour, width=112):
    return (f'<g class="node" data-name="{html.escape(name)}"><rect x="{x - width / 2}" y="{y - 17}" width="{width}" '
            f'height="34" rx="7" fill="{colour}" stroke="#18212b" stroke-width="1.2"/>'
            + text(x, y + 4.5, name, 12, "600") + "</g>")


def svg(lab_path=LAB):
    """The whole picture as SVG text."""
    p = labtest.Picture(lab_path)
    plan = labtest.read_csv("plan.csv")
    vlan_name = {row["vlan"]: row["name"] for row in plan if row["vlan"]}
    middle = WIDTH / 2 + 60
    where = {}
    parts = []

    # the layers
    for title, y, names in ROWS:
        colour = COLOURS[title.split()[0]]
        parts.append(f'<rect x="150" y="{y - 34}" width="{WIDTH - 170}" height="68" rx="10" fill="{colour}" opacity="0.45"/>')
        for i, line in enumerate(title.split("\n")):
            parts.append(text(20, y - 4 + 16 * i, line, 12 if i == 0 else 10.5, "700" if i == 0 else "400", "start",
                              "#18212b" if i == 0 else "#5f6c7a"))
        if title == "Internet":
            where["ISP"], where["INET-SRV"] = (middle, y), (middle + 220, y)
        else:
            where[names[0]], where[names[1]] = (middle - 170, y), (middle + 170, y)

    # the access switches in one row, each with what is plugged into it
    layout = pktlayout.rooms()
    order = [room[1] for room in layout]
    access = sorted(p.access, key=lambda name: order.index(name) if name in order else len(order))
    labels = pktlayout.room_labels()
    step = (WIDTH - 170) / len(access)
    parts.append(text(20, ACCESS_Y - 4, "Access", 12, "700", "start"))
    parts.append(text(20, ACCESS_Y + 12, "one switch per room", 10.5, "400", "start", "#5f6c7a"))
    boxes = []
    wing_span = {}
    for i, switch in enumerate(access):
        x = 150 + step * (i + 0.5)
        where[switch] = (x, ACCESS_Y)
        counts = {}
        ports = p.ports(switch)
        for port, (other, other_port) in p.cabled(switch).items():
            if other in p.hosts:
                vlan = labtest.value_after(ports.get(port, []), "switchport access vlan ") or "?"
                counts[vlan] = counts.get(vlan, 0) + 1
        kind = "office" if switch == "SW-OFFICE" else "mdf" if switch == "SW-MDF" else "room"
        room = switch[3:]
        if kind == "room":
            wing_span.setdefault(room[0], []).append(x)
        about = {"office": "Main office", "mdf": "Server room, IT"}.get(kind) or labels.get(room) or f"floor {room[1]}"
        boxes.append(text(x, ACCESS_Y + 36, about, 10.5, "600"))
        height = 48 + 17 * len(counts)
        boxes.append(f'<rect x="{x - step / 2 + 5}" y="{ACCESS_Y - 30}" width="{step - 10}" height="{height + 34}" rx="9" '
                     f'fill="{COLOURS[kind]}" opacity="0.6"/>')
        for row, vlan in enumerate(sorted(counts, key=int)):
            y = ACCESS_Y + 58 + 17 * row
            boxes.append(f'<circle cx="{x - step / 2 + 18}" cy="{y - 4}" r="4.5" fill="{VLAN_COLOURS.get(vlan, "#999")}"/>')
            what = "servers" if vlan == "70" else "things" if vlan == "40" and counts[vlan] != 1 else \
                "thing" if vlan == "40" else "PCs" if counts[vlan] != 1 else "PC"
            boxes.append(text(x - step / 2 + 27, y, f"{counts[vlan]} {what} VLAN {vlan}", 9.5, "400", "start"))

    for wing, xs in wing_span.items():
        y = ACCESS_Y + 132
        boxes.append(f'<line x1="{xs[0] - step / 2 + 8:.0f}" y1="{y}" x2="{xs[-1] + step / 2 - 8:.0f}" y2="{y}" stroke="#b8862b" stroke-width="3"/>')
        boxes.append(text((xs[0] + xs[-1]) / 2, y + 18, f"{wing} wing", 12, "700"))

    # the cables between routers and switches. Two cables between the same pair are an EtherChannel
    pairs = {}
    for a, a_port, b, b_port in p.links:
        if a in where and b in where:
            pairs[tuple(sorted((a, b)))] = pairs.get(tuple(sorted((a, b))), 0) + 1
    lines = []
    for (a, b), count in sorted(pairs.items()):
        (x1, y1), (x2, y2) = where[a], where[b]
        lines.append(f'<line x1="{x1:.0f}" y1="{y1}" x2="{x2:.0f}" y2="{y2}" stroke="#44515e" '
                     f'stroke-width="{1.1 if count == 1 else 3.2}" opacity="{0.55 if count == 1 else 0.9}"/>')
        if count > 1:
            lines.append(text((x1 + x2) / 2, (y1 + y2) / 2 - 6, f"LACP x{count}", 9.5, "600", "middle", "#44515e"))

    nodes = []
    for title, y, names in ROWS:
        for name in names:
            nodes.append(node(name, *where[name], "#ffffff"))
    for switch in access:
        nodes.append(node(switch, *where[switch], "#ffffff", min(104, step - 14)))

    # the VLAN and subnet table
    top = ACCESS_Y + 200
    table = [text(150, top, "VLANs and subnets", 13, "700", "start")]
    column = [150, 190, 330, 480, 620]
    for x, title in zip(column, ["", "VLAN", "Name", "Subnet", "Gateway (HSRP)"]):
        table.append(text(x, top + 22, title, 10.5, "600", "start", "#5f6c7a"))
    row = 0
    for entry in plan:
        if entry["vlan"] and entry["gateway"]:
            y = top + 42 + 19 * row
            table.append(f'<circle cx="162" cy="{y - 4}" r="5" fill="{VLAN_COLOURS.get(entry["vlan"], "#999")}"/>')
            for x, words in zip(column[1:], [entry["vlan"], entry["name"], entry["network"], entry["gateway"]]):
                table.append(text(x, y, words, 11.5, "400", "start"))
            row += 1
    notes = ["Router to router links: /30 subnets from 10.10.0.0, OSPF area 0",
             "Loopbacks (router IDs): 10.10.255.0/24",
             "ISP links: 203.0.113.0/30 and 203.0.113.4/30, public 203.0.113.8/29",
             "Thin line: one cable. Thick line: EtherChannel (LACP).",
             f"{len(p.devices)} devices, {len(p.hosts)} PCs and servers, {len(p.links)} cables"]
    for i, words in enumerate(notes):
        table.append(text(800, top + 22 + 19 * i, words, 11.5, "400", "start", "#18212b" if i < 3 else "#5f6c7a"))

    height = top + 60 + 19 * max(row, len(notes))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
            f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">\n'
            f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>\n'
            + text(20, 24, "RHS campus network", 15, "700", "start") + "\n"
            + "\n".join(parts + boxes + lines + nodes + table) + "\n</svg>\n")


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
    print("Written to topology.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

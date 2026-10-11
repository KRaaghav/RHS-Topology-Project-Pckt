#!/usr/bin/env python3
"""
pktbuild.py - add a whole classroom to the Packet Tracer lab

  python3 pktbuild.py add-room B128              add room B128 to the lab
  python3 pktbuild.py add-room B128 --dry-run    only say what would happen
  python3 pktbuild.py add-room C114 Library      a room with a name, shown on the canvas and the plans

A new room is a copy of the last classroom: one 2960 switch, 15 student PCs, a teacher
PC and all the cables, with two uplinks to the next free port on DIST-L3-1 and DIST-L3-2.
The program does everything a new room needs:

  - copies the devices and cables inside the .pkt file (new names, new MAC addresses)
  - gives the switch the next free management address in 10.10.99.0/24
  - turns the port on both distribution switches into a trunk for the room
  - writes configs/SW-<room>.txt and updates the two DIST files
  - adds the devices to inventory.csv
  - runs pktlayout.py so the new room gets its place and box on the canvas

Close the lab in Packet Tracer first. The lab from before is kept in ../changes/backups.

Only uses the Python standard library, nothing to install.
"""

import csv
import os
import random
import re
import sys
import uuid

import pktconfig
import pktlayout
from pktconfig import CONFIGS, HERE, LAB, Problem

INVENTORY = os.path.join(HERE, "inventory.csv")
# kept for classroom switches (.21 and .22 are the office and the MDF)
MGMT_ADDRESSES = [f"10.10.99.{n}" for n in list(range(11, 21)) + list(range(23, 41))]
DISTS = ["DIST-L3-1", "DIST-L3-2"]


# ---------------------------------------------------------------- small helpers

def devices_of(xml):
    """{name: the <DEVICE> block} for every device in the lab, PCs included."""
    found = {}
    for block in re.findall(r"<DEVICE>.*?</DEVICE>", xml, re.S):
        found[re.search(r"<NAME[^>]*>([^<]*)</NAME>", block).group(1)] = block
    return found


def ref_of(block):
    """The number the cables use to point at a device."""
    return re.search(r"save-ref-id:\d+", block).group(0)


def new_number(xml, digits, used):
    """A random number that is not in the file yet."""
    while True:
        number = str(random.randrange(10 ** (digits - 1), 10 ** digits))
        if number not in xml and number not in used:
            used.add(number)
            return number


def link_local(mac):
    """The IPv6 link local address a port makes from its MAC address (EUI-64)."""
    digits = mac.replace(".", "")
    first = int(digits[:2], 16) ^ 2
    groups = [f"{first:02X}{digits[2:4]}", digits[4:6] + "FF", "FE" + digits[6:8], digits[8:]]
    return "FE80::" + ":".join(g.lstrip("0") or "0" for g in groups)


def inventory_rows():
    with open(INVENTORY, newline="") as f:
        return list(csv.DictReader(f))


def free_dist_port(lab):
    """The lowest port that is shut down and parked in VLAN 998 on both distribution switches."""
    free = None
    for dist in DISTS:
        ports = set()
        lines = lab.config(dist)
        for i, line in enumerate(lines):
            match = re.fullmatch(r"interface GigabitEthernet1/0/(\d+)", line)
            if match:
                section = lines[i + 1:pktconfig.section_end(lines, i)]
                if " shutdown" in section and " switchport access vlan 998" in section:
                    ports.add(int(match.group(1)))
        free = ports if free is None else free & ports
    if not free:
        raise Problem("There is no port left that is free on both distribution switches.")
    return f"Gi1/0/{min(free)}"


# ---------------------------------------------------------------- copying inside the lab file

def copy_device(xml, block, old_room, new_room, used, new_lines):
    """Returns (the new <DEVICE> block, its physical view node, {old number: new number}).
    new_lines changes one config line (only the switch needs it)."""
    numbers = {}

    # the number cables point at, and the two memory addresses Packet Tracer saved
    old_ref = ref_of(block)
    numbers[old_ref] = "save-ref-id:" + new_number(xml, 19, used)
    for address in set(re.findall(r"<(?:MEM_ADDR|DEV_ADDR)>(\d+)<", block)):
        numbers[address] = new_number(xml, 15, used)

    # every port gets a new MAC address from the same maker
    for mac in sorted(set(re.findall(r"\b[0-9A-F]{4}\.[0-9A-F]{4}\.[0-9A-F]{4}\b", block))):
        while True:
            new_mac = mac[:7] + f"{random.randrange(16 ** 6):06X}"
            new_mac = new_mac[:9] + "." + new_mac[9:]
            if new_mac not in xml and new_mac not in used:
                used.add(new_mac)
                break
        numbers[mac] = new_mac
        numbers[link_local(mac)] = link_local(new_mac)

    # the place in the physical view: the last part of the path is the device itself
    path = re.search(r"<PHYSICAL>([^<]*)</PHYSICAL>", block).group(1).split(",")
    old_node = path[-1]
    numbers[old_node] = "{" + str(uuid.uuid4()) + "}"
    original = re.search(r"<ORIGINAL_DEVICE_UUID>([^<]*)<", block)
    if original:
        numbers[original.group(1)] = "{" + str(uuid.uuid4()) + "}"

    new_block = block
    for old, new in numbers.items():
        new_block = new_block.replace(old, new)

    # its icon in the physical view goes next to the one it is copied from: a room is
    # 16 icons of 7 wide, the switches sit 4 apart in the rack
    step = 4 if "<RUNNINGCONFIG>" in block else 112

    def shift(match):
        return match.group(1) + str(int(match.group(2)) + step) + match.group(3)
    new_block = re.sub(r"(<PHYSICAL_CPUR>.*?<X>)(\d+)(</X>)", shift, new_block, count=1, flags=re.S)

    # the name, and the room number in the config lines
    def rename(match):
        return match.group(1) + new_lines(match.group(2).replace(old_room, new_room)) + match.group(3)
    new_block = re.sub(r"(<(?:NAME|SYS_NAME|LINE)[^>]*>)([^<]*)(</)", rename, new_block)

    node = re.search(r"<NODE>(?:(?!<NODE>).)*?" + re.escape(old_node) + r".*?</NODE>", xml, re.S)
    if not node:
        raise Problem("Cannot find the room in the physical view, nothing was changed.")
    new_node = node.group(0).replace(old_node, numbers[old_node])
    new_node = re.sub(r"(<X>)(\d+)(</X>)", shift, new_node, count=1)
    new_node = re.sub(r"(<NAME[^>]*>)([^<]*)(</NAME>)",
                      lambda m: m.group(1) + m.group(2).replace(old_room, new_room) + m.group(3), new_node)
    return new_block, (node.group(0), new_node), numbers


def copy_link(link, numbers, old_port, new_port, xml, used):
    """A cable of the old room, changed to join the same ports of the new room."""
    def end(match):
        device, port = match.group(2), match.group(4)
        if device not in numbers and port == pktconfig.full_interface(old_port):
            port = pktconfig.full_interface(new_port)              # the end on a distribution switch
        return match.group(1) + numbers.get(device, device) + match.group(3) + port + match.group(5)
    link = re.sub(r"(<(?:FROM|TO)>)([^<]*)(</(?:FROM|TO)>\s*<PORT>)([^<]*)(</PORT>)", end, link)
    link = re.sub(r"(<(?:FROM|TO)_DEVICE_MEM_ADDR>)(\d+)", lambda m: m.group(1) + numbers.get(m.group(2), m.group(2)), link)
    return re.sub(r"(<(?:FROM|TO)_PORT_MEM_ADDR>)\d+", lambda m: m.group(1) + new_number(xml, 15, used), link)


def copy_room(xml, old_room, new_room, old_port, new_port, new_address):
    """The lab XML with a copy of old_room added as new_room. Returns (xml, names of the new devices)."""
    devices = devices_of(xml)
    names = ["SW-" + old_room] + [f"{old_room}-PC{n:02d}" for n in range(1, 16)] + [old_room + "-TCHR"]
    missing = [n for n in names if n not in devices]
    if missing:
        raise Problem(f"Room {old_room} is not complete in the lab ({missing[0]} is missing).")
    old_address = next((m.group(1) for l in re.findall(r"<LINE>(.*?)</LINE>", devices["SW-" + old_room])
                        for m in [re.match(r" ip address (10\.10\.99\.\d+) ", l)] if m), None)

    def switch_line(line):
        line = re.sub(rf"(Trunk to DIST-L3-\d ){re.escape(old_port)}\b", rf"\g<1>{new_port}", line)
        return line.replace(f"ip address {old_address} ", f"ip address {new_address} ") if old_address else line

    used = set()
    numbers = {}
    blocks = []
    nodes = []
    for name in names:
        block, node, changed = copy_device(xml, devices[name], old_room, new_room, used,
                                           switch_line if name.startswith("SW-") else lambda line: line)
        blocks.append(block)
        nodes.append(node)
        numbers.update(changed)

    old_refs = {ref_of(devices[name]) for name in names}
    links = [copy_link(link, numbers, old_port, new_port, xml, used)
             for link in re.findall(r"<LINK>.*?</LINK>", xml, re.S)
             if old_refs & set(re.findall(r"save-ref-id:\d+", link))]

    # put everything in: devices after the last device, cables after the last cable,
    # every physical view icon right after the one it was copied from
    for old_node, new_node in nodes:
        xml = xml.replace(old_node, old_node + "\n" + new_node, 1)
    last = xml.rindex("</DEVICE>") + len("</DEVICE>")
    xml = xml[:last] + "\n    " + "\n    ".join(blocks) + xml[last:]
    last = xml.rindex("</LINK>") + len("</LINK>")
    xml = xml[:last] + "\n    " + "\n    ".join(links) + xml[last:]
    return xml, [name.replace(old_room, new_room) for name in names]


# ---------------------------------------------------------------- the files around the lab

def room_trunk(lines, old_room, new_room, old_port, new_port):
    """Config lines of a distribution switch with the free port set up like the port of
    the old room. Works on the lab config and on the files in configs/."""
    lines = list(lines)
    old = lines.index("interface " + pktconfig.full_interface(old_port))
    new = lines.index("interface " + pktconfig.full_interface(new_port))
    section = [l.replace(old_room, new_room) for l in lines[old + 1:pktconfig.section_end(lines, old)]]
    lines[new + 1:pktconfig.section_end(lines, new)] = section
    return lines


def write_config_file(old_room, new_room, old_port, new_port, old_address, new_address):
    """configs/SW-<new room>.txt: the file of the old room with the three things that differ."""
    with open(os.path.join(CONFIGS, f"SW-{old_room}.txt")) as f:
        text = f.read()
    text = text.replace(old_room, new_room)
    text = re.sub(rf"(DIST-L3-\d ){re.escape(old_port)}\b", rf"\g<1>{new_port}", text)
    text = text.replace(f"ip address {old_address} ", f"ip address {new_address} ")
    with open(os.path.join(CONFIGS, f"SW-{new_room}.txt"), "w") as f:
        f.write(text)


def add_to_inventory(room, address, label=""):
    """The switch goes after the other room switches, the PCs after the other room PCs.
    A label like Library is kept in the location of the switch: Room C114 (Library)."""
    with open(INVENTORY) as f:
        lines = f.read().splitlines()
    last_switch = max(i for i, l in enumerate(lines) if ",switch 2960," in l)
    place = f"Room {room} ({label})" if label else f"Room {room}"
    lines.insert(last_switch + 1, f"SW-{room},switch 2960,{place},NETWORK-IT,{address}")
    last_pc = max(i for i, l in enumerate(lines) if ",STUDENTS,dhcp" in l)
    pcs = [f"{room}-TCHR,PC,Room {room},TEACHERS,dhcp"] + \
          [f"{room}-PC{n:02d},PC,Room {room},STUDENTS,dhcp" for n in range(1, 16)]
    lines[last_pc + 1:last_pc + 1] = pcs
    with open(INVENTORY, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- adding a room

def add_room(room, lab_path=LAB, write=True, label=""):
    """Returns the lines of a short report."""
    room = room.strip().upper()
    label = label.strip()
    if not re.fullmatch(r"[A-Za-z0-9 ]{0,24}", label):
        raise Problem("The name of a room is letters, digits and spaces only (24 at most).")
    if not re.fullmatch(r"[A-Z]\d{3}", room):
        raise Problem("A room number is a letter and three digits, like B128.")
    rows = inventory_rows()
    if any(row["name"] == "SW-" + room for row in rows):
        raise Problem(f"Room {room} is already in the lab.")
    taken = {row["ip"] for row in rows}
    address = next((a for a in MGMT_ADDRESSES if a not in taken), None)
    if address is None:
        raise Problem("All management addresses kept for classroom switches are used.")
    old_room = pktlayout.classrooms()[-1]

    lab = pktconfig.Lab(lab_path)
    new_port = free_dist_port(lab)
    old_switch = lab.config("SW-" + old_room)
    old_port = next(m.group(1) for l in old_switch for m in [re.search(r"Trunk to DIST-L3-1 (\S+)", l)] if m)
    old_address = next(m.group(1) for l in old_switch for m in [re.match(r" ip address (10\.10\.99\.\d+) ", l)] if m)

    xml, names = copy_room(lab.xml(), old_room, room, old_port, new_port, address)
    lab.use(xml)
    for dist in DISTS:
        lab.set_config(dist, room_trunk(lab.config(dist), old_room, room, old_port, new_port))

    report = [f"Room {room}: {names[0]} ({address}), 15 student PCs and {names[-1]}, copied from room {old_room}.",
              f"Uplinks: Gi0/1 to DIST-L3-1 {new_port}, Gi0/2 to DIST-L3-2 {new_port}."]
    if not write:
        return report + ["Dry run, nothing was written."]

    real_lab = os.path.abspath(lab_path) == os.path.abspath(LAB)
    backup = pktconfig.backup_lab(lab_path) if real_lab else None     # a copy of a copy is not needed
    lab.save()
    if real_lab:
        write_config_file(old_room, room, old_port, new_port, old_address, address)
        for dist in DISTS:
            path = os.path.join(CONFIGS, dist + ".txt")
            with open(path) as f:
                lines = room_trunk(f.read().splitlines(), old_room, room, old_port, new_port)
            with open(path, "w") as f:
                f.write("\n".join(lines) + "\n")
        add_to_inventory(room, address, label)
        pktlayout.arrange(lab_path, backup=False)
    report.append(f"Written to {os.path.basename(lab_path)}." +
                  (f" The lab from before is in changes/backups/{backup}" if backup else ""))
    if pktconfig.packet_tracer_is_open():
        report.append("Note: Packet Tracer is running. If this lab is open in it, close the lab WITHOUT "
                      "saving and open it again.")
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
    write = "--dry-run" not in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) < 2 or args[0] != "add-room":
        print(__doc__)
        return 2
    try:
        print("\n".join(add_room(args[1], lab_path, write, " ".join(args[2:]))))
    except Problem as err:
        print("Problem:", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

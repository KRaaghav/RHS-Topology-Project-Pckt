#!/usr/bin/env python3
"""
pktbuild.py - add a whole classroom to the Packet Tracer lab

  python3 pktbuild.py add-room B128              add room B128 to the lab
  python3 pktbuild.py add-room B128 --dry-run    only say what would happen
  python3 pktbuild.py add-room C114 Library      a room with a name, shown on the canvas and the plans
  python3 pktbuild.py add-thing CAM-GYM camera SW-A100 Gym
                                                 plug one more thing into a switch (see THINGS below)

A new room is a copy of the last classroom: one 2960 switch, 15 student PCs, a teacher
PC, the smartboard and all the cables, with two uplinks to the next free port on DIST-L3-1
and DIST-L3-2. A thing is something on the network that is not a computer somebody sits
at: a smartboard, printer, camera, bell... It goes on the next free port of the switch, in
VLAN 40 BUILDING.
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

# The things a school has on its network besides computers: kind -> what the port description says.
# Packet Tracer has no smartboard or bell, so in the lab every thing is a PC with its own
# picture (pkticons.py draws them). It gets an address by DHCP and answers ping like the real one.
THINGS = {"smartboard": "smartboard", "printer": "printer", "camera": "security camera",
          "bell": "bell and intercom speaker", "door": "badge reader of the door",
          "register": "lunch register", "vending": "vending machine", "scoreboard": "scoreboard"}
THING_VLAN = "40"

# what a port for a PC or a thing looks like on every access switch
EDGE_PORT = [" switchport mode access", " switchport port-security", " switchport port-security maximum 2",
             " switchport port-security mac-address sticky", " switchport port-security violation restrict",
             " ip dhcp snooping limit rate 15", " spanning-tree portfast", " spanning-tree bpduguard enable"]
PARKED_PORT = [" switchport access vlan 998", " switchport mode access", " shutdown"]


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

def new_mac_address(xml, mac, used):
    """A MAC address from the same maker as mac that is not in the lab yet."""
    while True:
        new_mac = mac[:7] + f"{random.randrange(16 ** 6):06X}"
        new_mac = new_mac[:9] + "." + new_mac[9:]
        if new_mac not in xml and new_mac not in used:
            used.add(new_mac)
            return new_mac


def copy_device(xml, block, old_room, new_room, used, new_lines, step=None):
    """Returns (the new <DEVICE> block, its physical view node, {old number: new number}).
    new_lines changes one config line (only the switch needs it). step is how far right of
    the old one the new icon goes in the physical view."""
    numbers = {}

    # the number cables point at, and the two memory addresses Packet Tracer saved
    old_ref = ref_of(block)
    numbers[old_ref] = "save-ref-id:" + new_number(xml, 19, used)
    for address in set(re.findall(r"<(?:MEM_ADDR|DEV_ADDR)>(\d+)<", block)):
        numbers[address] = new_number(xml, 15, used)

    # every port gets a new MAC address from the same maker
    for mac in sorted(set(re.findall(r"\b[0-9A-F]{4}\.[0-9A-F]{4}\.[0-9A-F]{4}\b", block))):
        new_mac = new_mac_address(xml, mac, used)
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
    if step is None:
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


def room_devices(room):
    """The names of everything in a classroom, the switch first."""
    return ["SW-" + room] + [f"{room}-PC{n:02d}" for n in range(1, 16)] + [room + "-TCHR", room + "-BOARD"]


def put_in(xml, blocks, nodes, links):
    """Add new devices, their physical view icons and their cables to the lab XML: devices
    after the last device, cables after the last cable, every icon right after the one it
    was copied from."""
    for old_node, new_node in nodes:
        xml = xml.replace(old_node, old_node + "\n" + new_node, 1)
    last = xml.rindex("</DEVICE>") + len("</DEVICE>")
    xml = xml[:last] + "\n    " + "\n    ".join(blocks) + xml[last:]
    last = xml.rindex("</LINK>") + len("</LINK>")
    return xml[:last] + "\n    " + "\n    ".join(links) + xml[last:]


def copy_room(xml, old_room, new_room, old_port, new_port, new_address, names=None):
    """The lab XML with a copy of old_room added as new_room. Returns (xml, names of the new devices).
    names is what to copy when it is not the whole room (only the switch, for a room without PCs)."""
    devices = devices_of(xml)
    names = names or room_devices(old_room)
    missing = [n for n in names if n not in devices]
    if missing:
        raise Problem(f"Room {old_room} is not complete in the lab ({missing[0]} is missing).")
    old_address = next((m.group(1) for line in re.findall(r"<LINE>(.*?)</LINE>", devices["SW-" + old_room])
                        for m in [re.match(r" ip address (10\.10\.99\.\d+) ", line)] if m), None)

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
    # a cable to something that is not copied (the PCs when only the switch is, a camera in
    # the hall) is left out. The uplinks to the distribution switches always come along
    stays = old_refs | {ref_of(block) for block in devices.values() if "<RUNNINGCONFIG>" in block}
    links = [copy_link(link, numbers, old_port, new_port, xml, used)
             for link in re.findall(r"<LINK>.*?</LINK>", xml, re.S)
             if old_refs & set(re.findall(r"save-ref-id:\d+", link))
             and set(re.findall(r"save-ref-id:\d+", link)) <= stays]
    return put_in(xml, blocks, nodes, links), [name.replace(old_room, new_room) for name in names]


# ---------------------------------------------------------------- one more thing on a switch

def set_section(lines, header, body):
    """Config lines with everything under a header (like interface FastEthernet0/17) replaced."""
    lines = list(lines)
    at = lines.index(header)
    lines[at + 1:pktconfig.section_end(lines, at)] = body
    return lines


def free_access_port(lab, switch, taken):
    """The first port of an access switch that is parked (shut down, VLAN 998) and not an
    uplink slot. taken are the ports this run already gave away."""
    lines = lab.config(switch)
    for i, line in enumerate(lines):
        if re.fullmatch(r"interface (FastEthernet0/\d+|GigabitEthernet1/0/\d+)", line) and line[10:] not in taken:
            if lines[i + 1:pktconfig.section_end(lines, i)] == PARKED_PORT:
                return line[10:]
    raise Problem(f"{switch} has no free port left.")


def thing_port(place, kind):
    """The config of the switch port a thing is plugged into."""
    return [f" description {place} - {THINGS[kind]}", f" switchport access vlan {THING_VLAN}"] + EDGE_PORT


def add_things(lab, things):
    """Put things into the lab that is open in memory. things is a list of
    (name, kind, switch, where it is). Returns ({switch: {port: config lines}}, report lines).
    The caller saves the lab and gives the files in configs/ the same ports."""
    xml = lab.xml()
    devices = devices_of(xml)
    model = next((name for name in devices if name.endswith("-TCHR")), None)
    if model is None:
        raise Problem("There is no teacher PC in the lab to copy.")
    cable = next(link for link in re.findall(r"<LINK>.*?</LINK>", xml, re.S) if ref_of(devices[model]) in link)
    model_switch = next(block for block in devices.values()
                        if "<RUNNINGCONFIG>" in block and ref_of(block) in cable)
    model_port = re.search(re.escape(ref_of(model_switch)) + r"</(?:FROM|TO)>\s*<PORT>([^<]*)", cable).group(1)

    def address(block):
        return re.search(r"<DEV_ADDR>(\d+)", block).group(1)

    used = set()
    blocks, nodes, links, report = [], [], [], []
    ports = {}
    for count, (name, kind, switch, place) in enumerate(things):
        if kind not in THINGS:
            raise Problem(f"{kind} is not a kind of thing. Kinds: {', '.join(THINGS)}.")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,17}", name):
            raise Problem(f"{name}: a name is capital letters, digits and - only (18 at most).")
        if name in devices or any(name == other[0] for other in things[:count]):
            raise Problem(f"{name} is already in the lab.")
        if switch not in devices or not switch.startswith("SW-"):
            raise Problem(f"{switch} is not an access switch in the lab.")
        port = free_access_port(lab, switch, ports.get(switch, {}))
        ports.setdefault(switch, {})[port] = thing_port(place, kind)
        block, node, numbers = copy_device(xml, devices[model], model, name, used, lambda line: line,
                                           step=7 * (count + 1))
        # the cable of the teacher PC, with both ends changed
        numbers[ref_of(model_switch)] = ref_of(devices[switch])
        numbers[address(model_switch)] = address(devices[switch])
        link = copy_link(cable, numbers, "", "", xml, used)
        link = link.replace(f"<PORT>{model_port}</PORT>", f"<PORT>{port}</PORT>")
        blocks.append(block)
        nodes.append(node)
        links.append(link)
        report.append(f"{name} ({kind}, {place}) on {switch} {port}, VLAN {THING_VLAN}.")

    lab.use(put_in(xml, blocks, nodes, links))
    for switch, new_ports in ports.items():
        lines = lab.config(switch)
        for port, body in new_ports.items():
            lines = set_section(lines, "interface " + port, body)
        lab.set_config(switch, lines)
    return ports, report


def update_port_files(ports):
    """Give the files in configs/ the ports add_things() made, with the comment line that
    starts the unused ports moved down to the first port that is still unused."""
    for switch, new_ports in ports.items():
        path = os.path.join(CONFIGS, switch + ".txt")
        with open(path) as f:
            lines = f.read().splitlines()
        for port, body in new_ports.items():
            lines = set_section(lines, "interface " + port, body)
        comment = next((line for line in lines if line.startswith("! ---- Unused ports")), None)
        if comment:
            lines.remove(comment)
            for i, line in enumerate(lines):
                if line.startswith("interface ") and lines[i + 1:i + 4] == PARKED_PORT:
                    lines.insert(i, comment)
                    break
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")


def add_thing(name, kind, switch, place="", lab_path=LAB, write=True):
    """Returns the lines of a short report."""
    name, switch = name.strip().upper(), switch.strip().upper()
    kind = kind.strip().lower()
    rows = inventory_rows()
    if not place:
        place = next((row["location"] for row in rows if row["name"] == switch), "")
        place = re.sub(r" \(.*\)", "", place)
    if not re.fullmatch(r"[A-Za-z0-9 ]{1,24}", place):
        raise Problem("Where it is: letters, digits and spaces only (24 at most).")
    lab = pktconfig.Lab(lab_path)
    ports, report = add_things(lab, [(name, kind, switch, place)])
    if not write:
        return report + ["Dry run, nothing was written."]
    real_lab = os.path.abspath(lab_path) == os.path.abspath(LAB)
    backup = pktconfig.backup_lab(lab_path) if real_lab else None
    lab.save()
    if real_lab:
        update_port_files(ports)
        with open(INVENTORY, "a") as f:
            f.write(f"{name},{kind},{place},BUILDING,dhcp\n")
        pktlayout.arrange(lab_path, backup=False)
    report.append(f"Written to {os.path.basename(lab_path)}." +
                  (f" The lab from before is in changes/backups/{backup}" if backup else ""))
    if pktconfig.packet_tracer_is_open():
        report.append("Note: Packet Tracer is running. If this lab is open in it, close the lab WITHOUT "
                      "saving and open it again.")
    return report


# ---------------------------------------------------------------- the files around the lab

def room_trunk(lines, old_room, new_room, old_port, new_port):
    """Config lines of a distribution switch with the free port set up like the port of
    the old room. Works on the lab config and on the files in configs/."""
    lines = list(lines)
    old = lines.index("interface " + pktconfig.full_interface(old_port))
    new = lines.index("interface " + pktconfig.full_interface(new_port))
    section = [line.replace(old_room, new_room) for line in lines[old + 1:pktconfig.section_end(lines, old)]]
    lines[new + 1:pktconfig.section_end(lines, new)] = section
    return lines


def without_extras(lines):
    """Config lines of a classroom switch with Fa0/18 to Fa0/24 parked: a plain room uses
    1-15 for students, 16 for the teacher and 17 for the smartboard."""
    for port in range(18, 25):
        lines = set_section(lines, f"interface FastEthernet0/{port}", PARKED_PORT)
    return lines


def write_config_file(old_room, new_room, old_port, new_port, old_address, new_address):
    """configs/SW-<new room>.txt: the file of the old room with the three things that differ."""
    with open(os.path.join(CONFIGS, f"SW-{old_room}.txt")) as f:
        text = f.read()
    text = text.replace(old_room, new_room)
    text = re.sub(rf"(DIST-L3-\d ){re.escape(old_port)}\b", rf"\g<1>{new_port}", text)
    text = text.replace(f"ip address {old_address} ", f"ip address {new_address} ")
    lines = without_extras(text.splitlines())
    comment = next((line for line in lines if line.startswith("! ---- Unused ports")), None)
    if comment:
        lines.remove(comment)
        lines.insert(lines.index("interface FastEthernet0/18"), comment)
    with open(os.path.join(CONFIGS, f"SW-{new_room}.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


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
    lines.append(f"{room}-BOARD,smartboard,Room {room},BUILDING,dhcp")
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
    old_room = pktlayout.classrooms()[-1]              # rooms without student PCs are not in this list

    lab = pktconfig.Lab(lab_path)
    new_port = free_dist_port(lab)
    old_switch = lab.config("SW-" + old_room)
    old_port = next(m.group(1) for line in old_switch for m in [re.search(r"Trunk to DIST-L3-1 (\S+)", line)] if m)
    old_address = next(m.group(1) for line in old_switch for m in [re.match(r" ip address (10\.10\.99\.\d+) ", line)] if m)

    xml, names = copy_room(lab.xml(), old_room, room, old_port, new_port, address)
    lab.use(xml)
    for dist in DISTS:
        lab.set_config(dist, room_trunk(lab.config(dist), old_room, room, old_port, new_port))
    # a camera or printer the old room has in the hall does not come along, its port is parked again
    lab.set_config(names[0], without_extras(lab.config(names[0])))

    report = [f"Room {room}: {names[0]} ({address}), 15 student PCs, {names[-2]} and {names[-1]}, "
              f"copied from room {old_room}.",
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
    if len(args) < 2 or args[0] not in ("add-room", "add-thing") or (args[0] == "add-thing" and len(args) < 4):
        print(__doc__)
        print("Kinds of things:", ", ".join(THINGS))
        return 2
    try:
        if args[0] == "add-thing":
            print("\n".join(add_thing(args[1], args[2], args[3], " ".join(args[4:]), lab_path, write)))
        else:
            print("\n".join(add_room(args[1], lab_path, write, " ".join(args[2:]))))
    except Problem as err:
        print("Problem:", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

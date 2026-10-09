#!/usr/bin/env python3
"""
pktconfig.py - write configuration changes into the Packet Tracer lab file

Packet Tracer devices cannot be reached over the network from outside Packet Tracer, but
the lab is saved in one file, and that file holds the running config of every router and
switch. This program opens the file (with pktfile.py), changes the configs in it the way
IOS would if the commands were typed in, and saves the file again. Open the lab in
Packet Tracer afterwards and the devices come up with the new config.

It does six things:

  list     the routers and switches in the lab
  show     print the running config of one device, as stored in the lab
  check    compare every config in the lab with the files in ../configs
  apply    put configuration commands into one or more devices
  backups  list the copies of the lab that were kept before each change
  restore  put one of those copies back (undo)

Examples:

  python3 pktconfig.py list
  python3 pktconfig.py show SW-E230
  python3 pktconfig.py check
  python3 pktconfig.py apply SW-E230 mychange.txt
  python3 pktconfig.py apply ../changes/2026-10-08_210000_add-a-vlan-40-guest
  python3 pktconfig.py apply SW-E230 mychange.txt --dry-run
  python3 pktconfig.py backups
  python3 pktconfig.py restore 2026-10-08_214007.pkt

"apply" with a folder uses every <device>.txt file in it (the folders that netconfig.py
makes). --dry-run shows what would change and writes nothing. --lab "other file.pkt"
works on another file, for example a copy.

Things to know:

- Close the lab in Packet Tracer before applying. Packet Tracer only reads the file when
  it opens it, and saving from Packet Tracer would overwrite the change.
- A copy of the lab from before each change is kept in ../changes/backups.
- The matching file in ../configs gets the same change, so the two stay the same.
- Write commands out in full ("switchport mode access", not "sw mo acc"). Sub-commands
  of an interface have to be indented with a space, or type "exit" to leave it.
- Only configuration commands work. "show", "ping" and "crypto key generate rsa" need a
  running device.

Used by netconfig.py and netcheck_ui.py (the "Write to the lab" button).
Only uses the Python standard library, nothing to install.
"""

import datetime
import difflib
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys

import pktfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(HERE, "..", "RHS School Network.pkt")
CONFIGS = os.path.join(HERE, "..", "configs")
BACKUPS = os.path.join(HERE, "..", "changes", "backups")


class Problem(Exception):
    """Something in the commands or the lab file is wrong. The text is shown to the user."""


# ---------------------------------------------------------------- the lab file

class Lab:
    """The unpacked lab. Devices are found by the name shown under them in Packet Tracer."""

    def __init__(self, path=LAB):
        self.path = path
        try:
            xml = pktfile.read_pkt(path).decode("utf-8")
        except FileNotFoundError:
            raise Problem(f"Lab file not found: {path}")
        except (ValueError, OSError) as err:
            raise Problem(f"Cannot read {os.path.basename(path)}: {err}")
        # every odd part is one <DEVICE>...</DEVICE>, the even parts are the text in between
        self.parts = re.split(r"(<DEVICE>.*?</DEVICE>)", xml, flags=re.S)
        self.index = {}
        for i in range(1, len(self.parts), 2):
            name = re.search(r"<NAME[^>]*>([^<]*)</NAME>", self.parts[i])
            if name and "<RUNNINGCONFIG>" in self.parts[i]:
                self.index[html.unescape(name.group(1))] = i

    def names(self):
        """Routers and switches (PCs and servers have no IOS config)."""
        return list(self.index)

    def _device(self, name):
        if name not in self.index:
            raise Problem(f"There is no router or switch called {name} in the lab.")
        return self.parts[self.index[name]]

    @staticmethod
    def _lines(block):
        return [html.unescape(l) for l in re.findall(r"<LINE>(.*?)</LINE>", block, re.S)]

    def config(self, name):
        """The running config of a device as a list of lines."""
        return self._lines(re.search(r"<RUNNINGCONFIG>(.*?)</RUNNINGCONFIG>", self._device(name), re.S).group(1))

    def set_config(self, name, lines):
        """Replace the running config, and save it like "write memory" would."""
        device = self._device(name)
        packed = "".join("<LINE>" + l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</LINE>"
                         for l in lines)
        startup = re.search(r"<STARTUPCONFIG>(.*?)</STARTUPCONFIG>", device, re.S)
        old_startup = self._lines(startup.group(1)) if startup else None

        def new_content(match):
            return match.group(1) + packed + match.group(3)

        def saved_copy(match):
            # a 2960 also keeps the startup config as the file flash:config.text
            return new_content(match) if self._lines(match.group(2)) == old_startup else match.group(0)

        device = re.sub(r"(<RUNNINGCONFIG>\s*)(.*?)(\s*</RUNNINGCONFIG>)", new_content, device, flags=re.S)
        device = re.sub(r"(<STARTUPCONFIG>\s*)(.*?)(\s*</STARTUPCONFIG>)", new_content, device, flags=re.S)
        device = re.sub(r"(<FILE_CONTENT class=\"CConfigFileContent\">\s*<CONFIG>\s*)(.*?)(\s*</CONFIG>)",
                        saved_copy, device, flags=re.S)
        self.parts[self.index[name]] = device

    def vlans(self, name):
        """The VLAN database of a switch: {number: name}. It is not part of the running config."""
        lists = re.findall(r"<VLANS>(.*?)</VLANS>", self._device(name), re.S)
        found = {}
        for element in re.findall(r"<VLAN [^>]*/>", lists[-1] if lists else ""):
            found[int(re.search(r'number="(\d+)"', element).group(1))] = \
                html.unescape(re.search(r'name="([^"]*)"', element).group(1))
        return found

    def change_vlans(self, name, changes):
        """changes is a list of ("add", number, vlan name) and ("remove", number, None).
        An "add" without a name keeps the name the VLAN has, or uses VLAN0040 for a new one.
        The switch keeps the list in a few places (memory and vlan.dat), all get the change."""

        def new_list(match):
            count, gap, inside = match.group(1), match.group(2) or "", match.group(3)
            elements = re.findall(r"<VLAN [^>]*/>", inside)
            if not elements:
                return match.group(0)
            between = inside[inside.index(elements[0]) + len(elements[0]):inside.index(elements[1])] \
                if len(elements) > 1 else ""
            before = inside[:inside.index(elements[0])]
            after = inside[inside.rindex(elements[-1]) + len(elements[-1]):]
            by_number = {int(re.search(r'number="(\d+)"', e).group(1)): e for e in elements}
            for action, number, vlan_name in changes:
                if action == "remove":
                    by_number.pop(number, None)
                elif vlan_name is None:
                    by_number.setdefault(number, f'<VLAN name="VLAN{number:04d}" number="{number}" rspan="0" />')
                else:
                    by_number[number] = f'<VLAN name="{html.escape(vlan_name)}" number="{number}" rspan="0" />'
            text = "<VLANS>" + before + between.join(by_number[n] for n in sorted(by_number)) + after + "</VLANS>"
            if count is not None:
                text = f"<VLAN_COUNT>{len(by_number)}</VLAN_COUNT>{gap}" + text
            return text

        device = re.sub(r"(?:<VLAN_COUNT>(\d+)</VLAN_COUNT>(\s*))?<VLANS>(.*?)</VLANS>", new_list,
                        self._device(name), flags=re.S)
        self.parts[self.index[name]] = device

    def save(self, path=None):
        path = path or self.path
        temporary = path + ".tmp"
        pktfile.write_pkt(temporary, "".join(self.parts).encode("utf-8"))
        os.replace(temporary, path)                # the old file is only replaced by a complete new one


# ---------------------------------------------------------------- small helpers

INTERFACE_TYPES = ["FastEthernet", "GigabitEthernet", "TenGigabitEthernet", "Port-channel", "Vlan",
                   "Loopback", "Serial", "Ethernet", "Tunnel"]
MADE_BY_CONFIG = ("Port-channel", "Vlan", "Loopback", "Tunnel")   # the others are real ports
ALL_VLANS = set(range(1, 1006))


def full_interface(text):
    """Fa0/5 -> FastEthernet0/5, gi1/0/3 -> GigabitEthernet1/0/3, vlan 99 -> Vlan99."""
    match = re.fullmatch(r"([A-Za-z\-]+)\s*(\d+(?:/\d+)*(?:\.\d+)?)", text.strip())
    kinds = [k for k in INTERFACE_TYPES if match and k.lower().startswith(match.group(1).lower())]
    if not kinds:
        raise Problem(f"'{text.strip()}' is not an interface name.")
    return kinds[0] + match.group(2)


def interface_range(text):
    """'fa0/1 - 15 , fa0/17 - 24' -> the list of full interface names."""
    names = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*([A-Za-z\-]+\s*(?:\d+/)*)(\d+)\s*(?:-\s*(\d+))?\s*", part)
        if not match or int(match.group(3) or match.group(2)) < int(match.group(2)):
            raise Problem(f"'interface range {text}' is not a valid range.")
        for number in range(int(match.group(2)), int(match.group(3) or match.group(2)) + 1):
            names.append(full_interface(match.group(1) + str(number)))
    return names


def number_list(text):
    """'10,20,30-32' -> {10, 20, 30, 31, 32}"""
    numbers = set()
    for part in text.split(","):
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part.strip())
        first = int(match.group(1)) if match else 0
        last = int(match.group(2) or first) if match else 0
        if not 1 <= first <= last <= 4094:
            raise Problem(f"'{text}' is not a VLAN list. Write it like 10,20 or 10-15.")
        numbers.update(range(first, last + 1))
    return numbers


def list_text(numbers):
    """{10, 20, 30, 31, 32} -> '10,20,30-32', the way IOS prints it."""
    parts = []
    run = []
    for number in sorted(numbers) + [None]:
        if run and number == run[-1] + 1:
            run.append(number)
            continue
        if run:
            parts.append(str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}")
        run = [number]
    return ",".join(parts)


def secret_hash(password, salt="mERr"):
    """The "secret 5" hash IOS stores instead of the password (MD5 crypt). Packet Tracer
    always uses the salt mERr."""
    pw, s = password.encode(), salt.encode()
    final = hashlib.md5(pw + s + pw).digest()
    start = pw + b"$1$" + s + (final * (len(pw) // 16 + 1))[:len(pw)]
    n = len(pw)
    while n:
        start += b"\x00" if n & 1 else pw[:1]
        n >>= 1
    final = hashlib.md5(start).digest()
    for i in range(1000):
        final = hashlib.md5((pw if i & 1 else final) + (s if i % 3 else b"") + (pw if i % 7 else b"") +
                            (final if i & 1 else pw)).digest()
    letters = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = ""
    for a, b, c, count in ((0, 6, 12, 4), (1, 7, 13, 4), (2, 8, 14, 4), (3, 9, 15, 4), (4, 10, 5, 4), (None, None, 11, 2)):
        value = final[c] if a is None else (final[a] << 16) | (final[b] << 8) | final[c]
        for _ in range(count):
            out += letters[value & 63]
            value >>= 6
    return f"$1${salt}${out}"


# ---------------------------------------------------------------- reading the commands

OPENERS = re.compile(r"(interface|line|router|vlan|ip access-list|ipv6 access-list|ip dhcp pool|"
                     r"class-map|policy-map|route-map) ", re.I)
# first words that are never typed inside an interface or line, used when nothing is indented
GLOBAL_ONLY = re.compile(r"(no )?(hostname|username|banner|enable|access-list|ntp|snmp-server|service|vtp|lldp|"
                         r"ip route|ip routing|ip default-gateway|ip domain-name|ip ssh|ip nat|"
                         r"spanning-tree vlan|spanning-tree mode) ", re.I)
IGNORED = {"enable", "en", "configure terminal", "conf t", "config t", "end", "write memory", "write", "wr",
           "wr mem", "copy running-config startup-config", "copy run start"}
NEEDS_DEVICE = ("show ", "do ", "ping ", "traceroute ", "reload", "copy ", "erase ", "delete ", "clear ",
                "debug ", "default ", "crypto key ")


def read_script(text):
    """Turn typed commands into steps: (section header or None, command or None)."""
    raw = [l.rstrip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("!")]
    nothing_indented = not any(l.startswith(" ") for l in raw)
    steps = []
    header = None
    for line in raw:
        command = " ".join(line.split())
        if command.lower().startswith("int "):
            command = "interface " + command[4:]
        low = command.lower()
        if low == "exit" or low in IGNORED:
            header = None
            continue
        if low.startswith("crypto key "):
            raise Problem("'crypto key generate rsa' cannot be written into the file. Type it on the "
                          "device in Packet Tracer.")
        if (low + " ").startswith(NEEDS_DEVICE):
            raise Problem(f"'{command}' is not a configuration command, it needs a running device.")
        indented = line.startswith(" ")
        if OPENERS.match(command + " ") and (nothing_indented or not indented or header is None):
            header = command
            steps.append((header, None))
        elif header and (indented or (nothing_indented and not GLOBAL_ONLY.match(command + " "))):
            steps.append((header, command))
        else:
            header = None
            steps.append((None, command))
    return steps


# ---------------------------------------------------------------- changing a config
# A config is a list of lines. Lines that start with a space belong to the section above
# them (an interface, a line, an ACL...). Lines that start with ! are comments.

DEFAULT_ON = {"ip domain-lookup", "switchport", "cdp enable", "cdp run", "ip dhcp snooping information option"}

# commands that replace the old line instead of adding a second one. The part in
# brackets has to be the same too ("standby 10 ip" does not replace "standby 20 ip")
ONE_PER_SECTION = [re.compile(p + r"(?: |$)") for p in (
    r"hostname", r"description", r"ip address(?!.* secondary)", r"switchport mode", r"switchport access vlan",
    r"switchport trunk native vlan", r"switchport trunk encapsulation", r"switchport port-security maximum",
    r"switchport port-security violation", r"spanning-tree mode", r"spanning-tree portfast",
    r"spanning-tree bpduguard", r"exec-timeout", r"standby version", r"standby (\d+) (ip|priority|timers)",
    r"ip default-gateway", r"enable secret", r"enable password", r"banner motd", r"username (\S+)",
    r"ip domain-name", r"ip ssh version", r"channel-group", r"speed", r"duplex", r"bandwidth", r"mtu",
    r"ip ospf (hello-interval|dead-interval|cost|priority)", r"router-id", r"transport input",
    r"access-class \S+ (in|out)", r"ip access-group \S+ (in|out)", r"ip nat (?:inside|outside)$",
    r"logging trap", r"login", r"password", r"ip dhcp snooping limit rate", r"ip dhcp snooping vlan",
    r"default-information originate", r"vtp mode", r"vtp domain", r"service timestamps (log|debug)")]


def kind_of(command):
    if command.startswith("no "):
        command = command[3:]
    for number, pattern in enumerate(ONE_PER_SECTION):
        match = pattern.match(command)
        if match:
            return (number,) + match.groups()
    return None


def section_end(lines, header):
    """Index of the first line after a section."""
    i = header + 1
    while i < len(lines) and lines[i].startswith(" "):
        i += 1
    return i


def members(lines, header):
    """Indexes of the lines inside a section, or of all top level lines if header is None."""
    if header is not None:
        return list(range(header + 1, section_end(lines, header)))
    return [i for i, l in enumerate(lines) if l and l[0] not in " !" and l != "end"]


def words_of(line):
    words = line.split()
    return words[1:] if words[:1] == ["no"] else words


def place_for(lines, header, command):
    """Where a new line goes: after the lines that look most like it. Returns (index, is_new_group)."""
    inside = members(lines, header)
    words = words_of(command)
    for count in (2, 1):
        alike = [i for i in inside if words_of(lines[i])[:count] == words[:count]]
        if alike and len(words) >= count:
            return (alike[-1] + 1 if header is not None else section_end(lines, alike[-1])), False
    if header is not None:
        return section_end(lines, header), False
    # nothing like it yet: put it just above the "line con 0" part near the end
    where = next((i for i in inside if lines[i].startswith("line ")),
                 lines.index("end") if "end" in lines else len(lines))
    while where > 0 and lines[where - 1].startswith("! "):
        where -= 1
    return where, True


def add(lines, header, command):
    indent = "" if header is None else " "
    inside = members(lines, header)
    texts = [lines[i].strip() for i in inside]
    if command in texts:
        return
    if "no " + command in texts:                   # "switchport" takes away "no switchport"
        del lines[inside[texts.index("no " + command)]]
        return
    kind = kind_of(command)
    if kind:
        for i, text in zip(inside, texts):
            if kind_of(text) == kind:
                lines[i] = indent + command
                return
    where, new_group = place_for(lines, header, command)
    lines[where:where] = [indent + command] + (["!"] if new_group else [])


def remove(lines, header, what, notes):
    inside = members(lines, header)
    texts = [lines[i].strip() for i in inside]
    hits = [i for i, t in zip(inside, texts) if t == what] or \
           [i for i, t in zip(inside, texts) if t.startswith(what + " ")]
    for i in reversed(hits):
        del lines[i:section_end(lines, i) if header is None else i + 1]
        if header is None and 0 < i < len(lines) and lines[i - 1] == lines[i] == "!":
            del lines[i]                           # do not leave two separator lines behind
    if hits or what == "shutdown" or "no " + what in texts:
        return
    passive = what.startswith("passive-interface ") and "passive-interface default" in texts
    if what in DEFAULT_ON or passive:              # on unless the config says no
        where, new_group = place_for(lines, header, what)
        lines[where:where] = [("" if header is None else " ") + "no " + what] + (["!"] if new_group else [])
    else:
        notes.append(f"'{what}' is not in the config, nothing was removed.")


def find_section(lines, header):
    for i in members(lines, None):
        if lines[i].lower() == header.lower():
            return i
    return None


def make_section(lines, header):
    """Index of a section header. Sections that do not exist yet are made in a sensible place."""
    found = find_section(lines, header)
    if found is not None:
        return found
    if not header.startswith("interface "):
        where, new_group = place_for(lines, None, header)
        lines[where:where] = [header] + (["!"] if new_group else [])
        return where

    name = header[len("interface "):]
    kind = next(k for k in INTERFACE_TYPES if name.startswith(k))
    if kind not in MADE_BY_CONFIG and "." not in name:
        raise Problem(f"has no interface {name}")

    def order(text):
        return [int(n) for n in re.findall(r"\d+", text)]

    interfaces = [i for i in members(lines, None) if lines[i].startswith("interface ")]
    same = [i for i in interfaces if lines[i].startswith("interface " + (name.split(".")[0] if "." in name else kind))]
    lower = [i for i in same if order(lines[i]) < order(name)]
    if lower or (not same and interfaces and kind != "Loopback"):
        where = section_end(lines, (lower or interfaces)[-1])
        if where < len(lines) and lines[where] == "!":
            where += 1
    else:
        where = (same or interfaces or [place_for(lines, None, header)[0]])[0]
        while where > 0 and lines[where - 1].startswith("! "):
            where -= 1
    lines[where:where] = [header, "!"]
    return where


def trunk_allowed(lines, header, rest, negative):
    """switchport trunk allowed vlan add/remove/except/all/none/<list>"""
    start = "switchport trunk allowed vlan"
    old = next((i for i in members(lines, header) if lines[i].strip().startswith(start + " ")), None)
    if old is None:
        current = set(ALL_VLANS)
    else:
        text = lines[old].strip()[len(start):].strip()
        current = set() if text == "none" else number_list(text)
    words = rest.split()
    if negative or words == ["all"]:
        new = set(ALL_VLANS)
    elif words == ["none"]:
        new = set()
    elif len(words) == 2 and words[0] == "add":
        new = current | number_list(words[1])
    elif len(words) == 2 and words[0] == "remove":
        new = current - number_list(words[1])
    elif len(words) == 2 and words[0] == "except":
        new = ALL_VLANS - number_list(words[1])
    elif len(words) == 1:
        new = number_list(words[0])
    else:
        raise Problem(f"'{start} {rest}' is not complete.")
    if old is not None:
        del lines[old]
    if new != ALL_VLANS:                           # all VLANs allowed is the default, IOS shows no line then
        line = f" {start} {list_text(new) if new else 'none'}"
        lines.insert(old if old is not None else place_for(lines, header, start)[0], line)


def stp_priority(lines, vlans, priority):
    """spanning-tree vlan <list> priority <n>. IOS keeps one line per priority value."""
    pattern = re.compile(r"spanning-tree vlan (\S+) priority (\d+)")
    done = priority is None
    for i in reversed(members(lines, None)):
        match = pattern.fullmatch(lines[i])
        if not match:
            continue
        current = number_list(match.group(1))
        if int(match.group(2)) == priority:
            current |= vlans
            done = True
        else:
            current -= vlans
        if current:
            lines[i] = f"spanning-tree vlan {list_text(current)} priority {match.group(2)}"
        else:
            del lines[i]
    if not done:
        add(lines, None, f"spanning-tree vlan {list_text(vlans)} priority {priority}")


def global_command(lines, command, vlan_changes, notes):
    negative = command.startswith("no ")
    body = command[3:] if negative else command

    match = re.fullmatch(r"spanning-tree vlan (\S+)(?: priority(?: (\d+))?| root(?: (primary|secondary))?)", body)
    if match and (negative or match.group(2) or match.group(3)):
        priority = None if negative else int(match.group(2) or {"primary": 24576, "secondary": 28672}[match.group(3)])
        if priority is not None and (priority % 4096 or priority > 61440):
            raise Problem("Spanning tree priority has to be a multiple of 4096, up to 61440.")
        return stp_priority(lines, number_list(match.group(1)), priority)

    if negative and body.startswith("vlan "):
        numbers = number_list(body[5:])
        if numbers & {1, 1002, 1003, 1004, 1005}:
            raise Problem("VLAN 1 and 1002-1005 are built in and cannot be removed.")
        vlan_changes.extend(("remove", n, None) for n in sorted(numbers))
        return None

    if negative and body.startswith("interface "):
        name = full_interface(body[len("interface "):])
        if not name.startswith(MADE_BY_CONFIG) and "." not in name:
            raise Problem(f"{name} is a real port and cannot be removed. Use 'shutdown'.")
        return remove(lines, None, "interface " + name, notes)

    if body.startswith("banner motd ") and not negative:
        text = body[len("banner motd "):]
        mark = "^C" if text.startswith("^C") else text[0]
        if len(text) < 2 * len(mark) or not text.endswith(mark) or mark in text[len(mark):-len(mark)]:
            raise Problem("The banner has to be on one line and start and end with the same character, "
                          "like: banner motd #text#")
        command = f"banner motd ^C{text[len(mark):-len(mark)]}^C"

    match = re.fullmatch(r"(username \S+(?: privilege \d+)? secret|enable secret) (?:(0|5) )?(\S+)", body)
    if match and not negative and match.group(2) != "5":
        command = f"{match.group(1)} 5 {secret_hash(match.group(3))}"     # never keep the password itself

    if negative:
        return remove(lines, None, body, notes)
    return add(lines, None, command)


def section_command(lines, header, command, notes):
    negative = command.startswith("no ")
    body = command[3:] if negative else command
    if body == "shut":
        body = command = "shutdown"
    title = lines[header]

    if title.startswith("interface ") and (body + " ").startswith("switchport trunk allowed vlan "):
        return trunk_allowed(lines, header, body[len("switchport trunk allowed vlan"):].strip(), negative)

    if "access-list" in title:
        # the order of ACL lines matters, so new lines always go at the end like on IOS
        if re.match(r"\d+ ", body):
            raise Problem("ACL line numbers are not supported. Remove the ACL with "
                          "'no ip access-list ...' and write all of it again.")
        inside = members(lines, header)
        same = [i for i in inside if lines[i].strip() == body]
        if negative and same:
            del lines[same[0]]
        elif negative:
            notes.append(f"'{body}' is not in {title}, nothing was removed.")
        elif not same:
            lines.insert(section_end(lines, header), " " + body)
        return None

    if title.startswith("router ") and re.match(r"passive-interface (?!default$)", body):
        body = "passive-interface " + full_interface(body.split(None, 1)[1])
        command = body

    if negative:
        return remove(lines, header, body, notes)
    return add(lines, header, command)


def targets_of(lines, header):
    """The sections a typed header means. 'interface range' and 'line vty 0 15' can be several."""
    low = header.lower()
    if low.startswith("interface range "):
        return ["interface " + name for name in interface_range(header[len("interface range "):])]
    if low.startswith("interface "):
        return ["interface " + full_interface(header[len("interface "):])]
    match = re.fullmatch(r"line (con|console|aux|vty) (\d+)(?: (\d+))?", low)
    if match:
        kind = "con" if match.group(1) == "console" else match.group(1)
        first, last = int(match.group(2)), int(match.group(3) or match.group(2))
        found = []
        for i in members(lines, None):                     # the config stores vty 0 4 and vty 5 15 apart
            stored = re.fullmatch(rf"line {kind} (\d+)(?: (\d+))?", lines[i])
            if stored and int(stored.group(1)) <= last and int(stored.group(2) or stored.group(1)) >= first:
                found.append(lines[i])
        return found or [f"line {kind} {first}" + (f" {last}" if match.group(3) else "")]
    return [header]


def merge(old_lines, script):
    """Apply typed commands to a config. Returns (new lines, VLAN database changes, notes)."""
    lines = list(old_lines)
    vlan_changes = []
    notes = []
    for header, command in read_script(script):
        if header is None:
            global_command(lines, command, vlan_changes, notes)
        elif header.lower().startswith("vlan "):
            # VLANs are kept in the VLAN database (vlan.dat), not in the running config
            numbers = sorted(number_list(header[5:]))
            if command is None:
                vlan_changes.extend(("add", n, None) for n in numbers)
            elif command.startswith("name ") and len(numbers) == 1:
                vlan_changes.append(("add", numbers[0], command[5:].strip()))
            else:
                notes.append(f"'{command}' under '{header}' was left out, only 'name' is supported there.")
        else:
            for target in targets_of(lines, header):
                where = make_section(lines, target)
                if command is not None:
                    section_command(lines, where, command, notes)
    return lines, vlan_changes, notes


# ---------------------------------------------------------------- applying to the lab

def without_comments(lines):
    return [l.rstrip() for l in lines if l.strip() and not l.startswith("!")]


def packet_tracer_is_open():
    try:
        return subprocess.run(["pgrep", "-x", "PacketTracer"], capture_output=True).returncode == 0
    except OSError:
        return False                               # no pgrep (Windows): cannot tell


def backup_lab(lab_path=LAB):
    """Keep a copy of the lab in ../changes/backups before it is changed. For the project's
    own lab the configs folder is copied too, so restore() can put both back.
    Returns the file name of the copy."""
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = stamp
    extra = 1
    while os.path.exists(os.path.join(BACKUPS, name + ".pkt")):    # two changes in the same second
        extra += 1
        name = f"{stamp}-{extra}"
    shutil.copy2(lab_path, os.path.join(BACKUPS, name + ".pkt"))
    if os.path.abspath(lab_path) == os.path.abspath(LAB) and os.path.isdir(CONFIGS):
        shutil.copytree(CONFIGS, os.path.join(BACKUPS, name + ".configs"))
    return name + ".pkt"


def backups():
    """Names of the kept copies, newest first."""
    if not os.path.isdir(BACKUPS):
        return []
    return sorted((f for f in os.listdir(BACKUPS) if f.endswith(".pkt")), reverse=True)


def restore(name, lab_path=LAB):
    """Put a kept copy back. The lab as it is now is kept as a new copy first, so a
    restore can be undone too. Returns the name of that new copy."""
    source = os.path.join(BACKUPS, name)
    if not re.fullmatch(r"[\w\-]+\.pkt", name) or not os.path.exists(source):
        raise Problem(f"There is no backup called {name}.")
    Lab(source)                                    # stops here if the copy cannot be read
    kept = backup_lab(lab_path)
    shutil.copy2(source, lab_path)
    old_configs = source[:-4] + ".configs"
    if os.path.abspath(lab_path) == os.path.abspath(LAB) and os.path.isdir(old_configs):
        for file_name in os.listdir(old_configs):
            shutil.copy2(os.path.join(old_configs, file_name), os.path.join(CONFIGS, file_name))
    return kept


def overview(lab_path=LAB):
    """One dict per router and switch in the lab: name, config lines, VLANs, and whether
    its config is the same as the file in ../configs."""
    lab = Lab(lab_path)
    rows = []
    for name in lab.names():
        config = lab.config(name)
        path = os.path.join(CONFIGS, name + ".txt")
        same = None
        if os.path.exists(path):
            with open(path) as f:
                same = without_comments(f.read().splitlines()) == without_comments(config)
        hostname = next((l.split(None, 1)[1] for l in config if l.startswith("hostname ")), name)
        rows.append({"name": name, "hostname": hostname, "lines": len(config), "same_as_file": same,
                     "vlans": {n: v for n, v in sorted(lab.vlans(name).items()) if n not in (1, 1002, 1003, 1004, 1005)}})
    return rows


def update_config_file(name, script):
    """Give ../configs/<name>.txt the same change, keeping its comment lines."""
    path = os.path.join(CONFIGS, name + ".txt")
    if not os.path.exists(path):
        return
    with open(path) as f:
        lines = f.read().splitlines()
    lines = merge(lines, script)[0]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def apply(scripts, lab_path=LAB, write=True):
    """scripts is {device name: commands as text}. Every script is checked first. If one
    has a mistake nothing is written at all.

    Returns {"changes": {device: text of what changed}, "notes": [...], "backup": file name or None}."""
    lab = Lab(lab_path)
    changes = {}
    notes = []
    for name, script in scripts.items():
        old = lab.config(name)
        try:
            new, vlan_changes, device_notes = merge(old, script)
        except Problem as err:
            raise Problem(f"{name}: {err}")
        notes += [f"{name}: {note}" for note in device_notes]

        report = [l for l in difflib.unified_diff(old, new, lineterm="", n=1) if not l.startswith(("---", "+++"))]
        existing = lab.vlans(name)
        for action, number, vlan_name in vlan_changes:
            if action == "add" and vlan_name is None:
                existing.setdefault(number, None)          # the name may come on the next line
            elif action == "add" and existing.get(number) != vlan_name:
                report.append(f"+vlan {number} name {vlan_name}   (VLAN database)")
                existing[number] = vlan_name
            elif action == "remove" and number in existing:
                report.append(f"-vlan {number} name {existing.pop(number)}   (VLAN database)")
        report += [f"+vlan {n} name VLAN{n:04d}   (VLAN database)" for n, v in existing.items() if v is None]
        changes[name] = "\n".join(report) if report else "Nothing to change, the config already has this."

        if new != old:
            lab.set_config(name, new)
        if vlan_changes:
            lab.change_vlans(name, vlan_changes)

    backup = None
    if write:
        backup = backup_lab(lab_path)
        lab.save()
        if os.path.abspath(lab_path) == os.path.abspath(LAB):
            for name, script in scripts.items():
                try:
                    update_config_file(name, script)
                except Problem as err:
                    notes.append(f"configs/{name}.txt was not updated: {err}")
        if packet_tracer_is_open():
            notes.append("Packet Tracer is running. If this lab is open in it, close the lab WITHOUT saving "
                         "and open it again. Saving there would put the old configs back.")
    return {"changes": changes, "notes": notes, "backup": backup}


# ---------------------------------------------------------------- commands

def list_devices(lab_path):
    lab = Lab(lab_path)
    for name in lab.names():
        vlans = [n for n in lab.vlans(name) if n not in (1, 1002, 1003, 1004, 1005)]
        print(f"{name:<12}{len(lab.config(name)):>5} config lines   VLANs: {list_text(vlans) or '-'}")
    return 0


def show(lab_path, name):
    print("\n".join(Lab(lab_path).config(name)))
    return 0


def check(lab_path):
    """Is every config in the lab the same as its file in ../configs (ignoring comments)?"""
    lab = Lab(lab_path)
    different = 0
    for name in lab.names():
        path = os.path.join(CONFIGS, name + ".txt")
        if not os.path.exists(path):
            print(f"{name:<12}no file in configs")
            continue
        with open(path) as f:
            on_disk = without_comments(f.read().splitlines())
        in_lab = without_comments(lab.config(name))
        delta = [l for l in difflib.unified_diff(on_disk, in_lab, "configs/" + name + ".txt", "lab", lineterm="", n=0)]
        print(f"{name:<12}{'same' if not delta else 'DIFFERENT'}")
        for line in delta[2:]:
            print("   ", line)
        different += bool(delta)
    print()
    print("All configs in the lab match the configs folder." if not different
          else f"{different} device(s) differ. Lines with + are only in the lab, lines with - only in the file.")
    return 1 if different else 0


def apply_command(lab_path, args, write):
    if len(args) == 1 and os.path.isdir(args[0]):
        known = Lab(lab_path).names()
        scripts = {}
        for file_name in sorted(os.listdir(args[0])):
            if file_name.endswith(".txt") and file_name[:-4] in known:
                with open(os.path.join(args[0], file_name)) as f:
                    scripts[file_name[:-4]] = f.read()
        if not scripts:
            raise Problem(f"No <device>.txt files found in {args[0]}")
    elif len(args) == 2:
        with open(args[1]) as f:
            scripts = {args[0]: f.read()}
    else:
        raise Problem("Use: apply <device> <file with commands>   or   apply <folder>")

    result = apply(scripts, lab_path, write)
    for name, text in result["changes"].items():
        print(f"== {name}")
        print(text)
    print()
    for note in result["notes"]:
        print("Note:", note)
    if write:
        print(f"Written to {os.path.basename(lab_path)}. The file from before is in changes/backups/{result['backup']}")
    else:
        print("Dry run, nothing was written.")
    return 0


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
    try:
        if args == ["list"]:
            return list_devices(lab_path)
        if len(args) == 2 and args[0] == "show":
            return show(lab_path, args[1])
        if args == ["check"]:
            return check(lab_path)
        if args and args[0] == "apply":
            return apply_command(lab_path, args[1:], write)
        if args == ["backups"]:
            print("\n".join(backups()) or "No backups yet.")
            return 0
        if len(args) == 2 and args[0] == "restore":
            kept = restore(args[1], lab_path)
            print(f"{args[1]} is the lab again. The lab from just before is in changes/backups/{kept}")
            return 0
    except Problem as err:
        print("Problem:", err)
        return 1
    except OSError as err:
        print("Problem:", err)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

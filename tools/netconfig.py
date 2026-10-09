#!/usr/bin/env python3
"""
netconfig.py - build configuration changes for groups of devices

Pick some devices and one change (for example "add a VLAN"), and this makes the exact
commands for every device. Devices do not all get the same lines: a 2960 and a 3650 name
their ports differently, DIST-L3-1 and DIST-L3-2 need different addresses, and some
commands do not exist on a router. The program works that out per device.

Packet Tracer devices cannot be reached over the network from outside Packet Tracer, so
apply() hands the scripts to pktconfig.py, which writes them into the lab file itself.
(Pasting a script into the device's CLI still works too.) On real equipment the same
scripts would be sent over SSH.

Used by netcheck_ui.py (the "Configure devices" tab).
"""

import csv
import datetime
import ipaddress
import os
import re

import pktconfig

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIGS = os.path.join(HERE, "..", "configs")
CHANGES = os.path.join(HERE, "..", "changes")

# device groups, in the order they are shown
GROUPS = [
    ("edge", "Edge routers"),
    ("core", "Core switches"),
    ("dist", "Distribution switches"),
    ("room", "Room switches"),
    ("access", "Other access switches (office, MDF)"),
]


# ---------------------------------------------------------------- devices

def group_of(name):
    """Which layer a device belongs to, from its name."""
    if name.startswith("RHS-EDGE"):
        return "edge"
    if name.startswith("CORE-"):
        return "core"
    if name.startswith("DIST-"):
        return "dist"
    if name in ("SW-OFFICE", "SW-MDF"):
        return "access"
    if name.startswith("SW-"):
        return "room"
    return None


def load_devices():
    """Routers and switches from inventory.csv, as a list of dicts."""
    devices = []
    with open(os.path.join(HERE, "inventory.csv"), newline="") as f:
        for row in csv.DictReader(f):
            group = group_of(row["name"])
            if group:
                devices.append({"name": row["name"], "group": group, "type": row["type"],
                                "location": row["location"], "ip": row["ip"]})
    return devices


def is_switch(device):
    return device["group"] != "edge"


def read_interfaces(name):
    """Read the saved config of a device and return {interface name: [its lines]}."""
    interfaces = {}
    current = None
    path = os.path.join(CONFIGS, name + ".txt")
    if not os.path.exists(path):
        return interfaces
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("interface "):
                current = line[len("interface "):]
                interfaces[current] = []
            elif line.startswith(" ") and current:
                interfaces[current].append(line.strip())
            elif not line.startswith("!"):
                current = None
    return interfaces


def trunk_ports(name, contains=""):
    """Trunk interfaces of a device. Members of an EtherChannel are left out because
    the change goes on the Port-channel interface instead."""
    found = []
    for port, lines in read_interfaces(name).items():
        if "switchport mode trunk" not in lines:
            continue
        if any(l.startswith("channel-group") for l in lines):
            continue
        description = " ".join(l for l in lines if l.startswith("description"))
        if contains and contains.lower() not in description.lower():
            continue
        found.append(port)
    return found


# ---------------------------------------------------------------- checking what was typed

# Something the user typed is wrong. The text is shown on the page. It is the same class
# as in pktconfig.py, so a mistake found while writing the lab is shown the same way.
Problem = pktconfig.Problem


def need_vlan(text):
    if not text.isdigit() or not 2 <= int(text) <= 1001:
        raise Problem("VLAN has to be a number from 2 to 1001.")
    return int(text)


def need_ip(text):
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        raise Problem(f"'{text}' is not a valid IP address.")


def need_network(text):
    try:
        return ipaddress.ip_network(text)
    except ValueError as err:
        raise Problem(f"'{text}' is not a valid subnet ({err}).")


def need_word(text, what):
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", text):
        raise Problem(f"{what} can only use letters, numbers, - and _ (no spaces).")
    return text


def need_interface(text):
    if not re.fullmatch(r"[A-Za-z\-]+ ?\d+(/\d+){0,2}", text):
        raise Problem("Interface should look like Fa0/5, Gi1/0/3 or Vlan99.")
    return text


def need_number(text, what, low, high):
    if not text.isdigit() or not low <= int(text) <= high:
        raise Problem(f"{what} has to be a number from {low} to {high}.")
    return int(text)


# ---------------------------------------------------------------- the changes
# Every change is a function that gets one device and the typed values, and returns the
# config lines for that device. Returning None means "this change does not apply here".

def change_vlan(device, v):
    if not is_switch(device):
        return None
    number = need_vlan(v["vlan"])
    return [f"vlan {number}", f" name {need_word(v['name'], 'VLAN name')}"]


def change_trunk_allow(device, v):
    if device["group"] not in ("dist", "room", "access"):
        return None
    number = need_vlan(v["vlan"])
    ports = trunk_ports(device["name"], v.get("contains", "").strip())
    if not ports:
        return None
    lines = []
    for port in ports:
        lines += [f"interface {port}", f" switchport trunk allowed vlan add {number}"]
    return lines


def change_gateway(device, v):
    if device["group"] != "dist":
        return None
    number = need_vlan(v["vlan"])
    net = need_network(v["network"])
    if net.num_addresses < 8:
        raise Problem("The subnet is too small for a gateway and two switches.")
    is_first = device["name"].endswith("1")
    address = net.network_address + (2 if is_first else 3)       # .2 on DIST-L3-1, .3 on DIST-L3-2
    active = (v.get("active") or "DIST-L3-1") == device["name"]
    lines = [f"spanning-tree vlan {number} priority {24576 if active else 28672}",
             f"interface Vlan{number}",
             f" ip address {address} {net.netmask}"]
    if v.get("dhcp", "yes") == "yes":
        lines.append(" ip helper-address 10.10.70.5")
    lines += [" standby version 2", f" standby {number} ip {net.network_address + 1}"]
    if active:
        lines.append(f" standby {number} priority 110")
    lines += [f" standby {number} preempt", " no shutdown"]
    return lines


def change_port_vlan(device, v):
    if not is_switch(device):
        return None
    return [f"interface {need_interface(v['interface'])}",
            " switchport mode access",
            f" switchport access vlan {need_vlan(v['vlan'])}",
            " no shutdown"]


def change_port_state(device, v):
    return [f"interface {need_interface(v['interface'])}",
            " shutdown" if v.get("state") == "shut down" else " no shutdown"]


def change_banner(device, v):
    text = v["text"].strip()
    if not text or "#" in text:
        raise Problem("Type the banner text (without the # character).")
    return [f"banner motd #{text}#"]


def change_syslog(device, v):
    return [f"logging {need_ip(v['ip'])}"]


def change_ntp(device, v):
    return [f"ntp server {need_ip(v['ip'])}"]


def change_user(device, v):
    password = v["password"]
    if len(password) < 8 or " " in password:
        raise Problem("Password needs at least 8 characters and no spaces.")
    return [f"username {need_word(v['username'], 'Username')} privilege 15 secret {password}"]


def change_ssh_source(device, v):
    net = need_network(v["network"])
    return [f"access-list 10 permit {net.network_address} {net.hostmask}"]


def change_timeout(device, v):
    minutes = need_number(v["minutes"], "Minutes", 1, 60)
    last_vty = 15 if is_switch(device) else 4
    return ["line con 0", f" exec-timeout {minutes} 0",
            f"line vty 0 {last_vty}", f" exec-timeout {minutes} 0"]


def change_save_only(device, v):
    return []


def change_custom(device, v):
    lines = [l.rstrip() for l in v["commands"].splitlines() if l.strip()]
    if not lines:
        raise Problem("Type at least one command.")
    return lines


def field(key, label, default="", choices=None, big=False):
    return {"key": key, "label": label, "default": default, "choices": choices, "big": big}


# what the page shows in the "Change" drop-down
CATALOG = [
    {"id": "vlan", "title": "Add a VLAN", "run": change_vlan,
     "help": "Creates the VLAN on every chosen switch. Routers are skipped.",
     "fields": [field("vlan", "VLAN number", "40"), field("name", "VLAN name", "GUEST")]},
    {"id": "trunk", "title": "Allow a VLAN on trunks", "run": change_trunk_allow,
     "help": "Adds the VLAN to the allowed list of each trunk. The trunk ports are read from the saved "
             "config of each device. Leave the filter empty for every trunk, or type a word from the port "
             "description (for example Room or E230).",
     "fields": [field("vlan", "VLAN number", "40"), field("contains", "Only trunks whose description contains", "")]},
    {"id": "gateway", "title": "Create a VLAN gateway (SVI + HSRP)", "run": change_gateway,
     "help": "Distribution switches only. DIST-L3-1 gets .2, DIST-L3-2 gets .3 and they share .1 with HSRP. "
             "The active switch also becomes spanning tree root for the VLAN.",
     "fields": [field("vlan", "VLAN number", "40"), field("network", "Subnet", "10.10.40.0/24"),
                field("active", "Active switch", "DIST-L3-1", ["DIST-L3-1", "DIST-L3-2"]),
                field("dhcp", "DHCP relay to SRV-DHCP", "yes", ["yes", "no"])]},
    {"id": "portvlan", "title": "Move an access port to a VLAN", "run": change_port_vlan,
     "help": "Port names differ by model: Fa0/5 on a room switch (2960), Gi1/0/5 on a 3650.",
     "fields": [field("interface", "Interface", "Fa0/17"), field("vlan", "VLAN number", "10")]},
    {"id": "portstate", "title": "Shut down or enable an interface", "run": change_port_state,
     "help": "Handy for the failure tests in the README.",
     "fields": [field("interface", "Interface", "Gi0/1"), field("state", "Action", "shut down", ["shut down", "enable"])]},
    {"id": "banner", "title": "Change the login banner", "run": change_banner,
     "help": "The warning text shown before the login prompt.",
     "fields": [field("text", "Banner text", "RHS campus network. Authorized users only - activity is logged.")]},
    {"id": "syslog", "title": "Set the syslog server", "run": change_syslog,
     "help": "Where the device sends its log messages.",
     "fields": [field("ip", "Server IP", "10.10.70.20")]},
    {"id": "ntp", "title": "Set the NTP server", "run": change_ntp,
     "help": "Where the device gets the time from.",
     "fields": [field("ip", "Server IP", "10.10.70.20")]},
    {"id": "user", "title": "Add a local user", "run": change_user,
     "help": "A new account for console and SSH logins.",
     "fields": [field("username", "Username", "tech2"), field("password", "Password", "")]},
    {"id": "sshsource", "title": "Allow another subnet to SSH in", "run": change_ssh_source,
     "help": "Adds a line to access-list 10, which the vty lines use.",
     "fields": [field("network", "Subnet", "10.10.30.0/24")]},
    {"id": "timeout", "title": "Set the idle timeout", "run": change_timeout,
     "help": "Logs out console and SSH sessions after this many idle minutes.",
     "fields": [field("minutes", "Minutes", "10")]},
    {"id": "save", "title": "Save the running config only", "run": change_save_only,
     "help": "No changes, just saves what is running to the startup config.",
     "fields": []},
    {"id": "custom", "title": "Custom commands", "run": change_custom,
     "help": "Type your own configuration lines. The same lines go to every chosen device. Write commands "
             "out in full and put a space in front of the lines that belong to an interface.",
     "fields": [field("commands", "Commands (one per line)", "", big=True)]},
]


def find_change(change_id):
    for change in CATALOG:
        if change["id"] == change_id:
            return change
    raise Problem("Pick a change from the list.")


def describe(change, values):
    """Short one line name of the change, for the log and the folder name."""
    parts = [str(values.get(f["key"], "")).strip() for f in change["fields"] if not f["big"] and f["key"] != "password"]
    return (change["title"] + " " + " ".join(p for p in parts if p)).strip()


# ---------------------------------------------------------------- building the scripts

def build(device_names, change_id, values):
    """Returns (title, {device: script text}, [notes])."""
    change = find_change(change_id)
    devices = {d["name"]: d for d in load_devices()}
    chosen = [devices[n] for n in device_names if n in devices]
    if not chosen:
        raise Problem("Tick at least one device.")

    title = describe(change, values)
    scripts = {}
    notes = []
    for device in chosen:
        lines = change["run"](device, values)
        if lines is None:
            notes.append(f"{device['name']} skipped, this change does not apply to it.")
            continue
        script = [f"! {device['name']} - {title}", "configure terminal"]
        script += lines
        script += ["end", "write memory", ""]
        scripts[device["name"]] = "\n".join(script)
    if not scripts:
        notes.append("Nothing to do: the change does not apply to any of the chosen devices.")
    return title, scripts, notes


def save(device_names, change_id, values):
    """Write one file per device into ../changes/<time>_<name>/ and add a line to the log."""
    title, scripts, notes = build(device_names, change_id, values)
    if not scripts:
        return title, scripts, notes, None
    return title, scripts, notes, write_files(title, scripts, "no")


def apply(device_names, change_id, values):
    """Like save(), and the change is also written into the Packet Tracer lab file.
    Returns (title, scripts, notes, folder, {device: what changed in its config})."""
    title, scripts, notes = build(device_names, change_id, values)
    if not scripts:
        return title, scripts, notes, None, {}
    result = pktconfig.apply(scripts)              # stops with a Problem before anything is written
    notes = notes + result["notes"] + [f"The lab from before this change is in changes/backups/{result['backup']}"]
    return title, scripts, notes, write_files(title, scripts, "yes"), result["changes"]


def history():
    """The lines of ../changes/log.csv as dicts, newest first."""
    path = os.path.join(CHANGES, "log.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))[::-1]


def write_files(title, scripts, in_lab):
    """Save the scripts and add a line to the log. Returns the name of the new folder."""
    now = datetime.datetime.now()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    folder = os.path.join(CHANGES, now.strftime("%Y-%m-%d_%H%M%S") + "_" + slug)
    os.makedirs(folder)
    for name, script in scripts.items():
        with open(os.path.join(folder, name + ".txt"), "w") as f:
            f.write(script)

    log_path = os.path.join(CHANGES, "log.csv")
    is_new = not os.path.exists(log_path)
    with open(log_path, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["time", "change", "devices", "folder", "written to lab"])
        writer.writerow([now.strftime("%Y-%m-%d %H:%M"), title, " ".join(scripts), os.path.basename(folder), in_lab])
    return os.path.basename(folder)

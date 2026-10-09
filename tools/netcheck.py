#!/usr/bin/env python3
"""
netcheck.py - small helper for the RHS school network project

It does five things:

  subnet     show the details of one subnet
  plan       check the addressing plan (plan.csv) for mistakes and overlaps
  inventory  check the device list (inventory.csv) against the plan
  compare    show the difference between two device configs
  template   print a config for a new classroom switch

Examples:

  python3 netcheck.py subnet 10.10.8.0/22
  python3 netcheck.py plan plan.csv
  python3 netcheck.py inventory inventory.csv plan.csv
  python3 netcheck.py compare ../configs/SW-E230.txt ../configs/SW-E110.txt
  python3 netcheck.py template E231 10.10.99.17

Only uses the Python standard library, nothing to install.
"""

import csv
import difflib
import ipaddress
import sys


# ---------------------------------------------------------------- subnet

def subnet_info(text):
    """Print the facts about one subnet, for example 10.10.8.0/22."""
    try:
        # strict=False lets you type a host address like 10.10.9.77/22
        net = ipaddress.ip_network(text, strict=False)
    except ValueError as err:
        print("Not a valid subnet:", err)
        return 1

    typed = text.split("/")[0]
    if typed != str(net.network_address):
        print(f"Note: {typed} is a host address, the subnet it belongs to is {net}")

    hosts = net.num_addresses - 2 if net.prefixlen < 31 else net.num_addresses
    print("Subnet:        ", net)
    print("Mask:          ", net.netmask)
    print("Wildcard mask: ", net.hostmask, " (used in ACLs and OSPF)")
    print("Network:       ", net.network_address)
    print("Broadcast:     ", net.broadcast_address)
    if net.prefixlen < 31:
        print("First host:    ", net.network_address + 1)
        print("Last host:     ", net.broadcast_address - 1)
    print("Usable hosts:  ", hosts)
    return 0


# ---------------------------------------------------------------- plan

def load_plan(path):
    """Read plan.csv. Returns a dict: name -> (network, gateway or None, vlan)."""
    plan = {}
    problems = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            try:
                net = ipaddress.ip_network(row["network"].strip())
            except ValueError as err:
                # the most common mistake: 10.10.10.0/22 is not a real /22 boundary
                problems.append(f"{name}: {row['network']} is not a valid subnet ({err})")
                continue
            gw = row["gateway"].strip()
            gw = ipaddress.ip_address(gw) if gw else None
            if name in plan:
                problems.append(f"{name}: name is used twice")
            plan[name] = (net, gw, row["vlan"].strip())
    return plan, problems


def check_plan(path):
    plan, problems = load_plan(path)

    # gateway must be a usable address inside its own subnet
    for name, (net, gw, vlan) in plan.items():
        if gw is None:
            continue
        if gw not in net:
            problems.append(f"{name}: gateway {gw} is not inside {net}")
        elif gw in (net.network_address, net.broadcast_address):
            problems.append(f"{name}: gateway {gw} is the network or broadcast address")

    # no two subnets may overlap
    names = list(plan)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if plan[a][0].overlaps(plan[b][0]):
                problems.append(f"{a} {plan[a][0]} overlaps {b} {plan[b][0]}")

    # the same VLAN number should not be used for two subnets
    seen = {}
    for name, (net, gw, vlan) in plan.items():
        if vlan and vlan in seen:
            problems.append(f"VLAN {vlan} is used by both {seen[vlan]} and {name}")
        if vlan:
            seen[vlan] = name

    print(f"{'name':<14}{'vlan':<6}{'subnet':<20}{'mask':<17}{'hosts':>6}  gateway")
    for name, (net, gw, vlan) in plan.items():
        hosts = net.num_addresses - 2 if net.prefixlen < 31 else net.num_addresses
        print(f"{name:<14}{vlan:<6}{str(net):<20}{str(net.netmask):<17}{hosts:>6}  {gw or '-'}")
    return report(problems, f"{len(plan)} subnets checked")


# ---------------------------------------------------------------- inventory

def check_inventory(inv_path, plan_path):
    plan, problems = load_plan(plan_path)
    names = set()
    used_ips = {}
    count = 0
    per_network = {}

    with open(inv_path, newline="") as f:
        for row in csv.DictReader(f):
            count += 1
            name = row["name"].strip()
            network = row["network"].strip()
            ip_text = row["ip"].strip()

            if name in names:
                problems.append(f"{name}: device name appears twice")
            names.add(name)

            if network not in plan:
                problems.append(f"{name}: network '{network}' is not in the plan")
                continue
            net, gw, vlan = plan[network]
            per_network[network] = per_network.get(network, 0) + 1

            if ip_text.lower() == "dhcp":
                continue                      # address comes from SRV-DHCP, nothing to check

            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError:
                problems.append(f"{name}: '{ip_text}' is not a valid IP address")
                continue

            if ip not in net:
                problems.append(f"{name}: {ip} is not in {network} {net}")
            elif net.prefixlen < 31 and ip in (net.network_address, net.broadcast_address):
                problems.append(f"{name}: {ip} is the network or broadcast address of {net}")
            if gw is not None and ip == gw:
                problems.append(f"{name}: {ip} is the gateway address of {network}")
            if ip in used_ips:
                problems.append(f"{name}: {ip} is already used by {used_ips[ip]}")
            used_ips[ip] = name

    # does every network have room for the devices in it?
    for network, n in sorted(per_network.items()):
        net = plan[network][0]
        room = net.num_addresses - 2 if net.prefixlen < 31 else net.num_addresses
        print(f"{network:<14}{n:>4} devices, {room} usable addresses")
        if n > room:
            problems.append(f"{network}: {n} devices do not fit in {net}")
    return report(problems, f"{count} devices checked")


# ---------------------------------------------------------------- compare

def clean_config(path):
    """Read a config and drop the lines that do not matter (comments and blanks)."""
    lines = []
    with open(path) as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("!"):
                continue
            lines.append(line)
    return lines


def compare(path_a, path_b):
    a = clean_config(path_a)
    b = clean_config(path_b)
    added = removed = 0
    for line in difflib.unified_diff(a, b, path_a, path_b, lineterm="", n=1):
        print(line)
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        if line.startswith("-") and not line.startswith("---"):
            removed += 1
    if added == 0 and removed == 0:
        print("The two configs are the same (ignoring comments).")
    else:
        print()
        print(f"{removed} lines only in {path_a}")
        print(f"{added} lines only in {path_b}")
    return 0


# ---------------------------------------------------------------- template

def room_switch_template(room, mgmt_ip, students=15):
    """Print the config for a 2960 classroom switch, same standard as the other rooms."""
    try:
        ip = ipaddress.ip_address(mgmt_ip)
    except ValueError:
        print(f"{mgmt_ip} is not a valid IP address")
        return 1
    if ip not in ipaddress.ip_network("10.10.99.0/24"):
        print(f"{mgmt_ip} is not in the NETWORK-IT VLAN 10.10.99.0/24")
        return 1
    if not 1 <= students <= 15:
        print("A room switch has ports Fa0/1 to Fa0/15 for students")
        return 1

    out = []
    add = out.append
    add(f"hostname SW-{room}")
    add("service password-encryption")
    add("enable secret RHSenable")
    add("username admin privilege 15 secret RHSadmin")
    add("no ip domain-lookup")
    add("ip domain-name rhs.lab")
    add("ip ssh version 2")
    add("lldp run")
    add("!")
    for number, name in ((10, "STUDENTS"), (20, "TEACHERS"), (99, "NETWORK-IT"),
                         (998, "PARKING"), (999, "NATIVE")):
        add(f"vlan {number}")
        add(f" name {name}")
    add("!")
    add("spanning-tree mode rapid-pvst")
    add("ip dhcp snooping vlan 10,20")
    add("no ip dhcp snooping information option")
    add("ip dhcp snooping")
    add("!")

    def access_port(port, description, vlan):
        add(f"interface FastEthernet0/{port}")
        add(f" description {description}")
        add(f" switchport access vlan {vlan}")
        add(" switchport mode access")
        add(" switchport port-security")
        add(" switchport port-security maximum 2")
        add(" switchport port-security mac-address sticky")
        add(" switchport port-security violation restrict")
        add(" ip dhcp snooping limit rate 15")
        add(" spanning-tree portfast")
        add(" spanning-tree bpduguard enable")
        add("!")

    for port in range(1, students + 1):
        access_port(port, f"Room {room} - student PC {port:02d}", 10)
    access_port(16, f"Room {room} - teacher PC", 20)

    # everything that is not used gets parked and shut
    first_unused = students + 1 if students < 15 else 17
    unused = [p for p in range(first_unused, 25) if p != 16]
    add(f"interface range FastEthernet0/{unused[0]} - {unused[-1]}"
        if 16 not in range(unused[0], unused[-1]) else
        f"interface range FastEthernet0/{unused[0]} - 15 , FastEthernet0/17 - 24")
    add(" switchport access vlan 998")
    add(" switchport mode access")
    add(" shutdown")
    add("!")

    for port, dist in ((1, "DIST-L3-1"), (2, "DIST-L3-2")):
        add(f"interface GigabitEthernet0/{port}")
        add(f" description Trunk to {dist}")
        add(" switchport trunk native vlan 999")
        add(" switchport trunk allowed vlan 10,20,99")
        add(" switchport mode trunk")
        add(" switchport nonegotiate")
        add(" ip dhcp snooping trust")
        add("!")

    add("interface Vlan1")
    add(" shutdown")
    add("interface Vlan99")
    add(f" description NETWORK-IT management - Room {room}")
    add(f" ip address {ip} 255.255.255.0")
    add(" no shutdown")
    add("ip default-gateway 10.10.99.1")
    add("!")
    add("access-list 10 permit 10.10.99.0 0.0.0.255")
    add("banner motd #RHS campus network (lab design). Authorized users only - activity is logged.#")
    add("logging 10.10.70.20")
    add("ntp server 10.10.70.20")
    add("line con 0")
    add(" exec-timeout 15 0")
    add(" logging synchronous")
    add(" login local")
    add("line vty 0 15")
    add(" access-class 10 in")
    add(" exec-timeout 10 0")
    add(" login local")
    add(" transport input ssh")
    add("end")
    print("\n".join(out))
    return 0


# ---------------------------------------------------------------- shared

def report(problems, summary):
    print()
    if problems:
        print(f"{summary}, {len(problems)} problem(s):")
        for p in problems:
            print("  -", p)
        return 1
    print(f"{summary}, no problems found.")
    return 0


def main(args):
    if len(args) >= 2 and args[0] == "subnet":
        return subnet_info(args[1])
    if len(args) == 2 and args[0] == "plan":
        return check_plan(args[1])
    if len(args) == 3 and args[0] == "inventory":
        return check_inventory(args[1], args[2])
    if len(args) == 3 and args[0] == "compare":
        return compare(args[1], args[2])
    if len(args) in (3, 4) and args[0] == "template":
        students = int(args[3]) if len(args) == 4 else 15
        return room_switch_template(args[1], args[2], students)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

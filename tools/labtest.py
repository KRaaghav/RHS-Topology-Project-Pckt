#!/usr/bin/env python3
"""
labtest.py - measurable tests and monitoring for the Packet Tracer lab

  python3 labtest.py              run every test and print the numbers
  python3 labtest.py --record     the same, and add the result to ../changes/health.csv
  python3 labtest.py history      the results recorded so far

Every test measures a number in the lab file and compares it with a target, for example
"hosts that still reach the ISP after any single failure: 142 of 142". The tests read the
cables and the configs inside the .pkt file. They do not start Packet Tracer, so they
cannot see live things like a ping. Those tests are in the table in README.md.

Recording a run after every change gives a history of the health of the lab over time.
The Monitor tab of netcheck_ui.py shows the same tests and that history.

Only uses the Python standard library, nothing to install.
"""

import csv
import datetime
import ipaddress
import os
import re
import sys

import pktconfig
from pktconfig import CONFIGS, HERE, LAB, Problem

HEALTH = os.path.join(HERE, "..", "changes", "health.csv")
DISTS = ["DIST-L3-1", "DIST-L3-2"]
BACKBONE = ["RHS-EDGE1", "RHS-EDGE2", "CORE-L3-1", "CORE-L3-2"] + DISTS
OUTSIDE = ["ISP", "INET-SRV"]              # not part of the school
USER_VLANS = [10, 20, 30, 70, 99]
DHCP_VLANS = [10, 20, 30]                  # the servers and the IT PCs have static addresses


# ---------------------------------------------------------------- reading the lab

class Picture:
    """What the tests need to know about the lab: devices, cables and configs."""

    def __init__(self, lab_path=LAB):
        lab = pktconfig.Lab(lab_path)
        xml = lab.xml()
        by_ref = {}
        self.devices = []
        for block in re.findall(r"<DEVICE>.*?</DEVICE>", xml, re.S):
            name = re.search(r"<NAME[^>]*>([^<]*)</NAME>", block).group(1)
            by_ref[re.search(r"save-ref-id:\d+", block).group(0)] = name
            self.devices.append(name)
        # every cable: (device, port, device, port)
        self.links = []
        for link in re.findall(r"<LINK>.*?</LINK>", xml, re.S):
            ends = re.findall(r"<(?:FROM|TO)>([^<]*)</(?:FROM|TO)>\s*<PORT>([^<]*)</PORT>", link)
            if len(ends) == 2 and all(ref in by_ref for ref, port in ends):
                self.links.append((by_ref[ends[0][0]], ends[0][1], by_ref[ends[1][0]], ends[1][1]))
        self.configs = {name: lab.config(name) for name in lab.names()}
        self.network = [n for n in self.configs if n not in OUTSIDE]       # the school's routers and switches
        self.access = [n for n in self.network if n.startswith("SW-")]
        # PCs and servers. The rack's power strips are devices too, but not part of the network
        self.hosts = [n for n in self.devices if n not in self.configs and n not in OUTSIDE
                      and not n.startswith("Power Distribution")]

    def section(self, device, header):
        """The lines under a header like 'interface Vlan10', without the leading space."""
        lines = self.configs[device]
        if header not in lines:
            return []
        start = lines.index(header)
        return [l.strip() for l in lines[start + 1:pktconfig.section_end(lines, start)]]

    def ports(self, device):
        """{port name: its config lines} for the real ports of a device."""
        return {l[10:]: self.section(device, l) for l in self.configs[device]
                if re.match(r"interface (Fast|Gigabit)Ethernet", l)}

    def cabled(self, device):
        """{port: (other device, other port)}"""
        found = {}
        for a, a_port, b, b_port in self.links:
            if a == device:
                found[a_port] = (b, b_port)
            if b == device:
                found[b_port] = (a, a_port)
        return found

    def reach_isp(self, dead_device=None, dead_link=None):
        """The devices that have a path of cables to the ISP when one thing is broken."""
        next_to = {}
        for i, (a, a_port, b, b_port) in enumerate(self.links):
            if i != dead_link and dead_device not in (a, b):
                next_to.setdefault(a, set()).add(b)
                next_to.setdefault(b, set()).add(a)
        seen = {"ISP"}
        todo = ["ISP"]
        while todo:
            for other in next_to.get(todo.pop(), ()):
                # a path does not go through a PC or a server
                if other not in seen:
                    seen.add(other)
                    if other in self.configs:
                        todo.append(other)
        return seen


def read_csv(name):
    with open(os.path.join(HERE, name), newline="") as f:
        return list(csv.DictReader(f))


def value_after(lines, start):
    """The rest of the first line that starts with this text, or None."""
    return next((l[len(start):].strip() for l in lines if l.startswith(start)), None)


# ---------------------------------------------------------------- the tests
# Every test returns (measured, target, lines of detail about what is wrong).

def test_drift(p):
    wrong = []
    for name in p.configs:
        path = os.path.join(CONFIGS, name + ".txt")
        if not os.path.exists(path):
            wrong.append(f"{name}: no file in configs/")
            continue
        with open(path) as f:
            if pktconfig.without_comments(f.read().splitlines()) != pktconfig.without_comments(p.configs[name]):
                wrong.append(f"{name}: lab and configs/{name}.txt differ")
    return len(p.configs) - len(wrong), len(p.configs), wrong


def test_two_uplinks(p):
    wrong = []
    for switch in p.access:
        uplinks = {other for other, port in p.cabled(switch).values() if other in DISTS}
        if len(uplinks) < 2:
            wrong.append(f"{switch}: uplink only to {', '.join(sorted(uplinks)) or 'nothing'}")
    return len(p.access) - len(wrong), len(p.access), wrong


def test_single_failure(p):
    """Break every backbone device and every cable between network devices, one at a time,
    and count the hosts that can still get to the ISP. The number is the worst case."""
    worst = len(p.hosts)
    wrong = []
    cases = [(name, name, None) for name in BACKBONE]
    for i, (a, a_port, b, b_port) in enumerate(p.links):
        if a in p.configs and b in p.configs:
            cases.append((f"cable {a} {a_port} - {b} {b_port}", None, i))
    for title, device, link in cases:
        alive = p.reach_isp(device, link)
        lost = [h for h in p.hosts if h not in alive]
        if lost:
            wrong.append(f"{title} fails: {len(lost)} hosts cut off ({', '.join(lost[:3])}...)")
        worst = min(worst, len(p.hosts) - len(lost))
    test_single_failure.cases = len(cases)
    return worst, len(p.hosts), wrong


def test_port_security(p):
    total = 0
    wrong = []
    for switch in p.access:
        ports = p.ports(switch)
        for port, (other, other_port) in p.cabled(switch).items():
            lines = ports.get(port, [])
            if other in p.hosts and re.fullmatch(r"(.*-PC\d+|.*-TCHR|.*-PC)", other):
                total += 1
                if "switchport port-security" not in lines:
                    wrong.append(f"{switch} {port} ({other}): no port security")
    return total - len(wrong), total, wrong


def test_edge_ports(p):
    """PortFast and BPDU guard on every port a host is plugged into."""
    total = 0
    wrong = []
    for switch in p.access:
        ports = p.ports(switch)
        for port, (other, other_port) in p.cabled(switch).items():
            if other in p.hosts:
                total += 1
                lines = ports.get(port, [])
                if "spanning-tree portfast" not in lines or "spanning-tree bpduguard enable" not in lines:
                    wrong.append(f"{switch} {port} ({other}): PortFast or BPDU guard missing")
    return total - len(wrong), total, wrong


def test_unused_ports(p):
    total = 0
    wrong = []
    for switch in p.network:
        cabled = p.cabled(switch)
        for port, lines in p.ports(switch).items():
            if port not in cabled:
                total += 1
                if "shutdown" not in lines:
                    wrong.append(f"{switch} {port}: no cable but not shut down")
    return total - len(wrong), total, wrong


def test_monitoring(p):
    """Syslog, NTP, SNMP and time stamps on every school device."""
    needed = {"logging 10.10.70.20": "syslog server", "ntp server 10.10.70.20": "NTP server",
              "snmp-server community": "SNMP", "service timestamps log datetime msec": "log time stamps"}
    wrong = []
    for name in p.network:
        missing = [what for start, what in needed.items() if value_after(p.configs[name], start) is None]
        if missing:
            wrong.append(f"{name}: no {', '.join(missing)}")
    return len(p.network) - len(wrong), len(p.network), wrong


def test_ssh_only(p):
    wrong = []
    for name in p.network:
        lines = p.configs[name]
        vty = [l.strip() for i, l in enumerate(lines) if l.startswith("line vty")
               for l in lines[i + 1:pktconfig.section_end(lines, i)]]
        if "ip ssh version 2" not in lines or "transport input ssh" not in vty or "transport input telnet" in vty:
            wrong.append(f"{name}: remote login is not SSH version 2 only")
    return len(p.network) - len(wrong), len(p.network), wrong


def test_gateways(p):
    """Every VLAN has the same HSRP gateway on both distribution switches, and it is the one in plan.csv."""
    plan = {row["vlan"]: row["gateway"] for row in read_csv("plan.csv")}
    wrong = []
    for vlan in USER_VLANS:
        found = [value_after(p.section(d, f"interface Vlan{vlan}"), f"standby {vlan} ip ") for d in DISTS]
        if found != [plan.get(str(vlan))] * 2:
            wrong.append(f"VLAN {vlan}: gateway should be {plan.get(str(vlan))} on both, found {found}")
    return len(USER_VLANS) - len(wrong), len(USER_VLANS), wrong


def test_root_matches_gateway(p):
    """The switch that is the HSRP gateway of a VLAN should also be its spanning tree root,
    or traffic takes a detour through the other distribution switch."""
    wrong = []
    for vlan in USER_VLANS:
        hsrp = {}
        stp = {}
        for d in DISTS:
            priority = value_after(p.section(d, f"interface Vlan{vlan}"), f"standby {vlan} priority ")
            hsrp[d] = int(priority or 100)
            stp[d] = 32768
            for line in p.configs[d]:
                match = re.fullmatch(r"spanning-tree vlan (\S+) priority (\d+)", line)
                if match and vlan in pktconfig.number_list(match.group(1)):
                    stp[d] = int(match.group(2))
        active = max(DISTS, key=lambda d: hsrp[d])
        root = min(DISTS, key=lambda d: stp[d])
        if active != root or hsrp[DISTS[0]] == hsrp[DISTS[1]] or stp[DISTS[0]] == stp[DISTS[1]]:
            wrong.append(f"VLAN {vlan}: HSRP active is {active}, spanning tree root is {root}")
    return len(USER_VLANS) - len(wrong), len(USER_VLANS), wrong


def test_dhcp_relay(p):
    total = 0
    wrong = []
    for vlan in DHCP_VLANS:
        for d in DISTS:
            total += 1
            if value_after(p.section(d, f"interface Vlan{vlan}"), "ip helper-address ") != "10.10.70.5":
                wrong.append(f"{d} Vlan{vlan}: no ip helper-address 10.10.70.5")
    return total - len(wrong), total, wrong


def test_trunks(p):
    """Both ends of a trunk cable must allow the same VLANs and use the same native VLAN."""
    total = 0
    wrong = []
    for a, a_port, b, b_port in p.links:
        if a not in p.network or b not in p.network:
            continue
        ends = [p.ports(a).get(a_port, []), p.ports(b).get(b_port, [])]
        if not any("switchport mode trunk" in lines for lines in ends):
            continue
        total += 1
        allowed = [value_after(lines, "switchport trunk allowed vlan ") for lines in ends]
        native = [value_after(lines, "switchport trunk native vlan ") for lines in ends]
        if allowed[0] != allowed[1] or native[0] != native[1] or None in allowed:
            wrong.append(f"{a} {a_port} - {b} {b_port}: allowed {allowed[0]} / {allowed[1]}, native {native[0]} / {native[1]}")
    return total - len(wrong), total, wrong


def test_host_vlans(p):
    """Every PC and server is plugged into a port of the VLAN the inventory says it is in."""
    vlan_of = {row["name"]: row["vlan"] for row in read_csv("plan.csv")}
    wanted = {row["name"]: vlan_of.get(row["network"]) for row in read_csv("inventory.csv")}
    wrong = []
    for host in p.hosts:
        port = next(((a, a_port) if b == host else (b, b_port)
                     for a, a_port, b, b_port in p.links if host in (a, b)), None)
        if port is None or port[0] not in p.configs:
            wrong.append(f"{host}: not plugged into a switch")
            continue
        vlan = value_after(p.ports(port[0]).get(port[1], []), "switchport access vlan ")
        if host not in wanted:
            wrong.append(f"{host}: not in inventory.csv")
        elif vlan != wanted[host]:
            wrong.append(f"{host}: on {port[0]} {port[1]} in VLAN {vlan}, should be VLAN {wanted[host]}")
    return len(p.hosts) - len(wrong), len(p.hosts), wrong


def test_address_room(p):
    """How full the fullest subnet is, in percent. Under 50 leaves room to double."""
    networks = {row["name"]: ipaddress.ip_network(row["network"]) for row in read_csv("plan.csv")
                if row["vlan"] and row["gateway"]}
    counts = {}
    for row in read_csv("inventory.csv"):
        counts[row["network"]] = counts.get(row["network"], 0) + 1
    fullest = 0
    wrong = []
    for name, net in networks.items():
        percent = round(100 * (counts.get(name, 0) + 3) / (net.num_addresses - 2))     # + gateway and the two DIST
        fullest = max(fullest, percent)
        if percent > 50:
            wrong.append(f"{name} {net}: {percent}% of the addresses are used")
    return fullest, 50, wrong


# (id, group, what is measured, unit, test, True when a lower number is better)
TESTS = [
    ("single-failure", "Redundancy", "Hosts that still reach the ISP after any single failure", "hosts", test_single_failure, False),
    ("two-uplinks", "Redundancy", "Access switches cabled to both distribution switches", "switches", test_two_uplinks, False),
    ("gateways", "Redundancy", "VLANs with the same HSRP gateway on both distribution switches", "VLANs", test_gateways, False),
    ("root-gateway", "Redundancy", "VLANs where the spanning tree root is also the HSRP active switch", "VLANs", test_root_matches_gateway, False),
    ("trunks", "Switching", "Trunk cables with the same allowed and native VLANs on both ends", "trunks", test_trunks, False),
    ("host-vlans", "Switching", "PCs and servers plugged into a port of the right VLAN", "hosts", test_host_vlans, False),
    ("dhcp-relay", "Switching", "Gateway interfaces that relay DHCP to SRV-DHCP", "interfaces", test_dhcp_relay, False),
    ("address-room", "Switching", "Fullest subnet (lower is better)", "% used", test_address_room, True),
    ("port-security", "Security", "PC ports with port security", "ports", test_port_security, False),
    ("edge-ports", "Security", "Host ports with PortFast and BPDU guard", "ports", test_edge_ports, False),
    ("unused-ports", "Security", "Ports without a cable that are shut down", "ports", test_unused_ports, False),
    ("ssh-only", "Security", "Devices that only allow SSH version 2 for remote login", "devices", test_ssh_only, False),
    ("monitoring", "Monitoring", "Devices that send logs to SRV-LOG, use NTP and answer SNMP", "devices", test_monitoring, False),
    ("drift", "Monitoring", "Device configs in the lab that match the configs folder", "devices", test_drift, False),
]


def run(lab_path=LAB):
    """Run every test. Returns a dict with the results, ready for json."""
    p = Picture(lab_path)
    results = []
    for test_id, group, title, unit, test, lower_is_better in TESTS:
        measured, target, wrong = test(p)
        passed = measured <= target if lower_is_better else measured >= target
        results.append({"id": test_id, "group": group, "title": title, "unit": unit, "measured": measured,
                        "target": target, "lower_is_better": lower_is_better, "passed": passed and not wrong,
                        "detail": wrong[:12] + ([f"... and {len(wrong) - 12} more"] if len(wrong) > 12 else [])})
    passed = sum(r["passed"] for r in results)
    return {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tests": results,
            "passed": passed, "total": len(results), "score": round(100 * passed / len(results)),
            "counts": {"devices": len(p.devices), "network devices": len(p.network), "hosts": len(p.hosts),
                       "cables": len(p.links), "failures tried": test_single_failure.cases}}


# ---------------------------------------------------------------- the history

def record(result):
    """Add one line to ../changes/health.csv: the time, the score and every measured number."""
    os.makedirs(os.path.dirname(HEALTH), exist_ok=True)
    header = ["time", "score", "passed", "total", "devices", "cables"] + [t[0] for t in TESTS]
    rows = history()
    row = {"time": result["time"], "score": result["score"], "passed": result["passed"], "total": result["total"],
           "devices": result["counts"]["devices"], "cables": result["counts"]["cables"]}
    row.update({t["id"]: t["measured"] for t in result["tests"]})
    with open(HEALTH, "w", newline="") as f:
        writer = csv.DictWriter(f, header, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows + [row])


def history():
    """The recorded runs, oldest first."""
    if not os.path.exists(HEALTH):
        return []
    with open(HEALTH, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- commands

def show(result):
    group = None
    for t in result["tests"]:
        if t["group"] != group:
            group = t["group"]
            print(f"\n{group}")
        sign = "<=" if t["lower_is_better"] else "of"
        number = f"{t['measured']} {sign} {t['target']} {t['unit']}"
        print(f"  {'PASS' if t['passed'] else 'FAIL'}  {t['title']:<68} {number}")
        for line in t["detail"]:
            print(f"          {line}")
    c = result["counts"]
    print(f"\n{result['passed']} of {result['total']} tests passed, score {result['score']}%.")
    print(f"Lab: {c['devices']} devices ({c['network devices']} routers and switches, {c['hosts']} PCs and "
          f"servers), {c['cables']} cables. {c['failures tried']} single failures tried.")


def main(args):
    try:
        if args == ["history"]:
            rows = history()
            if not rows:
                print("Nothing recorded yet. Run: python3 labtest.py --record")
            for row in rows:
                print(f"{row['time']}  score {row['score']:>3}%  {row['passed']}/{row['total']} tests  "
                      f"{row['devices']} devices")
            return 0
        if args not in ([], ["--record"]):
            print(__doc__)
            return 2
        result = run()
        show(result)
        if args:
            record(result)
            print("Recorded in changes/health.csv")
        return 0 if result["passed"] == result["total"] else 1
    except Problem as err:
        print("Problem:", err)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

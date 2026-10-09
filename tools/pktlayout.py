#!/usr/bin/env python3
"""
pktlayout.py - tidy the canvas of the Packet Tracer lab

It does three things to the logical view, without touching any device config:

  - puts every device on a grid: internet, edge, core and distribution in the middle
    at the top, one box per room underneath with the switch above its PCs
  - draws a coloured box behind every layer and every room
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

import html
import os
import re
import sys
import uuid

import pktfile
from pktconfig import LAB, Problem, backup_lab, packet_tracer_is_open

# ---------------------------------------------------------------- where everything goes
# All numbers are pixels on the canvas. A device position is the middle of its icon.

ROOM_WIDTH = 600
ROOM_STEP = 660                 # room width plus the gap to the next room
ROOMS_TOP, ROOMS_BOTTOM = 930, 1810
FIRST_ROOM_LEFT = 60
SWITCH_Y = 1060
PC_ROWS = [1220, 1370, 1520, 1670]
MIDDLE = 2670                   # the routers and layer 3 switches are centred on this line
LAYER_LEFT, LAYER_RIGHT = 2280, 3060

# colours of the boxes (red, green, blue)
GREY, RED, PURPLE, BLUE = (232, 232, 232), (255, 216, 216), (228, 218, 255), (208, 226, 255)
GREEN, YELLOW, CYAN = (208, 248, 208), (255, 255, 176), (184, 248, 248)

# (name on the room note, access switch, colour, PCs from left to right and top to bottom)
ROOMS = [("Main office + counseling\nVLAN 30 MANAGEMENT", "SW-OFFICE", GREEN,
          ["PRINCIPAL-PC", "ASST-PRINCIPAL-PC", "COUNSELOR1-PC", "COUNSELOR2-PC", "REGISTRAR-PC", "FRONT-OFFICE-PC"])]
for room in ("E230", "E110", "E103", "E203", "C214", "B126"):
    ROOMS.append((f"Room {room}\nVLAN 10 students (15), VLAN 20 teacher", "SW-" + room, YELLOW,
                  [f"{room}-PC{n:02d}" for n in range(1, 16)] + [room + "-TCHR"]))
ROOMS.append(("MDF (server room) + IT office\nVLAN 70 SERVERS, VLAN 99 NETWORK-IT", "SW-MDF", CYAN,
              ["SRV-DHCP", "SRV-DNS-WEB", "SRV-LOG", "SRV-FILE", "IT-PC1", "IT-PC2"]))

# the layers in the middle: (y, colour, {device: x})
LAYERS = [(80, GREY, {"ISP": MIDDLE, "INET-SRV": MIDDLE + 290}),
          (310, RED, {"RHS-EDGE1": MIDDLE - 240, "RHS-EDGE2": MIDDLE + 240}),
          (540, PURPLE, {"CORE-L3-1": MIDDLE - 240, "CORE-L3-2": MIDDLE + 240}),
          (770, BLUE, {"DIST-L3-1": MIDDLE - 240, "DIST-L3-2": MIDDLE + 240})]


# ---------------------------------------------------------------- the text on the canvas
# (x, y, text). Lines are kept under about 72 characters so the columns do not run into
# each other. Four columns at the top (x = 60, 1100, 3300, 4300), three notes at the bottom.
# The notes at the top end above y = 700, so the uplinks to the rooms do not run through them.

NOTES = [
    (60, 15, """RHS CAMPUS NETWORK - CCNA project (Packet Tracer 9.0)
My own design for part of a high school network, using six rooms
at Redmond High School. It is NOT the real RHS network.

WHAT THIS LAB DOES
- connects 90 student PCs, 6 teacher PCs, 6 office PCs, 2 IT PCs and
  4 servers in six classrooms, the main office and the server room
- keeps students, teachers, office staff and IT apart in their own
  VLANs, with ACLs that decide who can reach what
- gives every PC its address from one DHCP server (SRV-DHCP)
- takes everyone to the internet through NAT on two edge routers
- keeps working when any one router, layer 3 switch or uplink
  cable between a room and the internet fails
Three layers like the Cisco campus model: core, distribution, access."""),

    (60, 470, """HOW A PACKET GETS OUT (E230-PC01 opens www.example.com)
1. PC asks SRV-DHCP for an address. DIST relays it (ip helper-address)
2. PC sends to its gateway 10.10.8.1, the HSRP address on DIST-L3-1
3. ACL STUDENTS-IN on interface Vlan10 checks it: internet is allowed
4. DIST routes it to a core switch, the core to an edge router (OSPF)
5. RHS-EDGE1 swaps the 10.x address for its public one (PAT) and
   sends it to the ISP. The answer comes back the same way.
Watch it hop by hop in Simulation mode (bottom right corner)."""),

    (1100, 15, """INTERNET (simulated)
ISP router with loopback 8.8.8.8 as a ping target.
INET-SRV is www.example.com (198.51.100.10).
Public addresses are from the documentation ranges."""),

    (1100, 170, """EDGE ROUTERS (2911) - RHS-EDGE1 and RHS-EDGE2
Connect the school to the ISP. Two routers and two ISP links,
so one can fail. EDGE2 is the backup (default route metric 100).
ip nat inside source list 1 interface g0/0/0 overload (PAT)
ip nat inside source static (school website 203.0.113.10)
ip access-group OUTSIDE-IN in, default-information originate"""),

    (1100, 380, """CORE LAYER (3650) - CORE-L3-1 and CORE-L3-2
Only routes between the edge and the distribution layer.
No user VLANs and no ACLs here, so it stays simple and fast.
ip routing, no switchport + ip address on each link
router ospf 1 (area 0), channel-group 1 mode active (LACP)"""),

    (1100, 560, """DISTRIBUTION LAYER (3650) - DIST-L3-1 and DIST-L3-2
Default gateway of every VLAN. All rules between VLANs are here.
DIST-L3-1 is HSRP active + STP root for VLAN 10, 70, 99.
DIST-L3-2 is HSRP active + STP root for VLAN 20, 30.
interface vlan + standby (gateway .1), ip helper-address
ip access-list extended + ip access-group in, router ospf 1"""),

    (3300, 15, """ACCESS LAYER - one 2960 per room, office and MDF are 3650 as layer 2
Where the PCs plug in. Fa0/1-15 students, Fa0/16 teacher.
One trunk to each distribution switch (Gi0/1 and Gi0/2).
Spanning tree blocks one of them per VLAN, so there is no loop.
switchport mode access, switchport access vlan
switchport mode trunk, switchport trunk allowed vlan 10,20,99"""),

    (3300, 230, """VLANS AND SUBNETS
10  STUDENTS     10.10.8.0/22     20  TEACHERS   10.10.20.0/24
30  MANAGEMENT   10.10.30.0/24    70  SERVERS    10.10.70.0/24
99  NETWORK-IT   10.10.99.0/24    998 unused ports, 999 native
Gateway is always .1 (HSRP), DIST-L3-1 is .2 and DIST-L3-2 is .3.
Links between routers are /30s from 10.10.0.0, OSPF single area 0."""),

    (3300, 450, """WHO CAN REACH WHAT (ACLs on the distribution switches)
Students:    internet, the school website and DNS only
Teachers:    servers, students, internet. Not management or IT
Management:  everything except the IT VLAN
Network IT:  everything, and the only VLAN that may SSH to devices
Servers:     may answer, may not start a connection into the school
Internet:    only the school web server, on port 80 and 443"""),

    (1300, 1840, """LOGINS (every router and switch, console included)
user admin / RHSadmin, enable secret RHSenable
SSH from IT-PC1 after typing: crypto key generate rsa (1024)"""),

    (4300, 15, """REDUNDANCY - what takes over when something fails
ISP link 1 or RHS-EDGE1    -> RHS-EDGE2 (OSPF default route)
a core switch              -> the other core (OSPF)
a distribution switch      -> the other one (HSRP moves gateway .1)
an uplink of a room switch -> its other uplink (Rapid PVST+)
one cable of a bundle      -> the other cable (LACP EtherChannel)
EtherChannels: core to core, dist to dist, SW-MDF to each dist."""),

    (4300, 255, """SECURITY ON THE ACCESS SWITCHES
PortFast + BPDU guard and sticky port security (max 2 MACs)
DHCP snooping, only the uplinks may answer DHCP
unused ports are shut down and parked in VLAN 998
native VLAN 999 is empty, trunks do not negotiate
SSH version 2 only, and only from the IT VLAN (access-class 10)"""),

    (4300, 470, """THINGS TO TRY (wait a minute after opening for green links)
E230-PC01: ipconfig -> 10.10.8.x, gateway 10.10.8.1
E230-PC01: ping C214-PC01 works, ping a teacher PC fails
E230-PC01: browser www.rhs.lab works, ftp 10.10.70.30 fails
E230-PC01: ping 8.8.8.8 works (NAT on the edge)
IT-PC1: ping anything, ssh -l admin 10.10.99.11
DIST-L3-1: show standby brief, show etherchannel summary
Break it: shutdown g0/0/0 on RHS-EDGE1 while a ping -t runs"""),

    (60, 1840, """SERVERS (VLAN 70, static addresses)
SRV-DHCP 10.10.70.5 (DHCP for VLAN 10, 20, 30)     SRV-DNS-WEB 10.10.70.10 (DNS + www.rhs.lab)
SRV-LOG 10.10.70.20 (syslog + NTP)                 SRV-FILE 10.10.70.30 (FTP for staff)
IT-PC1 10.10.99.50, IT-PC2 10.10.99.51. Switch management: 10.10.99.11-16 rooms, .21 office, .22 MDF"""),

    (2200, 1840, """MORE IN THE PROJECT FOLDER
README.md explains every design choice, WALKTHROUGH.md builds it step by step.
configs/ has the config of every device with comments. tools/ has the Python programs
that check the addressing plan and write config changes straight into this file."""),

    (3300, 1840, """CHANGE CONFIGS WITH BUTTONS (NetCheck)
Packet Tracer cannot start other programs, so this is not a real button.
1. Save and close this lab.   2. Double click "Start NetCheck.command"
(in the tools folder). The page opens at http://127.0.0.1:8765
3. Make the change there, then press "Open in Packet Tracer" on the page."""),
]


def positions():
    """{device name: (x, y)} for every device the layout knows."""
    where = {}
    for y, colour, devices in LAYERS:
        for name, x in devices.items():
            where[name] = (x, y)
    for number, (title, switch, colour, pcs) in enumerate(ROOMS):
        left = FIRST_ROOM_LEFT + number * ROOM_STEP
        where[switch] = (left + ROOM_WIDTH // 2, SWITCH_Y)
        columns = 4 if len(pcs) > 6 else 2             # 16 PCs in a room, 6 in the office and MDF
        for i, pc in enumerate(pcs):
            x = left + ROOM_WIDTH * (2 * (i % columns) + 1) // (2 * columns)
            where[pc] = (x, PC_ROWS[i // columns])
    return where


def boxes():
    """(left, top, right, bottom, colour) of every coloured box."""
    found = [(LAYER_LEFT, y - 70, LAYER_RIGHT, y + 70, colour) for y, colour, devices in LAYERS]
    for number, (title, switch, colour, pcs) in enumerate(ROOMS):
        left = FIRST_ROOM_LEFT + number * ROOM_STEP
        found.append((left, ROOMS_TOP, left + ROOM_WIDTH, ROOMS_BOTTOM, colour))
    return found


def notes():
    """(x, y, text) of every note: the big ones above and one title per room. The title is
    at the bottom of the room box, because the uplinks come into the box from the top."""
    found = list(NOTES)
    for number, (title, switch, colour, pcs) in enumerate(ROOMS):
        found.append((FIRST_ROOM_LEFT + number * ROOM_STEP + 10, ROOMS_BOTTOM - 65, title))
    return found


# ---------------------------------------------------------------- writing it into the file

def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box_xml(number, box):
    left, top, right, bottom, (red, green, blue) = box
    # Packet Tracer saves the bottom right corner under the name TopLeft and the other way round
    return f"""<RECTANGLE uuid="{{{uuid.uuid4()}}}">
    <TopLeftX>{right}</TopLeftX>
    <TopLeftY>{bottom}</TopLeftY>
    <BottomRightX>{left}</BottomRightX>
    <BottomRightY>{top}</BottomRightY>
    <Color>
     <Red>{red}</Red>
     <Green>{green}</Green>
     <Blue>{blue}</Blue>
    </Color>
    <Filled OUTLINECOLOR="#000000" OUTLINED="true">1</Filled>
    <RECTCLUSTERID>1-1</RECTCLUSTERID>
    <MEM_ADDR>{140200000000000 + number * 4096}</MEM_ADDR>
    <DevicePlacement_ShapeName />
    <DevicePlacement_ShapeX>{(left + right) / 2:.1f}</DevicePlacement_ShapeX>
    <DevicePlacement_ShapeY>{(top + bottom) / 2:.1f}</DevicePlacement_ShapeY>
    <DevicePlacement_ShapeZ>0.21</DevicePlacement_ShapeZ>
   </RECTANGLE>"""


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
    for x, y, text in NOTES:
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


def arrange(lab_path=LAB, write=True):
    """Returns the lines of a short report."""
    try:
        xml = pktfile.read_pkt(lab_path).decode("utf-8")
    except FileNotFoundError:
        raise Problem(f"Lab file not found: {lab_path}")
    except (ValueError, OSError) as err:
        raise Problem(f"Cannot read {os.path.basename(lab_path)}: {err}")

    where = positions()
    report = []
    seen = set()

    def move(match):
        device = match.group(0)
        name = html.unescape(re.search(r"<NAME[^>]*>([^<]*)</NAME>", device).group(1))
        spot = re.search(r"(<LOGICAL>\s*<X>)([^<]*)(</X>\s*<Y>)([^<]*)(</Y>)", device)
        if name not in where or not spot:
            if float(spot.group(2)) < 3800 and float(spot.group(4)) < 3000:    # it is on the part we arrange
                report.append(f"{name} is not in the layout, it stays where it is.")
            return device
        seen.add(name)
        x, y = where[name]
        if (round(float(spot.group(2))), round(float(spot.group(4)))) != (x, y):
            report.append(f"{name:<18} {spot.group(2):>5},{spot.group(4):<5} -> {x},{y}")
        return device[:spot.start()] + f"{spot.group(1)}{x}{spot.group(3)}{y}{spot.group(5)}" + device[spot.end():]

    xml = re.sub(r"<DEVICE>.*?</DEVICE>", move, xml, flags=re.S)
    moved = len(report)
    for name in sorted(set(where) - seen):
        report.append(f"{name} is in the layout but not in the lab.")

    all_boxes = "\n   ".join(box_xml(i, b) for i, b in enumerate(boxes()))
    all_notes = "\n    ".join(note_xml(i, n) for i, n in enumerate(notes()))
    xml = replace_once(xml, r"\n <RECTANGLES>.*?</RECTANGLES>|\n <RECTANGLES />",
                       f"\n <RECTANGLES>\n   {all_boxes}\n  </RECTANGLES>", "coloured boxes")
    xml = replace_once(xml, r"(?<=</GRID_COLOR>)(\s*)(?:<NOTES>.*?</NOTES>|<NOTES />)",
                       f"\n   <NOTES>\n    {all_notes}\n    </NOTES>", "canvas notes")
    xml = replace_once(xml, r"(?<=<SHAPETESTS />)(\s*)<DESCRIPTION translate=\"true\">.*?</DESCRIPTION>",
                       f'\n   <DESCRIPTION translate="true">{escape(description_html())}</DESCRIPTION>',
                       "lab description")
    report.append(f"{moved} device(s) moved, {len(boxes())} boxes, {len(notes())} notes, description written.")

    if write:
        backup = backup_lab(lab_path)
        pktfile.write_pkt(lab_path + ".tmp", xml.encode("utf-8"))
        os.replace(lab_path + ".tmp", lab_path)
        report.append(f"Written to {os.path.basename(lab_path)}. The file from before is in changes/backups/{backup}")
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

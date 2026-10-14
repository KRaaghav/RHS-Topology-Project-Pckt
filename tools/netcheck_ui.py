#!/usr/bin/env python3
"""
netcheck_ui.py - a simple window for the network tools

Run it with:   python3 netcheck_ui.py
(or double click "Start NetCheck.command")

It starts a tiny web server that only this computer can reach and opens the page in the
browser. The page is in the ui folder next to this file. It is written with React, but
React is saved in ui/vendor, so nothing has to be installed and it works without internet.
The buttons on the page call the same functions as netcheck.py, netconfig.py, pktconfig.py,
pktlayout.py, pktbuild.py and labtest.py, so there is no second copy of the logic.

The page has six pages:

  Overview   health score, counts, the topology (click to break a device) and the building in 3D
  Lab        the routers and switches inside the Packet Tracer file, click one to read its config
  Configure  pick devices and a change, see what it would do, write it into the lab
  Monitor    measurable tests of the lab with a score, and the history of that score
  Checks     subnet calculator, plan and inventory checks, compare configs, new room switch
  History    every change that was made, and the copies of the lab to go back to

Close the Terminal window (or press Ctrl+C) to stop it.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import diagram
import floorplan
import labtest
import netcheck
import netconfig
import pktbuild
import pktconfig
import pktlayout

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIGS = os.path.join(HERE, "..", "configs")
UI = os.path.join(HERE, "ui")                      # the page itself: index.html, style.css and the .js files
KINDS = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}
PORT = 8765


def config_names():
    """The device configs that can be picked in the compare box."""
    return sorted(f[:-4] for f in os.listdir(CONFIGS) if f.endswith(".txt"))


def run(command, values):
    """Run one netcheck function and return everything it printed as text."""
    plan = os.path.join(HERE, "plan.csv")
    inventory = os.path.join(HERE, "inventory.csv")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):          # catch the print() output
        try:
            if command == "subnet":
                netcheck.subnet_info(values.get("subnet", "").strip())
            elif command == "plan":
                netcheck.check_plan(plan)
            elif command == "inventory":
                netcheck.check_inventory(inventory, plan)
            elif command == "compare":
                a, b = values.get("a"), values.get("b")
                if a not in config_names() or b not in config_names():
                    print("Pick two devices from the lists.")
                else:
                    os.chdir(CONFIGS)              # so the output shows short file names
                    netcheck.compare(a + ".txt", b + ".txt")
            elif command == "template":
                room = values.get("room", "").strip().upper()
                students = values.get("students", "15").strip() or "15"
                if not room.isalnum():
                    print("Type a room number like E231.")
                elif not students.isdigit():
                    print("Student PCs has to be a number from 1 to 15.")
                else:
                    netcheck.room_switch_template(room, values.get("ip", "").strip(), int(students))
            else:
                print("Unknown command.")
        except Exception as err:                   # show the error on the page instead of crashing
            print("Error:", err)
    return out.getvalue()


def page_data():
    """What the Configure tab needs to draw itself: devices, groups and the list of changes."""
    changes = [{"id": c["id"], "title": c["title"], "help": c["help"], "fields": c["fields"]}
               for c in netconfig.CATALOG]
    return {"devices": netconfig.load_devices(), "groups": netconfig.GROUPS, "changes": changes,
            "configs": config_names()}


def configure(body, write, lab=False):
    """Build the scripts for the chosen devices. The answer always says what the change does
    to each config in the lab. With write=True the scripts are also saved to files, with
    lab=True they are also written into the Packet Tracer lab file."""
    devices = body.get("devices") or []
    change, values = body.get("change"), body.get("values") or {}
    if lab:
        title, scripts, notes, folder, changes = netconfig.apply(devices, change, values)
        return {"title": title, "scripts": scripts, "notes": notes, "folder": folder, "changes": changes,
                "written": True}
    if write:
        title, scripts, notes, folder = netconfig.save(devices, change, values)
    else:
        title, scripts, notes = netconfig.build(devices, change, values)
        folder = None
    result = pktconfig.apply(scripts, write=False) if scripts else {"changes": {}, "notes": []}
    return {"title": title, "scripts": scripts, "notes": notes + result["notes"], "folder": folder,
            "changes": result["changes"], "written": False}


def lab_overview():
    """The Lab tab: every router and switch in the .pkt file, with its layer from the inventory."""
    known = {d["name"]: d for d in netconfig.load_devices()}
    rows = pktconfig.overview()
    for row in rows:
        device = known.get(row["name"], {})
        row["group"] = device.get("group") or "outside"
        row["type"] = device.get("type", "")
        row["location"] = device.get("location", "")
        row["ip"] = device.get("ip", "")
    return {"devices": rows, "packet_tracer_open": pktconfig.packet_tracer_is_open(),
            "file": os.path.basename(pktconfig.LAB)}


def open_lab():
    """Open the lab file the same way a double click on it would."""
    lab = os.path.abspath(pktconfig.LAB)
    if sys.platform == "darwin":
        subprocess.run(["open", lab], check=False)
    elif sys.platform == "win32":
        os.startfile(lab)
    else:
        subprocess.run(["xdg-open", lab], check=False)


def action(path, body):
    """Everything the page can ask for with a POST. Returns something json can pack."""
    if path == "/preview":
        return configure(body, write=False)
    if path == "/save":
        return configure(body, write=True)
    if path == "/apply":
        return configure(body, write=True, lab=True)
    if path == "/lab":
        return lab_overview()
    if path == "/config":
        return {"name": body.get("device"), "text": "\n".join(pktconfig.Lab().config(body.get("device", "")))}
    if path == "/history":
        return {"changes": netconfig.history(), "backups": pktconfig.backups()}
    if path == "/restore":
        kept = pktconfig.restore(body.get("backup", ""))
        return {"message": f"{body.get('backup')} is the lab again. The lab from just before was kept as {kept}."}
    if path == "/open":
        open_lab()
        return {"message": "Opening the lab in Packet Tracer."}
    if path == "/health":
        result = labtest.run()
        if body.get("record"):
            labtest.record(result)
        result["history"] = labtest.history()[-40:]
        return result
    if path == "/graph":
        return graph()
    if path == "/fail":
        return fail(body.get("device", ""))
    if path == "/add-room":
        report = pktbuild.add_room(body.get("room", ""), label=body.get("label", ""))
        for module in (diagram, floorplan):        # the pictures in the README show the new room too
            with open(module.OUT, "w") as f:
                f.write(module.svg())
        return {"message": " ".join(report[:2])}
    if path == "/layout":
        report = pktlayout.arrange()
        return {"message": next(line for line in report if line.startswith("Written")).replace(
            "Written to", "Canvas arranged in")}
    return {"error": "Unknown request."}


def graph():
    """What the page needs to draw the topology and the building: the layers, the access
    switches with what is plugged into them, the cables between routers and switches, the
    VLANs and the wings. All of it is read from the lab file, plan.csv and inventory.csv."""
    p = labtest.Picture()
    labels = pktlayout.room_labels()
    order = [room[1] for room in pktlayout.rooms()]
    access = []
    for switch in sorted(p.access, key=lambda name: order.index(name) if name in order else len(order)):
        ports = p.ports(switch)
        counts, uplinks = {}, []
        for port, (other, other_port) in sorted(p.cabled(switch).items()):
            if other in p.hosts:
                vlan = labtest.value_after(ports.get(port, []), "switchport access vlan ") or "?"
                counts[vlan] = counts.get(vlan, 0) + 1
            elif other not in uplinks:
                uplinks.append(other)
        kind = "office" if switch == "SW-OFFICE" else "mdf" if switch == "SW-MDF" else "room"
        room = switch[3:]
        label = {"office": "Main office", "mdf": "Server room, IT"}.get(kind) or labels.get(room) or f"floor {room[1]}"
        access.append({"name": switch, "kind": kind, "room": room, "label": label, "named": labels.get(room, ""),
                       "wing": room[0] if kind == "room" else "", "floor": room[1] if kind == "room" else "1",
                       "counts": counts, "uplinks": sorted(uplinks)})

    layers = [{"title": title.split("\n")[0], "note": title.partition("\n")[2], "names": names}
              for title, y, names in diagram.ROWS]
    drawn = {name for layer in layers for name in layer["names"]} | set(p.access)
    pairs = {}
    for a, a_port, b, b_port in p.links:
        if a in drawn and b in drawn:
            pairs[tuple(sorted((a, b)))] = pairs.get(tuple(sorted((a, b))), 0) + 1
    wings = pktlayout.wings()
    spans = [{"wing": wing, "rooms": [a["room"] for a in access if a["wing"] == wing]} for wing in wings]
    vlans = [{"vlan": row["vlan"], "name": row["name"], "network": row["network"], "gateway": row["gateway"]}
             for row in labtest.read_csv("plan.csv") if row["vlan"] and row["gateway"]]
    return {"layers": layers, "access": access, "wings": wings, "spans": spans, "vlans": vlans,
            "links": [{"a": a, "b": b, "count": count} for (a, b), count in sorted(pairs.items())]}


def fail(device):
    """Switch one router or switch off and say who still has a path of cables to the ISP.
    This is the same search the single failure test in labtest.py does."""
    p = labtest.Picture()
    if device not in p.devices or device in p.hosts:
        raise netconfig.Problem(f"{device} is not a router or switch in the lab.")
    alive = p.reach_isp(dead_device=device)
    lost = sorted(host for host in p.hosts if host not in alive)
    cut = sorted(name for name in p.configs if name not in alive and name != device)
    if device == "ISP":
        why = "The ISP is the internet in this lab, so everything behind it is cut off."
    elif lost and device in p.access:
        why = "A room switch is the one thing without a backup: only what is plugged into it is cut off, every other room keeps working."
    elif lost:
        why = "There is no second path around this device."
    else:
        why = "There is a second device of the same kind next to it, and the traffic goes through that one."
    return {"device": device, "hosts": len(p.hosts), "lost": len(lost), "lost_names": lost[:4], "cut": cut, "why": why}


def page_file(path):
    """The text and the kind of one file of the page, or (None, None). Only files that
    are really inside the ui folder are given out."""
    name = path.split("?")[0].split("#")[0].lstrip("/") or "index.html"
    full = os.path.normpath(os.path.join(UI, name))
    kind = KINDS.get(os.path.splitext(full)[1])
    if not full.startswith(UI + os.sep) or kind is None or not os.path.isfile(full):
        return None, None
    with open(full, encoding="utf-8") as f:
        return f.read(), kind


class Handler(BaseHTTPRequestHandler):
    def send_text(self, text, kind):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")   # so a changed file shows up on the next reload
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/data":
            self.send_text(json.dumps(page_data()), "application/json")
            return
        text, kind = page_file(self.path)
        if text is None:
            self.send_error(404)
        else:
            self.send_text(text, kind)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        if self.path == "/run":
            self.send_text(run(body.get("command"), body.get("values") or {}), "text/plain")
            return
        try:
            reply = action(self.path, body)
        except netconfig.Problem as err:           # a mistake in what was typed, or in the lab file
            reply = {"error": str(err)}
        except KeyError as err:
            reply = {"error": f"Missing value: {err}"}
        except OSError as err:
            reply = {"error": str(err)}
        self.send_text(json.dumps(reply), "application/json")

    def log_message(self, *args):
        pass                                       # keep the Terminal window quiet


if __name__ == "__main__":
    # 127.0.0.1 means only this computer can open the page
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    address = f"http://127.0.0.1:{PORT}"
    print("NetCheck is running at", address)
    print("Leave this window open. Press Ctrl+C or close it to stop.")
    webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

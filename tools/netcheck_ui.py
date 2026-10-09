#!/usr/bin/env python3
"""
netcheck_ui.py - a simple window for netcheck.py and netconfig.py

Run it with:   python3 netcheck_ui.py
(or double click "Start NetCheck.command")

It starts a tiny web server that only this computer can reach and opens the page in the
browser. The buttons on the page call the same functions as netcheck.py and
netconfig.py, so there is no second copy of the logic. The page has two tabs: Checks and
Configure devices. Close the Terminal window (or press Ctrl+C) to stop it.
"""

import contextlib
import io
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import netcheck
import netconfig

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIGS = os.path.join(HERE, "..", "configs")
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
    return {"devices": netconfig.load_devices(), "groups": netconfig.GROUPS, "changes": changes}


def configure(body, write):
    """Build the scripts for the chosen devices. With write=True they are also saved to files."""
    try:
        devices = body.get("devices") or []
        if write:
            title, scripts, notes, folder = netconfig.save(devices, body.get("change"), body.get("values") or {})
        else:
            title, scripts, notes = netconfig.build(devices, body.get("change"), body.get("values") or {})
            folder = None
        return {"title": title, "scripts": scripts, "notes": notes, "folder": folder}
    except netconfig.Problem as err:
        return {"error": str(err)}
    except KeyError as err:
        return {"error": f"Missing value: {err}"}


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetCheck</title>
<style>
  :root { --bg:#f4f6f8; --card:#ffffff; --ink:#1c2733; --soft:#5d6b7a; --line:#d5dce3; --accent:#1f6f54; --out:#10202b; --outink:#dbe9e4; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#12181e; --card:#1b232b; --ink:#e6edf2; --soft:#9aa8b5; --line:#2e3944; --accent:#3fa37f; --out:#0b1116; --outink:#cfe3db; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 -apple-system, "Segoe UI", sans-serif; }
  main { max-width:1100px; margin:0 auto; padding:24px 16px 40px; }
  h1 { font-size:22px; margin:0 0 2px; }
  p.sub { margin:0 0 20px; color:var(--soft); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px 16px; }
  .card h2 { font-size:15px; margin:0 0 4px; }
  .card p { margin:0 0 10px; color:var(--soft); font-size:13px; }
  label { display:block; font-size:12px; color:var(--soft); margin:8px 0 3px; }
  input, select { width:100%; padding:7px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--ink); font:inherit; }
  .row { display:flex; gap:8px; } .row > div { flex:1; min-width:0; }
  button { margin-top:12px; padding:8px 14px; border:0; border-radius:6px; background:var(--accent); color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  button:focus-visible, input:focus-visible, select:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .outhead { display:flex; justify-content:space-between; align-items:center; margin:22px 0 6px; }
  .outhead h2 { font-size:15px; margin:0; }
  .outhead button { margin:0; background:transparent; color:var(--accent); border:1px solid var(--line); font-weight:500; padding:5px 10px; }
  nav { display:flex; gap:6px; margin:0 0 18px; border-bottom:1px solid var(--line); }
  nav button { margin:0; background:transparent; color:var(--soft); border-radius:6px 6px 0 0; border-bottom:3px solid transparent; }
  nav button.on { color:var(--ink); border-bottom-color:var(--accent); }
  .two { display:grid; grid-template-columns:minmax(260px, 340px) 1fr; gap:14px; align-items:start; }
  @media (max-width:760px) { .two { grid-template-columns:1fr; } }
  .devgroup { margin:10px 0 0; } .devgroup b { display:block; font-size:12px; color:var(--soft); margin-bottom:2px; }
  .devgroup label { display:flex; gap:8px; align-items:center; font-size:14px; color:var(--ink); margin:2px 0; }
  .devgroup input { width:auto; }
  textarea { width:100%; min-height:110px; padding:7px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--ink); font:13px/1.5 ui-monospace, Menlo, monospace; }
  .ghost { background:transparent; color:var(--accent); border:1px solid var(--line); font-weight:500; }
  .msg { margin:14px 0 0; padding:10px 12px; border-radius:6px; border:1px solid var(--line); background:var(--card); font-size:14px; }
  .msg.bad { border-color:#b4472f; }
  .script { margin-top:12px; } .script .outhead { margin:0 0 6px; } .script pre { min-height:0; max-height:320px; }
  .count { color:var(--soft); font-size:13px; margin-top:8px; }
  pre { margin:0; background:var(--out); color:var(--outink); border-radius:8px; padding:14px; min-height:160px; max-height:560px; overflow:auto; font:13px/1.5 ui-monospace, Menlo, monospace; white-space:pre; }
</style>
</head>
<body>
<main>
  <h1>NetCheck</h1>
  <p class="sub">RHS school network - check subnets, the addressing plan, the inventory and device configs.</p>

  <nav>
    <button id="tab-checks" class="on" onclick="show('checks')">Checks</button>
    <button id="tab-configure" onclick="show('configure')">Configure devices</button>
  </nav>

  <section id="checks">
  <div class="grid">
    <div class="card">
      <h2>Subnet calculator</h2>
      <p>Mask, wildcard, first and last host for any subnet.</p>
      <label for="subnet">Subnet (address/prefix)</label>
      <input id="subnet" value="10.10.8.0/22">
      <button onclick="run('subnet', {subnet: val('subnet')})">Calculate</button>
    </div>

    <div class="card">
      <h2>Check addressing plan</h2>
      <p>Reads plan.csv. Finds bad subnets, bad gateways and overlaps.</p>
      <button onclick="run('plan', {})">Check plan</button>
    </div>

    <div class="card">
      <h2>Check inventory</h2>
      <p>Reads inventory.csv. Finds duplicate names, duplicate IPs and addresses in the wrong subnet.</p>
      <button onclick="run('inventory', {})">Check inventory</button>
    </div>

    <div class="card">
      <h2>Compare two configs</h2>
      <p>Lines with - are only in the first device, lines with + only in the second.</p>
      <div class="row">
        <div><label for="a">First device</label><select id="a">__OPTIONS_A__</select></div>
        <div><label for="b">Second device</label><select id="b">__OPTIONS_B__</select></div>
      </div>
      <button onclick="run('compare', {a: val('a'), b: val('b')})">Compare</button>
    </div>

    <div class="card">
      <h2>New room switch config</h2>
      <p>Makes a config for a new classroom switch, ready to paste into the CLI.</p>
      <div class="row">
        <div><label for="room">Room</label><input id="room" value="E231"></div>
        <div><label for="students">Student PCs</label><input id="students" value="15"></div>
      </div>
      <label for="ip">Management IP (in 10.10.99.0/24)</label>
      <input id="ip" value="10.10.99.17">
      <button onclick="run('template', {room: val('room'), ip: val('ip'), students: val('students')})">Generate</button>
    </div>
  </div>

  <div class="outhead">
    <h2>Output</h2>
    <button onclick="navigator.clipboard.writeText(document.getElementById('out').textContent)">Copy</button>
  </div>
  <pre id="out">Press a button above.</pre>
  </section>

  <section id="configure" hidden>
    <div class="two">
      <div class="card">
        <h2>1. Devices</h2>
        <p>Pick a group, then tick or untick single devices.</p>
        <label for="group">Device group</label>
        <select id="group" onchange="pickGroup()"></select>
        <div id="devices"></div>
        <div class="count" id="count"></div>
      </div>
      <div class="card">
        <h2>2. Change</h2>
        <p id="help"></p>
        <label for="change">What to configure</label>
        <select id="change" onchange="drawFields()"></select>
        <div id="fields"></div>
        <button onclick="send(false)">Preview commands</button>
        <button class="ghost" onclick="send(true)">Save scripts to files</button>
      </div>
    </div>
    <div id="result"></div>
  </section>
</main>
<script>
  function val(id) { return document.getElementById(id).value; }
  function el(tag, text, cls) { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }

  function show(name) {
    for (const n of ['checks', 'configure']) {
      document.getElementById(n).hidden = n !== name;
      document.getElementById('tab-' + n).className = n === name ? 'on' : '';
    }
  }

  // ---- Configure devices tab
  let DATA = null;

  async function start() {
    DATA = await (await fetch('/data')).json();

    const group = document.getElementById('group');
    const presets = [['', 'Choose...'], ['all', 'All routers and switches'], ['switches', 'All switches'],
                     ['allaccess', 'All access switches']].concat(DATA.groups).concat([['none', 'None']]);
    for (const [id, title] of presets) { const o = el('option', title); o.value = id; group.appendChild(o); }

    const box = document.getElementById('devices');
    for (const [id, title] of DATA.groups) {
      const part = el('div', '', 'devgroup');
      part.appendChild(el('b', title));
      for (const d of DATA.devices.filter(d => d.group === id)) {
        const label = el('label');
        const tick = el('input'); tick.type = 'checkbox'; tick.value = d.name; tick.dataset.group = d.group;
        tick.onchange = countDevices;
        label.appendChild(tick);
        label.appendChild(el('span', d.name + '  (' + d.location + ')'));
        part.appendChild(label);
      }
      box.appendChild(part);
    }

    const change = document.getElementById('change');
    for (const c of DATA.changes) { const o = el('option', c.title); o.value = c.id; change.appendChild(o); }
    drawFields();
    countDevices();
  }

  function pickGroup() {
    const g = val('group');
    if (!g) return;
    for (const tick of document.querySelectorAll('#devices input')) {
      const dg = tick.dataset.group;
      tick.checked = g === 'all' || (g === 'switches' && dg !== 'edge') ||
                     (g === 'allaccess' && (dg === 'room' || dg === 'access')) || g === dg;
    }
    countDevices();
  }

  function chosenDevices() {
    return Array.from(document.querySelectorAll('#devices input:checked')).map(t => t.value);
  }

  function countDevices() {
    document.getElementById('count').textContent = chosenDevices().length + ' device(s) chosen';
  }

  function drawFields() {
    const c = DATA.changes.find(c => c.id === val('change'));
    document.getElementById('help').textContent = c.help;
    const box = document.getElementById('fields');
    box.textContent = '';
    for (const f of c.fields) {
      const label = el('label', f.label); label.htmlFor = 'f-' + f.key;
      let input;
      if (f.choices) {
        input = el('select');
        for (const choice of f.choices) input.appendChild(el('option', choice));
      } else if (f.big) {
        input = el('textarea');
      } else {
        input = el('input');
      }
      input.id = 'f-' + f.key; input.value = f.default; input.dataset.key = f.key;
      box.appendChild(label); box.appendChild(input);
    }
  }

  async function send(write) {
    const values = {};
    for (const input of document.querySelectorAll('#fields [data-key]')) values[input.dataset.key] = input.value;
    const result = document.getElementById('result');
    result.textContent = '';
    let reply;
    try {
      reply = await (await fetch(write ? '/save' : '/preview', {method: 'POST',
        body: JSON.stringify({devices: chosenDevices(), change: val('change'), values: values})})).json();
    } catch (e) {
      result.appendChild(el('div', 'The program is not running any more. Start netcheck_ui.py again.', 'msg bad'));
      return;
    }
    if (reply.error) { result.appendChild(el('div', reply.error, 'msg bad')); return; }

    const names = Object.keys(reply.scripts);
    let text = reply.title + ': ' + names.length + ' device(s). ';
    text += reply.folder ? 'Saved in the folder changes/' + reply.folder + ' and added to changes/log.csv. '
                         : 'This is a preview, nothing was saved. ';
    text += 'To apply: open the device in Packet Tracer, CLI tab, log in, type enable, then paste its script.';
    result.appendChild(el('div', text, 'msg'));
    for (const note of reply.notes) result.appendChild(el('div', note, 'msg'));

    for (const name of names) {
      const part = el('div', '', 'script');
      const head = el('div', '', 'outhead');
      head.appendChild(el('h2', name));
      const copy = el('button', 'Copy');
      copy.onclick = () => { navigator.clipboard.writeText(reply.scripts[name]); copy.textContent = 'Copied'; };
      head.appendChild(copy);
      part.appendChild(head);
      part.appendChild(el('pre', reply.scripts[name]));
      result.appendChild(part);
    }
    result.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  start();
  async function run(command, values) {
    const out = document.getElementById('out');
    out.textContent = 'Working...';
    try {
      const reply = await fetch('/run', {method: 'POST', body: JSON.stringify({command: command, values: values})});
      out.textContent = await reply.text();
    } catch (e) {
      out.textContent = 'The program is not running any more. Start netcheck_ui.py again.';
    }
    out.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def send_text(self, text, kind):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/data":
            self.send_text(json.dumps(page_data()), "application/json")
            return
        names = config_names()

        def options(chosen):
            return "".join(f"<option{' selected' if n == chosen else ''}>{n}</option>" for n in names)

        page = PAGE.replace("__OPTIONS_A__", options("SW-E230")).replace("__OPTIONS_B__", options("SW-E110"))
        self.send_text(page, "text/html")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        if self.path == "/preview":
            self.send_text(json.dumps(configure(body, write=False)), "application/json")
        elif self.path == "/save":
            self.send_text(json.dumps(configure(body, write=True)), "application/json")
        else:
            self.send_text(run(body.get("command"), body.get("values") or {}), "text/plain")

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

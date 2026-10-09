#!/usr/bin/env python3
"""
netcheck_ui.py - a simple window for the network tools

Run it with:   python3 netcheck_ui.py
(or double click "Start NetCheck.command")

It starts a tiny web server that only this computer can reach and opens the page in the
browser. The buttons on the page call the same functions as netcheck.py, netconfig.py,
pktconfig.py and pktlayout.py, so there is no second copy of the logic.

The page has four tabs:

  Lab        the routers and switches inside the Packet Tracer file, click one to read its config
  Configure  pick devices and a change, see what it would do, write it into the lab
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

import netcheck
import netconfig
import pktconfig
import pktlayout

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
    if path == "/layout":
        report = pktlayout.arrange()
        return {"message": next(line for line in report if line.startswith("Written")).replace(
            "Written to", "Canvas arranged in")}
    return {"error": "Unknown request."}


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetCheck</title>
<style>
  :root { --bg:#f5f6f8; --card:#ffffff; --ink:#18212b; --soft:#5f6c7a; --line:#dde2e8; --accent:#1f6f54; --tint:#e6f2ed;
          --out:#0f1b24; --outink:#d9e6e1; --bad:#b4472f; --warn:#8a6100; --warnbg:#fdf3d7; --add:#7fd6a8; --del:#f09a88; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#11161b; --card:#1a2128; --ink:#e7edf2; --soft:#98a6b3; --line:#2b3540; --accent:#46ad88; --tint:#1d3029;
            --out:#0a0f13; --outink:#cfe1da; --bad:#e0745c; --warn:#e8c56a; --warnbg:#332a12; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, "Segoe UI", sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid var(--line); }
  .bar { max-width:1120px; margin:0 auto; padding:0 20px; display:flex; align-items:center; gap:22px; flex-wrap:wrap; }
  .brand { font-weight:700; font-size:17px; padding:14px 0; } .brand span { color:var(--accent); }
  nav { display:flex; gap:2px; flex:1; }
  nav button { background:none; border:0; border-bottom:2px solid transparent; color:var(--soft); font:inherit; font-weight:500;
               padding:16px 12px 14px; cursor:pointer; }
  nav button:hover { color:var(--ink); } nav button.on { color:var(--ink); border-bottom-color:var(--accent); }
  .pill { font-size:12.5px; padding:4px 10px; border-radius:99px; background:var(--tint); color:var(--accent); white-space:nowrap; }
  .pill.warn { background:var(--warnbg); color:var(--warn); }
  main { max-width:1120px; margin:0 auto; padding:26px 20px 60px; }
  h1 { font-size:21px; margin:0 0 4px; } h2 { font-size:15px; margin:0 0 4px; }
  .sub { margin:0 0 20px; color:var(--soft); }
  h3 { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--soft); margin:22px 0 8px; font-weight:600; }
  .head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; }
  .tools { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px 16px; }
  .card p { margin:0 0 10px; color:var(--soft); font-size:13px; }
  .device { text-align:left; font:inherit; color:inherit; cursor:pointer; transition:border-color .12s, transform .12s; }
  .device:hover { border-color:var(--accent); transform:translateY(-1px); }
  .device b { display:flex; justify-content:space-between; align-items:center; font-size:15px; }
  .device small { display:block; color:var(--soft); font-size:12.5px; margin-top:2px; }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--accent); flex:none; } .dot.off { background:var(--bad); }
  .chips { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
  .chip { font-size:11.5px; padding:1px 7px; border-radius:99px; background:var(--bg); border:1px solid var(--line); color:var(--soft); }
  label { display:block; font-size:12px; color:var(--soft); margin:10px 0 3px; }
  input, select, textarea { width:100%; padding:8px 9px; border:1px solid var(--line); border-radius:7px; background:var(--bg);
                            color:var(--ink); font:inherit; }
  textarea { min-height:120px; font:13px/1.5 ui-monospace, Menlo, monospace; }
  .row { display:flex; gap:8px; } .row > div { flex:1; min-width:0; }
  button.go, button.ghost { margin-top:12px; padding:8px 14px; border-radius:7px; font:inherit; font-weight:600; cursor:pointer; }
  button.go { border:1px solid var(--accent); background:var(--accent); color:#fff; }
  button.ghost { border:1px solid var(--line); background:transparent; color:var(--ink); font-weight:500; }
  button.ghost:hover { border-color:var(--accent); color:var(--accent); }
  button.small { margin:0; padding:5px 10px; font-size:13px; }
  button:disabled { opacity:.5; cursor:default; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .two { display:grid; grid-template-columns:minmax(260px, 340px) 1fr; gap:14px; align-items:start; }
  @media (max-width:780px) { .two { grid-template-columns:1fr !important; } }
  .picks { display:flex; flex-wrap:wrap; gap:6px; }
  .pick { font:inherit; font-size:13px; padding:4px 10px; border-radius:99px; border:1px solid var(--line); background:var(--bg);
          color:var(--ink); cursor:pointer; }
  .pick.on { background:var(--accent); border-color:var(--accent); color:#fff; }
  .steps { display:flex; gap:8px; flex-wrap:wrap; margin-top:4px; }
  .msg { margin:14px 0 0; padding:10px 12px; border-radius:8px; border:1px solid var(--line); background:var(--card); font-size:14px; }
  .msg.bad { border-color:var(--bad); color:var(--bad); } .msg.good { border-color:var(--accent); }
  .result { margin-top:12px; } .result .head { align-items:center; margin-bottom:6px; }
  .pair { display:grid; grid-template-columns:1fr 1fr; gap:8px; } @media (max-width:780px) { .pair { grid-template-columns:1fr; } }
  .pair > div { min-width:0; }
  .pair h4 { margin:0 0 4px; font-size:12px; color:var(--soft); font-weight:500; }
  pre { margin:0; background:var(--out); color:var(--outink); border-radius:8px; padding:12px 14px; max-height:420px; overflow:auto;
        font:13px/1.5 ui-monospace, Menlo, monospace; white-space:pre; }
  pre .add { color:var(--add); } pre .del { color:var(--del); } pre .at { opacity:.5; } pre mark { background:#d9a400; color:#000; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; font-size:12px; color:var(--soft); font-weight:500; padding:6px 10px; border-bottom:1px solid var(--line); }
  td { padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; } tr:last-child td { border-bottom:0; }
  td.soft { color:var(--soft); white-space:nowrap; }
  .empty { color:var(--soft); padding:18px 0; }
  #sheet { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:10; display:flex; justify-content:flex-end; }
  #sheet[hidden] { display:none; }
  #sheet .panel { width:min(760px, 100%); height:100%; background:var(--card); padding:18px 20px; display:flex; flex-direction:column; gap:10px; }
  #sheet pre { flex:1; max-height:none; }
  #toast { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); background:var(--ink); color:var(--bg); padding:10px 16px;
           border-radius:8px; font-size:14px; max-width:90vw; z-index:20; }
  #toast[hidden] { display:none; }
</style>
</head>
<body>
<header><div class="bar">
  <div class="brand">Net<span>Check</span></div>
  <nav id="tabs"></nav>
  <span class="pill" id="status">Reading the lab...</span>
</div></header>

<main>
  <section id="lab">
    <div class="head">
      <div><h1>Lab</h1><p class="sub" id="lab-sub">The routers and switches inside the Packet Tracer file. Click one to read its config.</p></div>
      <div class="tools">
        <input id="lab-filter" placeholder="Filter devices or VLANs" style="width:210px" oninput="drawLab()">
        <button class="ghost small" onclick="loadLab(true)">Refresh</button>
        <button class="ghost small" onclick="arrange()">Tidy the canvas</button>
        <button class="small" onclick="openLab()">Open in Packet Tracer</button>
      </div>
    </div>
    <div id="lab-body"><p class="empty">Reading the lab file...</p></div>
  </section>

  <section id="configure" hidden>
    <h1>Configure</h1>
    <p class="sub">Pick devices, pick a change, look at what it does, then write it into the lab.</p>
    <div class="two">
      <div class="card">
        <h2>1. Devices</h2>
        <p id="count">0 chosen</p>
        <div class="picks" id="presets"></div>
        <div id="devices"></div>
      </div>
      <div class="card">
        <h2>2. Change</h2>
        <p id="help"></p>
        <label for="change">What to configure</label>
        <select id="change" onchange="drawFields()"></select>
        <div id="fields"></div>
        <div class="steps">
          <button class="go" onclick="send('/preview')">Preview</button>
          <button class="go" onclick="send('/apply')">Write to the lab</button>
          <button class="ghost" onclick="send('/save')">Save scripts only</button>
        </div>
      </div>
    </div>
    <div id="result"></div>
  </section>

  <section id="checks" hidden>
    <h1>Checks</h1>
    <p class="sub">Subnets, the addressing plan, the inventory and the saved configs.</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(300px, 1fr))">
      <div class="card">
        <h2>Subnet calculator</h2>
        <p>Mask, wildcard, first and last host for any subnet.</p>
        <label for="subnet">Subnet (address/prefix)</label>
        <input id="subnet" value="10.10.8.0/22" onkeydown="if (event.key === 'Enter') run('subnet', {subnet: val('subnet')})">
        <button class="go" onclick="run('subnet', {subnet: val('subnet')})">Calculate</button>
      </div>
      <div class="card">
        <h2>Addressing plan</h2>
        <p>Reads plan.csv. Finds bad subnets, bad gateways and overlaps.</p>
        <button class="go" onclick="run('plan', {})">Check plan</button>
      </div>
      <div class="card">
        <h2>Inventory</h2>
        <p>Reads inventory.csv. Finds duplicate names, duplicate IPs and addresses in the wrong subnet.</p>
        <button class="go" onclick="run('inventory', {})">Check inventory</button>
      </div>
      <div class="card">
        <h2>Compare two configs</h2>
        <p>Lines with - are only in the first device, lines with + only in the second.</p>
        <div class="row">
          <div><label for="a">First device</label><select id="a"></select></div>
          <div><label for="b">Second device</label><select id="b"></select></div>
        </div>
        <button class="go" onclick="run('compare', {a: val('a'), b: val('b')})">Compare</button>
      </div>
      <div class="card">
        <h2>New room switch</h2>
        <p>Makes a config for a new classroom switch, ready to paste into the CLI.</p>
        <div class="row">
          <div><label for="room">Room</label><input id="room" value="E231"></div>
          <div><label for="students">Student PCs</label><input id="students" value="15"></div>
        </div>
        <label for="ip">Management IP (in 10.10.99.0/24)</label>
        <input id="ip" value="10.10.99.17">
        <button class="go" onclick="run('template', {room: val('room'), ip: val('ip'), students: val('students')})">Generate</button>
      </div>
    </div>
    <div class="result">
      <div class="head"><h2>Output</h2><button class="ghost small" onclick="copyText(document.getElementById('out').textContent, this)">Copy</button></div>
      <pre id="out">Press a button above.</pre>
    </div>
  </section>

  <section id="history" hidden>
    <h1>History</h1>
    <p class="sub">Every change made with this tool, and the copies of the lab kept before each one.</p>
    <div class="two" style="grid-template-columns:1fr minmax(260px, 340px)">
      <div class="card"><h2>Changes</h2><div id="log"></div></div>
      <div class="card"><h2>Go back</h2><p>Restoring puts the lab and the configs folder back the way they were. The lab as it is now is kept first, so you can undo a restore too.</p><div id="backups"></div></div>
    </div>
  </section>
</main>

<div id="sheet" hidden onclick="if (event.target === this) closeSheet()">
  <div class="panel">
    <div class="head" style="align-items:center">
      <h1 id="sheet-title"></h1>
      <div class="tools">
        <input id="sheet-find" placeholder="Find in config" style="width:180px" oninput="drawSheet()">
        <button class="ghost small" onclick="copyText(SHEET, this)">Copy</button>
        <button class="ghost small" onclick="configureThis()">Configure this device</button>
        <button class="ghost small" onclick="closeSheet()">Close</button>
      </div>
    </div>
    <span class="sub" id="sheet-sub" style="margin:0"></span>
    <pre id="sheet-text"></pre>
  </div>
</div>
<div id="toast" hidden></div>

<script>
  const NL = String.fromCharCode(10);
  const TABS = [['lab', 'Lab'], ['configure', 'Configure'], ['checks', 'Checks'], ['history', 'History']];
  const LAYERS = [['edge', 'Edge routers'], ['core', 'Core switches'], ['dist', 'Distribution switches'], ['room', 'Room switches'],
                  ['access', 'Office and MDF'], ['outside', 'Outside the school']];
  let DATA = null, LAB = null, SHEET = '', SHEET_NAME = '';

  function val(id) { return document.getElementById(id).value; }
  function el(tag, text, cls) { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
  function clear(id) { const e = document.getElementById(id); e.textContent = ''; return e; }

  async function ask(path, body) {
    try {
      return await (await fetch(path, {method: 'POST', body: JSON.stringify(body || {})})).json();
    } catch (e) {
      return {error: 'The program is not running any more. Start netcheck_ui.py again.'};
    }
  }

  function toast(text) {
    const t = document.getElementById('toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 6000);
  }

  function copyText(text, button) {
    navigator.clipboard.writeText(text);
    const old = button.textContent; button.textContent = 'Copied';
    setTimeout(() => { button.textContent = old; }, 1200);
  }

  // text with + and - lines in colour
  function diffBlock(text) {
    const pre = el('pre');
    for (const line of text.split(NL)) {
      const cls = line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'at' : '';
      pre.appendChild(el('span', line + NL, cls));
    }
    return pre;
  }

  function show(name) {
    for (const [id] of TABS) {
      document.getElementById(id).hidden = id !== name;
      document.getElementById('tab-' + id).className = id === name ? 'on' : '';
    }
    location.hash = name;
    if (name === 'history') loadHistory();
  }

  // ---- Lab tab
  async function loadLab(say) {
    const reply = await ask('/lab');
    const status = document.getElementById('status');
    if (reply.error) {
      clear('lab-body').appendChild(el('div', reply.error, 'msg bad'));
      status.textContent = 'Lab file problem'; status.className = 'pill warn';
      return;
    }
    LAB = reply;
    const different = LAB.devices.filter(d => d.same_as_file === false).length;
    if (LAB.packet_tracer_open) { status.textContent = 'Packet Tracer is open - close the lab before writing'; status.className = 'pill warn'; }
    else if (different) { status.textContent = different + ' config(s) differ from the configs folder'; status.className = 'pill warn'; }
    else { status.textContent = LAB.devices.length + ' devices, lab and configs folder match'; status.className = 'pill'; }
    document.getElementById('lab-sub').textContent = 'The routers and switches inside ' + LAB.file + '. Click one to read its config.';
    drawLab();
    if (say) toast('Lab file read again.');
  }

  function drawLab() {
    if (!LAB) return;
    const body = clear('lab-body');
    const want = val('lab-filter').trim().toLowerCase();
    let shown = 0;
    for (const [id, title] of LAYERS) {
      const devices = LAB.devices.filter(d => d.group === id).filter(d => !want ||
        (d.name + ' ' + d.location + ' ' + d.type + ' ' + d.ip + ' ' + Object.entries(d.vlans).map(v => 'vlan ' + v[0] + ' ' + v[1]).join(' '))
          .toLowerCase().includes(want));
      if (!devices.length) continue;
      shown += devices.length;
      body.appendChild(el('h3', title));
      const grid = el('div', '', 'grid');
      for (const d of devices) {
        const card = el('button', '', 'card device');
        const top = el('b', d.name);
        const dot = el('span', '', 'dot' + (d.same_as_file === false ? ' off' : ''));
        dot.title = d.same_as_file === false ? 'Differs from the file in the configs folder' : 'Same as the file in the configs folder';
        top.appendChild(dot);
        card.appendChild(top);
        card.appendChild(el('small', [d.type, d.location, d.ip].filter(Boolean).join(' · ') || 'not in the inventory'));
        card.appendChild(el('small', d.lines + ' config lines'));
        const chips = el('div', '', 'chips');
        for (const [number, name] of Object.entries(d.vlans)) chips.appendChild(el('span', number + ' ' + name, 'chip'));
        if (chips.children.length) card.appendChild(chips);
        card.onclick = () => openSheet(d);
        grid.appendChild(card);
      }
      body.appendChild(grid);
    }
    if (!shown) body.appendChild(el('p', 'Nothing matches the filter.', 'empty'));
  }

  async function openSheet(d) {
    const reply = await ask('/config', {device: d.name});
    if (reply.error) { toast(reply.error); return; }
    SHEET = reply.text; SHEET_NAME = d.name;
    document.getElementById('sheet-title').textContent = d.name;
    document.getElementById('sheet-sub').textContent = 'Running config as stored in the lab file, ' + d.lines + ' lines.';
    document.getElementById('sheet-find').value = '';
    drawSheet();
    document.getElementById('sheet').hidden = false;
  }

  function drawSheet() {
    const pre = clear('sheet-text');
    const want = val('sheet-find').toLowerCase();
    let first = null;
    for (const line of SHEET.split(NL)) {
      const at = want ? line.toLowerCase().indexOf(want) : -1;
      if (at < 0) { pre.appendChild(document.createTextNode(line + NL)); continue; }
      pre.appendChild(document.createTextNode(line.slice(0, at)));
      const mark = el('mark', line.slice(at, at + want.length));
      first = first || mark;
      pre.appendChild(mark);
      pre.appendChild(document.createTextNode(line.slice(at + want.length) + NL));
    }
    if (first) first.scrollIntoView({block: 'center'});
  }

  function closeSheet() { document.getElementById('sheet').hidden = true; }

  function configureThis() {
    closeSheet();
    for (const b of document.querySelectorAll('#devices .pick')) b.classList.toggle('on', b.dataset.name === SHEET_NAME);
    countDevices();
    show('configure');
  }

  async function arrange() {
    if (!confirm('Put every device back on the grid and rewrite the boxes and notes on the canvas?' + NL + NL +
                 'Close the lab in Packet Tracer first. Device configs are not touched.')) return;
    const reply = await ask('/layout');
    toast(reply.error || reply.message);
  }

  async function openLab() {
    const reply = await ask('/open');
    toast(reply.error || reply.message);
  }

  // ---- Configure tab
  async function start() {
    const tabs = document.getElementById('tabs');
    for (const [id, title] of TABS) {
      const b = el('button', title); b.id = 'tab-' + id; b.onclick = () => show(id); tabs.appendChild(b);
    }
    DATA = await (await fetch('/data')).json();

    const presets = [['all', 'All'], ['switches', 'All switches'], ['allaccess', 'All access switches']]
      .concat(DATA.groups.map(g => [g[0], g[1]])).concat([['none', 'None']]);
    for (const [id, title] of presets) {
      const b = el('button', title, 'pick'); b.onclick = () => pickGroup(id);
      document.getElementById('presets').appendChild(b);
    }
    const box = document.getElementById('devices');
    for (const [id, title] of DATA.groups) {
      box.appendChild(el('h3', title));
      const picks = el('div', '', 'picks');
      for (const d of DATA.devices.filter(d => d.group === id)) {
        const b = el('button', d.name, 'pick');
        b.dataset.name = d.name; b.dataset.group = d.group; b.title = d.type + ', ' + d.location;
        b.onclick = () => { b.classList.toggle('on'); countDevices(); };
        picks.appendChild(b);
      }
      box.appendChild(picks);
    }
    const change = document.getElementById('change');
    for (const c of DATA.changes) { const o = el('option', c.title); o.value = c.id; change.appendChild(o); }
    for (const [id, chosen] of [['a', 'SW-E230'], ['b', 'SW-E110']]) {
      for (const name of DATA.configs) { const o = el('option', name); o.selected = name === chosen; document.getElementById(id).appendChild(o); }
    }
    drawFields();
    countDevices();
    const wanted = location.hash.slice(1);
    show(TABS.some(t => t[0] === wanted) ? wanted : 'lab');
    loadLab();
  }

  function pickGroup(g) {
    for (const b of document.querySelectorAll('#devices .pick')) {
      const dg = b.dataset.group;
      b.classList.toggle('on', g === 'all' || (g === 'switches' && dg !== 'edge') ||
                               (g === 'allaccess' && (dg === 'room' || dg === 'access')) || g === dg);
    }
    countDevices();
  }

  function chosenDevices() { return Array.from(document.querySelectorAll('#devices .pick.on')).map(b => b.dataset.name); }
  function countDevices() { document.getElementById('count').textContent = chosenDevices().length + ' chosen. Click a group or single devices.'; }

  function drawFields() {
    const c = DATA.changes.find(c => c.id === val('change'));
    document.getElementById('help').textContent = c.help;
    const box = clear('fields');
    for (const f of c.fields) {
      const label = el('label', f.label); label.htmlFor = 'f-' + f.key;
      let input;
      if (f.choices) { input = el('select'); for (const choice of f.choices) input.appendChild(el('option', choice)); }
      else if (f.big) input = el('textarea');
      else input = el('input');
      input.id = 'f-' + f.key; input.value = f.default; input.dataset.key = f.key;
      box.appendChild(label); box.appendChild(input);
    }
  }

  async function send(path) {
    if (path === '/apply' && !confirm('Write this change into the Packet Tracer lab file?' + NL + NL +
        'Close the lab in Packet Tracer first. A copy of the file is kept, see the History tab.')) return;
    const values = {};
    for (const input of document.querySelectorAll('#fields [data-key]')) values[input.dataset.key] = input.value;
    const result = clear('result');
    const reply = await ask(path, {devices: chosenDevices(), change: val('change'), values: values});
    if (reply.error) { result.appendChild(el('div', reply.error, 'msg bad')); return; }

    const names = Object.keys(reply.scripts);
    let text = reply.title + ': ' + names.length + ' device(s). ';
    if (reply.written) text += 'Written into the lab file and the configs folder. Open the lab in Packet Tracer to see it.';
    else if (reply.folder) text += 'Scripts saved in changes/' + reply.folder + '. The lab was not changed.';
    else text += 'This is a preview, nothing was changed. On the right is what each config in the lab would get.';
    result.appendChild(el('div', text, 'msg' + (reply.written ? ' good' : '')));
    for (const note of reply.notes) result.appendChild(el('div', note, 'msg'));

    for (const name of names) {
      const part = el('div', '', 'card result');
      const head = el('div', '', 'head');
      head.appendChild(el('h2', name));
      const copy = el('button', 'Copy script', 'ghost small');
      copy.onclick = () => copyText(reply.scripts[name], copy);
      head.appendChild(copy);
      part.appendChild(head);
      const pair = el('div', '', 'pair');
      const left = el('div'); left.appendChild(el('h4', 'Commands')); left.appendChild(el('pre', reply.scripts[name]));
      const right = el('div'); right.appendChild(el('h4', reply.written ? 'What changed in the lab' : 'What would change in the lab'));
      right.appendChild(diffBlock(reply.changes[name] || ''));
      pair.appendChild(left); pair.appendChild(right);
      part.appendChild(pair);
      result.appendChild(part);
    }
    result.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    if (reply.written) { toast('Written to the lab.'); loadLab(); }
  }

  // ---- Checks tab
  async function run(command, values) {
    document.getElementById('out').textContent = 'Working...';
    let text;
    try {
      text = await (await fetch('/run', {method: 'POST', body: JSON.stringify({command: command, values: values})})).text();
    } catch (e) {
      text = 'The program is not running any more. Start netcheck_ui.py again.';
    }
    const fresh = command === 'compare' ? diffBlock(text) : el('pre', text);
    fresh.id = 'out';
    document.getElementById('out').replaceWith(fresh);
    fresh.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  // ---- History tab
  async function loadHistory() {
    const reply = await ask('/history');
    const log = clear('log'), backups = clear('backups');
    if (reply.error) { log.appendChild(el('div', reply.error, 'msg bad')); return; }
    if (!reply.changes.length) log.appendChild(el('p', 'No changes yet. Make one on the Configure tab.', 'empty'));
    else {
      const table = el('table');
      const head = el('tr'); for (const h of ['When', 'Change', 'Devices', 'In lab']) head.appendChild(el('th', h));
      table.appendChild(head);
      for (const row of reply.changes) {
        const tr = el('tr');
        tr.appendChild(el('td', row.time, 'soft'));
        tr.appendChild(el('td', row.change));
        const devices = (row.devices || '').split(' ');
        tr.appendChild(el('td', devices.length > 3 ? devices.length + ' devices' : devices.join(', '), 'soft'));
        tr.appendChild(el('td', row['written to lab'] === 'yes' ? 'yes' : 'scripts only', 'soft'));
        tr.title = row.devices;
        table.appendChild(tr);
      }
      log.appendChild(table);
    }
    if (!reply.backups.length) backups.appendChild(el('p', 'No copies yet. One is made before every change.', 'empty'));
    else {
      const table = el('table');
      for (const name of reply.backups) {
        const tr = el('tr');
        tr.appendChild(el('td', 'Lab before ' + name.slice(0, 10) + ' ' + name.slice(11, 13) + ':' + name.slice(13, 15) + ':' + name.slice(15, 17)));
        const cell = el('td'); cell.style.textAlign = 'right';
        const b = el('button', 'Restore', 'ghost small');
        b.onclick = async () => {
          if (!confirm('Put the lab back to how it was before this change?' + NL + NL + 'Close the lab in Packet Tracer first.')) return;
          const r = await ask('/restore', {backup: name});
          toast(r.error || r.message); loadHistory(); loadLab();
        };
        cell.appendChild(b); tr.appendChild(cell);
        table.appendChild(tr);
      }
      backups.appendChild(table);
    }
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  start();
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
        else:
            self.send_text(PAGE, "text/html")

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

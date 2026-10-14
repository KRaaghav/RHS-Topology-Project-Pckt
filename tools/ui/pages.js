// pages.js - the six pages of NetCheck

import { html, useState, useEffect, useMemo, useApp, useCount, ask, askText, Icon, Button, Card, Segments, CopyButton, Diff,
         Skeleton, Empty, Notice, Ring } from './lib.js';
import { Topology, Building } from './views.js';

const LAYERS = [['edge', 'Edge routers'], ['core', 'Core switches'], ['dist', 'Distribution switches'], ['room', 'Room switches'],
                ['access', 'Office and MDF'], ['outside', 'Outside the school']];

function PageHead({ title, sub, children }) {
  return html`<div className="page-head">
    <div><h1>${title}</h1><p>${sub}</p></div>
    <div className="page-tools">${children}</div>
  </div>`;
}

// ---------------------------------------------------------------- Overview

function Tile({ number, label, icon, delay }) {
  const shown = useCount(number);
  return html`<div className="tile rise" style=${{ animationDelay: delay + 'ms' }}>
    <span className="tile-icon"><${Icon} name=${icon} size=${16} /></span>
    <b>${number == null ? '–' : shown}</b><span>${label}</span>
  </div>`;
}

export function Overview() {
  const app = useApp();
  const { health, graph, data } = app;
  const [view, setView] = useState('topology');
  const counts = health ? health.counts : {};
  const failed = health ? health.tests.filter(t => !t.passed) : [];
  const rooms = data ? data.devices.filter(d => d.group === 'room').length : null;
  const tiles = [[counts.devices, 'devices in the lab', 'grid'], [counts['network devices'], 'routers and switches', 'lab'],
                 [counts.hosts, 'PCs and servers', 'overview'], [rooms, 'classrooms', 'building'],
                 [counts.cables, 'cables', 'share'], [counts['failures tried'], 'single failures survived', 'zap']];

  return html`<div className="page">
    <${PageHead} title="Overview" sub=${health ? 'The lab at a glance. Tests last run ' + health.time + '.' : 'The lab at a glance.'}>
      <${Button} small icon="refresh" onClick=${() => app.reload(true)}>Refresh<//>
      <${Button} small icon="plus" onClick=${app.addRoom}>Add a room<//>
      <${Button} small kind="primary" icon="open" onClick=${app.openLab}>Open in Packet Tracer<//>
    <//>
    <div className="hero">
      <div className="card score rise">
        <${Ring} score=${health ? health.score : null} />
        <div>
          <span className="eyebrow">Health score</span>
          <h2>${!health ? 'Running the tests...' : failed.length ? failed.length + ' test' + (failed.length > 1 ? 's' : '') + ' failing' : 'Everything passes'}</h2>
          <p>${health ? health.passed + ' of ' + health.total + ' measurable tests pass' + (failed.length ? ': ' + failed.map(t => t.title).join('; ') : ', nothing to fix.') : ' '}</p>
          <${Button} small icon="monitor" onClick=${() => app.go('monitor')}>See every test<//>
        </div>
      </div>
      <div className="tiles">${tiles.map(([number, label, icon], i) =>
        html`<${Tile} key=${label} number=${number} label=${label} icon=${icon} delay=${80 + i * 60} />`)}</div>
    </div>
    <${Card} delay=${160} title=${view === 'topology' ? 'Topology' : 'Building'}
      right=${html`<${Segments} value=${view} onChange=${setView} options=${[['topology', 'Topology', 'share'], ['building', 'Building', 'building']]} />`}>
      ${!graph ? html`<${Skeleton} rows=${4} height=${90} />`
        : html`<div key=${view} className="fade">${view === 'topology' ? html`<${Topology} graph=${graph} />` : html`<${Building} graph=${graph} />`}</div>`}
    <//>
  </div>`;
}

// ---------------------------------------------------------------- Lab

export function Lab() {
  const app = useApp();
  const { lab, labError } = app;
  const [filter, setFilter] = useState('');
  const want = filter.trim().toLowerCase();
  const match = d => !want || (d.name + ' ' + d.location + ' ' + d.type + ' ' + d.ip + ' ' +
    Object.entries(d.vlans).map(v => 'vlan ' + v[0] + ' ' + v[1]).join(' ')).toLowerCase().includes(want);
  const shown = lab ? lab.devices.filter(match) : [];

  return html`<div className="page">
    <${PageHead} title="Lab" sub=${'The routers and switches inside ' + (lab ? lab.file : 'the Packet Tracer file') + '. Click one to read its config.'}>
      <label className="search"><${Icon} name="search" size=${15} />
        <input value=${filter} onInput=${e => setFilter(e.target.value)} placeholder="Filter devices or VLANs" aria-label="Filter devices or VLANs" /></label>
      <${Button} small icon="refresh" onClick=${() => app.reload(true)}>Refresh<//>
      <${Button} small icon="plus" onClick=${app.addRoom}>Add a room<//>
      <${Button} small icon="grid" onClick=${app.arrange}>Tidy the canvas<//>
      <${Button} small kind="primary" icon="open" onClick=${app.openLab}>Open in Packet Tracer<//>
    <//>
    ${labError && html`<${Notice} kind="bad">${labError}<//>`}
    ${!lab && !labError && html`<${Skeleton} rows=${4} height=${96} />`}
    ${lab && !shown.length && html`<${Empty} icon="search">Nothing matches the filter.<//>`}
    ${LAYERS.map(([id, title]) => {
      const devices = shown.filter(d => d.group === id);
      if (!devices.length) return null;
      return html`<section key=${id} className="layer">
        <h3><i className=${'layer-dot k-' + id} />${title}<span>${devices.length}</span></h3>
        <div className="device-grid">${devices.map((d, i) => html`<button key=${d.name} className=${'device rise k-' + id}
          style=${{ animationDelay: Math.min(i, 14) * 30 + 'ms' }} onClick=${() => app.openConfig(d.name)}>
          <b>${d.name}<i className=${'state' + (d.same_as_file === false ? ' off' : '')}
            title=${d.same_as_file === false ? 'Differs from the file in the configs folder' : 'Same as the file in the configs folder'} /></b>
          <small>${[d.type, d.location, d.ip].filter(Boolean).join(' · ') || 'not in the inventory'}</small>
          <small>${d.lines} config lines</small>
          ${Object.keys(d.vlans).length > 0 && html`<div className="chips">${Object.entries(d.vlans).map(([number, name]) =>
            html`<span key=${number} className="chip">${number} ${name}</span>`)}</div>`}
        </button>`)}</div>
      </section>`;
    })}
  </div>`;
}

// ---------------------------------------------------------------- Configure

export function Configure() {
  const app = useApp();
  const { data, picked, setPicked } = app;
  const [change, setChange] = useState(data.changes[0].id);
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState('');
  const [reply, setReply] = useState(null);
  const chosen = data.changes.find(c => c.id === change);

  useEffect(() => {
    const fresh = {};
    chosen.fields.forEach(f => { fresh[f.key] = f.default; });
    setValues(fresh);
  }, [change]);

  const toggle = name => setPicked(picked.includes(name) ? picked.filter(n => n !== name) : picked.concat(name));
  const pickGroup = g => setPicked(data.devices.filter(d => g === 'all' || (g === 'switches' && d.group !== 'edge') ||
    (g === 'allaccess' && (d.group === 'room' || d.group === 'access')) || g === d.group).map(d => d.name));
  const presets = [['all', 'All'], ['switches', 'All switches'], ['allaccess', 'All access switches']].concat(data.groups).concat([['none', 'None']]);

  const send = async path => {
    if (path === '/apply' && !await app.confirm({ title: 'Write this change into the lab?', ok: 'Write to the lab',
      text: 'Close the lab in Packet Tracer first. A copy of the file is kept, see the History page.' })) return;
    setBusy(path);
    const answer = await ask(path, { devices: picked, change, values });
    setBusy('');
    setReply(answer);
    if (answer.written) { app.toast('Written to the lab.', 'good'); app.reload(); }
  };

  const names = reply && !reply.error ? Object.keys(reply.scripts) : [];
  return html`<div className="page">
    <${PageHead} title="Configure" sub="Pick devices, pick a change, look at what it does, then write it into the lab." />
    <div className="split">
      <${Card} title="1. Devices" sub=${picked.length + ' chosen. Click a group or single devices.'}>
        <div className="picks">${presets.map(([id, title]) =>
          html`<button key=${id} className="pick preset" onClick=${() => pickGroup(id)}>${title}</button>`)}</div>
        ${data.groups.map(([id, title]) => html`<div key=${id}>
          <h4>${title}</h4>
          <div className="picks">${data.devices.filter(d => d.group === id).map(d => html`<button key=${d.name}
            className=${'pick' + (picked.includes(d.name) ? ' on' : '')} title=${d.type + ', ' + d.location}
            aria-pressed=${picked.includes(d.name)} onClick=${() => toggle(d.name)}>${d.name}</button>`)}</div>
        </div>`)}
      <//>
      <${Card} delay=${80} title="2. Change" sub=${chosen.help}>
        <label className="field"><span>What to configure</span>
          <select value=${change} onChange=${e => setChange(e.target.value)}>
            ${data.changes.map(c => html`<option key=${c.id} value=${c.id}>${c.title}</option>`)}</select></label>
        ${chosen.fields.map(f => html`<label key=${change + f.key} className="field"><span>${f.label}</span>
          ${f.choices ? html`<select value=${values[f.key] ?? f.default} onChange=${e => setValues({ ...values, [f.key]: e.target.value })}>
              ${f.choices.map(c => html`<option key=${c}>${c}</option>`)}</select>`
            : f.big ? html`<textarea value=${values[f.key] ?? f.default} onInput=${e => setValues({ ...values, [f.key]: e.target.value })} />`
            : html`<input value=${values[f.key] ?? f.default} onInput=${e => setValues({ ...values, [f.key]: e.target.value })} />`}
        </label>`)}
        <div className="steps">
          <${Button} kind="primary" icon="eye" busy=${busy === '/preview'} onClick=${() => send('/preview')}>Preview<//>
          <${Button} kind="primary" icon="zap" busy=${busy === '/apply'} onClick=${() => send('/apply')}>Write to the lab<//>
          <${Button} icon="save" busy=${busy === '/save'} onClick=${() => send('/save')}>Save scripts only<//>
        </div>
      <//>
    </div>
    ${reply && reply.error && html`<${Notice} kind="bad">${reply.error}<//>`}
    ${reply && !reply.error && html`<div className="results">
      <${Notice} kind=${reply.written ? 'good' : ''}>${reply.title}: ${names.length} device(s). ${reply.written
        ? 'Written into the lab file and the configs folder. Open the lab in Packet Tracer to see it.'
        : reply.folder ? 'Scripts saved in changes/' + reply.folder + '. The lab was not changed.'
        : 'This is a preview, nothing was changed. On the right is what each config in the lab would get.'}<//>
      ${reply.notes.map((note, i) => html`<${Notice} key=${i}>${note}<//>`)}
      ${names.map((name, i) => html`<${Card} key=${name} delay=${i * 50} title=${name} right=${html`<${CopyButton} text=${reply.scripts[name]} label="Copy script" />`}>
        <div className="pair">
          <div><h4>Commands</h4><pre className="code">${reply.scripts[name]}</pre></div>
          <div><h4>${reply.written ? 'What changed in the lab' : 'What would change in the lab'}</h4><${Diff} text=${reply.changes[name] || ''} /></div>
        </div>
      <//>`)}
    </div>`}
  </div>`;
}

// ---------------------------------------------------------------- Monitor

function Trend({ rows }) {
  if (!rows.length) return html`<${Empty} icon="monitor">Nothing recorded yet. Press Run and record.<//>`;
  const points = rows.map((r, i) => [rows.length === 1 ? 150 : 8 + 284 * i / (rows.length - 1), 74 - 62 * Number(r.score) / 100]);
  const line = points.map(p => p.join(',')).join(' ');
  return html`<div>
    <svg className="trend" viewBox="0 0 300 84" preserveAspectRatio="none">
      <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="var(--accent)" stopOpacity=".35" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
      <polygon points=${`${points[0][0]},84 ${line} ${points[points.length - 1][0]},84`} fill="url(#trend-fill)" />
      <polyline points=${line} pathLength="1" />
      ${points.map(([x, y], i) => html`<circle key=${i} cx=${x} cy=${y} r="2.6" />`)}
    </svg>
    <ul className="runs">${rows.slice(-6).reverse().map((r, i) => html`<li key=${i}>
      <span>${r.time}</span><b className=${Number(r.score) < 100 ? 'low' : ''}>${r.score}%</b>
      <small>${r.passed}/${r.total} tests · ${r.devices} devices</small></li>`)}</ul>
  </div>`;
}

export function Monitor() {
  const app = useApp();
  const { health, healthError } = app;
  const [busy, setBusy] = useState('');
  const run = async record => {
    setBusy(record ? 'record' : 'run');
    await app.loadHealth(record);
    setBusy('');
    app.toast(record ? 'Tests run and recorded.' : 'Tests run.', 'good');
  };
  const groups = useMemo(() => {
    const found = [];
    (health ? health.tests : []).forEach(t => {
      if (!found.length || found[found.length - 1][0] !== t.group) found.push([t.group, []]);
      found[found.length - 1][1].push(t);
    });
    return found;
  }, [health]);
  let row = 0;

  return html`<div className="page">
    <${PageHead} title="Monitor" sub=${health ? `${health.passed} of ${health.total} tests pass, score ${health.score}%. Each test measures a number in the lab file and compares it with a target.`
      : 'Tests that measure a number in the lab file and compare it with a target.'}>
      <${Button} small icon="play" busy=${busy === 'run'} onClick=${() => run(false)}>Run the tests<//>
      <${Button} small kind="primary" icon="save" busy=${busy === 'record'} onClick=${() => run(true)}>Run and record<//>
    <//>
    ${healthError && html`<${Notice} kind="bad">${healthError}<//>`}
    <div className="split wide-left">
      <div className="stack">
        ${!health && !healthError && html`<${Skeleton} rows=${5} height=${70} />`}
        ${groups.map(([group, tests], g) => html`<${Card} key=${group} delay=${g * 70} title=${group}
          right=${html`<span className="count-pill">${tests.filter(t => t.passed).length}/${tests.length}</span>`}>
          ${tests.map(t => {
            const share = Math.min(100, t.lower_is_better ? t.measured : 100 * t.measured / (t.target || 1));
            return html`<div key=${t.id} className=${'test' + (t.passed ? '' : ' bad')}>
              <span className="mark"><${Icon} name=${t.passed ? 'check' : 'alert'} size=${12} /></span>
              <span className="test-title">${t.title}</span>
              <div className="meter"><i style=${{ width: share + '%', animationDelay: 150 + (row++) * 45 + 'ms' }} /></div>
              <span className="number"><b>${t.measured}</b><small>${t.lower_is_better ? ` ${t.unit}, limit ${t.target}` : ` of ${t.target} ${t.unit}`}</small></span>
              ${t.detail.length > 0 && html`<pre className="why">${t.detail.join('\n')}</pre>`}
            </div>`;
          })}
        <//>`)}
      </div>
      <div className="stack">
        <${Card} delay=${120} title="Score over time" sub="One point for every recorded run. Record a run after each change to see when something broke.">
          ${health && html`<${Trend} rows=${health.history} />`}
        <//>
        <${Card} delay=${200} title="What is not tested here">
          <p className="soft">These tests read the lab file. Pings, DHCP leases and failover times only exist while Packet Tracer runs, so those are the tests in the README table.</p>
        <//>
      </div>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- Checks

export function Checks() {
  const { data } = useApp();
  const [form, setForm] = useState({ subnet: '10.10.8.0/22', a: 'SW-E230', b: 'SW-E110', room: 'E231', students: '15', ip: '10.10.99.25' });
  const [out, setOut] = useState({ command: '', text: '' });
  const [busy, setBusy] = useState('');
  const set = key => e => setForm({ ...form, [key]: e.target.value });
  const run = async (command, values) => {
    setBusy(command);
    const text = await askText('/run', { command, values });
    setBusy('');
    setOut({ command, text });
  };
  const option = name => html`<option key=${name}>${name}</option>`;

  return html`<div className="page">
    <${PageHead} title="Checks" sub="Subnets, the addressing plan, the inventory and the saved configs." />
    <div className="split wide-right">
      <div className="stack">
        <${Card} title="Subnet calculator" sub="Mask, wildcard, first and last host for any subnet.">
          <label className="field"><span>Subnet (address/prefix)</span>
            <input value=${form.subnet} onInput=${set('subnet')} onKeyDown=${e => { if (e.key === 'Enter') run('subnet', { subnet: form.subnet }); }} /></label>
          <${Button} kind="primary" busy=${busy === 'subnet'} onClick=${() => run('subnet', { subnet: form.subnet })}>Calculate<//>
        <//>
        <${Card} delay=${60} title="Addressing plan" sub="Reads plan.csv. Finds bad subnets, bad gateways and overlaps.">
          <${Button} kind="primary" busy=${busy === 'plan'} onClick=${() => run('plan', {})}>Check plan<//>
        <//>
        <${Card} delay=${120} title="Inventory" sub="Reads inventory.csv. Finds duplicate names, duplicate IPs and addresses in the wrong subnet.">
          <${Button} kind="primary" busy=${busy === 'inventory'} onClick=${() => run('inventory', {})}>Check inventory<//>
        <//>
        <${Card} delay=${180} title="Compare two configs" sub="Lines with - are only in the first device, lines with + only in the second.">
          <div className="fields">
            <label className="field"><span>First device</span><select value=${form.a} onChange=${set('a')}>${data.configs.map(option)}</select></label>
            <label className="field"><span>Second device</span><select value=${form.b} onChange=${set('b')}>${data.configs.map(option)}</select></label>
          </div>
          <${Button} kind="primary" busy=${busy === 'compare'} onClick=${() => run('compare', { a: form.a, b: form.b })}>Compare<//>
        <//>
        <${Card} delay=${240} title="New room switch" sub="Makes a config for a new classroom switch, ready to paste into the CLI.">
          <div className="fields">
            <label className="field"><span>Room</span><input value=${form.room} onInput=${set('room')} /></label>
            <label className="field"><span>Student PCs</span><input value=${form.students} onInput=${set('students')} /></label>
          </div>
          <label className="field"><span>Management IP (in 10.10.99.0/24)</span><input value=${form.ip} onInput=${set('ip')} /></label>
          <${Button} kind="primary" busy=${busy === 'template'} onClick=${() => run('template', { room: form.room, ip: form.ip, students: form.students })}>Generate<//>
        <//>
      </div>
      <div className="terminal rise">
        <header><span className="lights"><i /><i /><i /></span><b>${out.command ? 'netcheck ' + out.command : 'output'}</b>
          ${out.text && html`<${CopyButton} text=${out.text} />`}</header>
        ${busy ? html`<pre className="code">Working...</pre>`
          : !out.text ? html`<pre className="code idle">Press a button on the left.<span className="caret" /></pre>`
          : out.command === 'compare' ? html`<div key=${out.text} className="fade"><${Diff} text=${out.text} /></div>`
          : html`<pre key=${out.text} className="code fade">${out.text}</pre>`}
      </div>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- History

export function History() {
  const app = useApp();
  const [reply, setReply] = useState(null);
  const load = async () => setReply(await ask('/history'));
  useEffect(() => { load(); }, []);
  const restore = async name => {
    if (!await app.confirm({ title: 'Put the lab back?', ok: 'Restore', text: 'The lab and the configs folder go back to how they were ' +
      'before this change. Close the lab in Packet Tracer first. The lab as it is now is kept, so you can undo this too.' })) return;
    const answer = await ask('/restore', { backup: name });
    app.toast(answer.error || answer.message, answer.error ? 'bad' : 'good');
    load();
    app.reload();
  };
  const when = name => name.slice(0, 10) + ' ' + name.slice(11, 13) + ':' + name.slice(13, 15) + ':' + name.slice(15, 17);

  return html`<div className="page">
    <${PageHead} title="History" sub="Every change made with this tool, and the copies of the lab kept before each one." />
    ${reply && reply.error && html`<${Notice} kind="bad">${reply.error}<//>`}
    ${!reply && html`<${Skeleton} rows=${4} />`}
    ${reply && !reply.error && html`<div className="split wide-left">
      <${Card} title="Changes" sub=${reply.changes.length + ' so far'}>
        ${!reply.changes.length ? html`<${Empty} icon="history">No changes yet. Make one on the Configure page.<//>`
          : html`<ol className="timeline">${reply.changes.map((row, i) => {
            const devices = (row.devices || '').split(' ').filter(Boolean);
            const inLab = row['written to lab'] === 'yes';
            return html`<li key=${i} className="rise" style=${{ animationDelay: Math.min(i, 12) * 35 + 'ms' }} title=${row.devices}>
              <i className=${inLab ? 'on' : ''} />
              <div><b>${row.change}</b><small>${devices.length > 3 ? devices.length + ' devices' : devices.join(', ')}</small></div>
              <span className=${'tag' + (inLab ? ' on' : '')}>${inLab ? 'in the lab' : 'scripts only'}</span>
              <time>${row.time}</time>
            </li>`;
          })}</ol>`}
      <//>
      <${Card} delay=${80} title="Go back" sub="Restoring puts the lab and the configs folder back the way they were. The lab as it is now is kept first, so you can undo a restore too.">
        ${!reply.backups.length ? html`<${Empty} icon="undo">No copies yet. One is made before every change.<//>`
          : html`<ul className="backups">${reply.backups.map(name => html`<li key=${name}>
            <span>Lab before <b>${when(name)}</b></span>
            <${Button} small icon="undo" onClick=${() => restore(name)}>Restore<//></li>`)}</ul>`}
      <//>
    </div>`}
  </div>`;
}

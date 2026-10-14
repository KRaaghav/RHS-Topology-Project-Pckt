// app.js - the frame around the pages: side bar, config viewer, dialogs and messages

import { html, useState, useEffect, useRef, useCallback, Ctx, ask, Icon, Button, CopyButton } from './lib.js';
import { Overview, Lab, Configure, Monitor, Checks, History } from './pages.js';

const TABS = [['overview', 'Overview', Overview], ['lab', 'Lab', Lab], ['configure', 'Configure', Configure],
              ['monitor', 'Monitor', Monitor], ['checks', 'Checks', Checks], ['history', 'History', History]];

// ---- the running config of one device, slides in from the right

function Sheet({ name, lab, onClose, onConfigure }) {
  const [text, setText] = useState(null);
  const [find, setFind] = useState('');
  const body = useRef(null);
  useEffect(() => {
    ask('/config', { device: name }).then(reply => setText(reply.error ? 'Problem: ' + reply.error : reply.text));
  }, [name]);
  useEffect(() => {
    const first = body.current && body.current.querySelector('mark');
    if (first) first.scrollIntoView({ block: 'center' });
  }, [find]);
  const device = lab && lab.devices.find(d => d.name === name);
  const want = find.toLowerCase();
  const lines = (text || '').split('\n');
  const hits = want ? lines.filter(l => l.toLowerCase().includes(want)).length : 0;

  return html`<div className="sheet" onClick=${e => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="sheet-panel" role="dialog" aria-label=${'Config of ' + name}>
      <header>
        <div><span className="eyebrow">Running config in the lab file</span><h2>${name}</h2>
          <p>${device ? [device.type, device.location, device.ip].filter(Boolean).join(' · ') : ''}${text ? ' · ' + lines.length + ' lines' : ''}</p></div>
        <${Button} small icon="close" aria-label="Close" onClick=${onClose} />
      </header>
      <div className="sheet-tools">
        <label className="search"><${Icon} name="search" size=${15} />
          <input autoFocus value=${find} onInput=${e => setFind(e.target.value)} placeholder="Find in config" aria-label="Find in config" />
          ${want && html`<small>${hits} line${hits === 1 ? '' : 's'}</small>`}</label>
        <${CopyButton} text=${text || ''} />
        <${Button} small icon="configure" onClick=${() => onConfigure(name)}>Configure this device<//>
      </div>
      <pre className="code numbered" ref=${body}>${text == null ? 'Reading...' : lines.map((line, i) => {
        const at = want ? line.toLowerCase().indexOf(want) : -1;
        return html`<span key=${i} className=${'line' + (at >= 0 ? ' hit' : '')}>${at < 0 ? line
          : html`${line.slice(0, at)}<mark>${line.slice(at, at + want.length)}</mark>${line.slice(at + want.length)}`}${'\n'}</span>`;
      })}</pre>
    </aside>
  </div>`;
}

// ---- questions in the middle of the page

function Dialog({ dialog, onDone }) {
  const [room, setRoom] = useState('');
  const [label, setLabel] = useState('');
  const isRoom = dialog.kind === 'room';
  const good = /^[A-Za-z][1-9][0-9]{2}$/.test(room.trim());
  const submit = e => {
    e.preventDefault();
    if (isRoom && !good) return;
    onDone(isRoom ? { room: room.trim().toUpperCase(), label: label.trim() } : true);
  };
  return html`<div className="sheet center" onClick=${e => { if (e.target === e.currentTarget) onDone(null); }}>
    <form className="dialog" role="dialog" aria-label=${dialog.title} onSubmit=${submit}>
      <h2>${dialog.title}</h2>
      <p>${dialog.text}</p>
      ${isRoom && html`<div className="fields">
        <label className="field"><span>Room number</span><input autoFocus value=${room} onInput=${e => setRoom(e.target.value)} placeholder="E231" /></label>
        <label className="field"><span>Name (can stay empty)</span><input value=${label} onInput=${e => setLabel(e.target.value)} placeholder="Art room" /></label>
      </div>`}
      ${isRoom && room && !good && html`<p className="field-problem">A wing letter, the floor, then two digits. E231 is wing E, floor 2.</p>`}
      <div className="dialog-buttons">
        <${Button} type="button" onClick=${() => onDone(null)}>Cancel<//>
        <${Button} type="submit" kind="primary" autoFocus=${!isRoom} disabled=${isRoom && !good}>${dialog.ok}<//>
      </div>
    </form>
  </div>`;
}

// ---- the whole page

function App() {
  const wanted = location.hash.slice(1);
  const [tab, setTab] = useState(TABS.some(t => t[0] === wanted) ? wanted : 'overview');
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || 'dark');
  const [data, setData] = useState(null);
  const [lab, setLab] = useState(null);
  const [labError, setLabError] = useState('');
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState('');
  const [graph, setGraph] = useState(null);
  const [picked, setPicked] = useState([]);          // the devices chosen on the Configure page
  const [sheet, setSheet] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [toasts, setToasts] = useState([]);
  const answer = useRef(null);

  const toast = useCallback((text, kind = '') => {
    const id = Math.random();
    setToasts(list => list.concat([{ id, text, kind }]));
    setTimeout(() => setToasts(list => list.filter(t => t.id !== id)), 6000);
  }, []);

  const confirm = useCallback(question => new Promise(resolve => {
    answer.current = resolve;
    setDialog({ kind: 'confirm', ok: 'OK', ...question });
  }), []);
  const closeDialog = value => { setDialog(null); if (answer.current) answer.current(value); answer.current = null; };

  const loadHealth = useCallback(async record => {
    const reply = await ask('/health', { record: !!record });
    if (reply.error) setHealthError(reply.error);
    else { setHealthError(''); setHealth(reply); }
  }, []);

  const reload = useCallback(async say => {
    // every answer is shown as soon as it is there, the tests take the longest
    await Promise.all([
      fetch('/data').then(r => r.json()).then(setData).catch(() => toast('The program is not running any more. Start netcheck_ui.py again.', 'bad')),
      ask('/lab').then(reply => {
        if (reply.error) setLabError(reply.error);
        else { setLabError(''); setLab(reply); }
      }),
      ask('/graph').then(reply => { if (!reply.error) setGraph(reply); }),
      loadHealth(false)]);
    if (say === true) toast('Lab file read again.', 'good');
  }, [loadHealth, toast]);

  useEffect(() => { reload(); }, []);
  useEffect(() => { location.hash = tab; window.scrollTo(0, 0); }, [tab]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('netcheck-theme', theme); } catch (e) { /* private window, the theme is just not remembered */ }
  }, [theme]);
  useEffect(() => {
    const key = e => {
      if (e.key !== 'Escape') return;
      if (dialog) closeDialog(null); else setSheet(null);
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  });

  const openConfig = name => {
    if (lab && !lab.devices.some(d => d.name === name)) toast(name + ' is a server, it has no IOS config.');
    else setSheet(name);
  };
  const openLab = async () => { const r = await ask('/open'); toast(r.error || r.message, r.error ? 'bad' : ''); };
  const arrange = async () => {
    if (!await confirm({ title: 'Tidy the canvas?', ok: 'Tidy it', text: 'Every device goes back on the grid and the boxes and notes ' +
      'on the canvas are written again. Device configs are not touched. Close the lab in Packet Tracer first.' })) return;
    const r = await ask('/layout');
    toast(r.error || r.message, r.error ? 'bad' : 'good');
  };
  const addRoom = async () => {
    const room = await new Promise(resolve => {
      answer.current = resolve;
      setDialog({ kind: 'room', title: 'Add a room', ok: 'Add the room', text: 'The room gets a 2960 switch, 15 student PCs, a teacher PC ' +
        'and two uplinks, copied from the last room. Close the lab in Packet Tracer first.' });
    });
    if (!room) return;
    toast('Adding room ' + room.room + '...');
    const r = await ask('/add-room', room);
    toast(r.error || r.message, r.error ? 'bad' : 'good');
    if (!r.error) reload();
  };

  const app = { data, lab, labError, health, healthError, graph, picked, setPicked, toast, confirm, reload, loadHealth, openConfig,
                openLab, arrange, addRoom, go: setTab };
  const index = TABS.findIndex(t => t[0] === tab);
  const Page = TABS[index][2];
  const different = lab ? lab.devices.filter(d => d.same_as_file === false).length : 0;
  const status = labError ? ['warn', 'Lab file problem', labError]
    : !lab ? ['', 'Reading the lab...', '']
    : lab.packet_tracer_open ? ['warn', 'Packet Tracer is open', 'Close the lab there before writing.']
    : different ? ['warn', different + ' config(s) differ', 'The lab and the configs folder are not the same.']
    : ['good', 'Lab and configs match', lab.devices.length + ' routers and switches'];

  return html`<${Ctx.Provider} value=${app}>
    <div className="shell">
      <aside className="side">
        <div className="brand"><span className="brand-mark"><i /><i /><i /></span><div><b>NetCheck</b><small>RHS campus network</small></div></div>
        <nav className="nav" style=${{ '--i': index }}>
          <i className="glider" />
          ${TABS.map(([id, title]) => html`<button key=${id} className=${id === tab ? 'on' : ''} aria-current=${id === tab ? 'page' : null}
            onClick=${() => setTab(id)}><${Icon} name=${id} />${title}
            ${id === 'monitor' && health && html`<span className=${'badge' + (health.score < 100 ? ' low' : '')}>${health.score}</span>`}</button>`)}
        </nav>
        <div className="side-foot">
          <div className=${'status ' + status[0]}><i /><div><b>${status[1]}</b><small>${status[2]}</small></div></div>
          <button className="theme" onClick=${() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            <${Icon} name=${theme === 'dark' ? 'sun' : 'moon'} size=${16} />${theme === 'dark' ? 'Light mode' : 'Dark mode'}</button>
        </div>
      </aside>
      <main>${data ? html`<${Page} key=${tab} />` : html`<div className="page"><div className="skeleton" style=${{ height: '180px' }} /></div>`}</main>
    </div>
    ${sheet && html`<${Sheet} key=${sheet} name=${sheet} lab=${lab} onClose=${() => setSheet(null)}
      onConfigure=${name => { setSheet(null); setPicked([name]); setTab('configure'); }} />`}
    ${dialog && html`<${Dialog} dialog=${dialog} onDone=${closeDialog} />`}
    <div className="toasts" aria-live="polite">${toasts.map(t => html`<div key=${t.id} className=${'toast ' + t.kind}>
      <${Icon} name=${t.kind === 'bad' ? 'alert' : t.kind === 'good' ? 'check' : 'eye'} size=${15} />${t.text}</div>`)}</div>
  <//>`;
}

window.ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);

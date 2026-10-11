// lib.js - small things every part of the page uses
//
// The page is written with React, but without a build step: htm turns the html`...`
// strings into React elements in the browser, so there is nothing to compile or install.

const R = window.React;
export const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = R;
export const html = window.htm.bind(R.createElement);

// everything the pages share (the lab, the test results, toast(), confirm(), ...)
export const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export const VLAN_COLOURS = { 10: '#f5c451', 20: '#ff9f5a', 30: '#4ade80', 40: '#f87171', 70: '#4fd1e0', 99: '#b794f6' };

// ---- talking to netcheck_ui.py

export async function ask(path, body) {
  try {
    return await (await fetch(path, { method: 'POST', body: JSON.stringify(body || {}) })).json();
  } catch (e) {
    return { error: 'The program is not running any more. Start netcheck_ui.py again.' };
  }
}

export async function askText(path, body) {
  try {
    return await (await fetch(path, { method: 'POST', body: JSON.stringify(body || {}) })).text();
  } catch (e) {
    return 'The program is not running any more. Start netcheck_ui.py again.';
  }
}

// ---- hooks

// a number that counts up to its value instead of jumping there
export function useCount(target, ms = 900) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (target == null || isNaN(target)) return undefined;
    const start = performance.now();
    const first = from.current;
    let frame;
    const step = now => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(first + (target - first) * eased));
      if (t < 1) frame = requestAnimationFrame(step);
      else from.current = target;
    };
    frame = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(frame); from.current = target; };
  }, [target, ms]);
  return shown;
}

// the width of an element, kept up to date when the window changes size
export function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return undefined;
    const watch = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    watch.observe(ref.current);
    return () => watch.disconnect();
  }, []);
  return [ref, width];
}

// ---- icons (drawn as lines, 24 x 24)

const ICONS = {
  overview: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  lab: 'M2 4h20v6H2zM2 14h20v6H2zM6 7h.01M6 17h.01M10 7h4M10 17h4',
  configure: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  monitor: 'M22 12h-4l-3 9L9 3l-3 9H2',
  checks: 'M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3',
  history: 'M12 8v4l3 2M3.1 11a9 9 0 1 1 .5 4M3 4v7h7',
  refresh: 'M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8M21 3v6h-6M3 21v-6h6',
  plus: 'M12 5v14M5 12h14',
  open: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
  search: 'M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  close: 'M18 6 6 18M6 6l12 12',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  zap: 'M13 2 3 14h9l-1 8 10-12h-9z',
  play: 'M5 3l14 9-14 9z',
  grid: 'M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18',
  check: 'M20 6 9 17l-5-5',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  save: 'M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2zM17 21v-8H7v8M7 3v5h8',
  eye: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  undo: 'M3 7v6h6M3.5 13a9 9 0 1 0 2.1-9.4L3 7',
  building: 'M3 21h18M5 21V5l7-3 7 3v16M9 9h.01M15 9h.01M9 13h.01M15 13h.01M10 21v-4h4v4',
  share: 'M12 2v6M12 22v-6M5 12H2M22 12h-3M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
};

export function Icon({ name, size = 18 }) {
  return html`<svg className="icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d=${ICONS[name] || ''} /></svg>`;
}

// ---- small parts

export function Button({ icon, kind = 'ghost', small, busy, children, ...rest }) {
  return html`<button className=${'btn ' + kind + (small ? ' small' : '') + (busy ? ' busy' : '')} disabled=${busy || rest.disabled} ...${rest}>
    ${icon && html`<${Icon} name=${busy ? 'refresh' : icon} size=${small ? 15 : 16} />`}${children && html`<span>${children}</span>`}
  </button>`;
}

export function Card({ title, sub, right, className = '', delay = 0, children }) {
  return html`<section className=${'card rise ' + className} style=${{ animationDelay: delay + 'ms' }}>
    ${(title || right) && html`<header className="card-head">
      <div><h2>${title}</h2>${sub && html`<p>${sub}</p>`}</div>${right}
    </header>`}
    ${children}
  </section>`;
}

// a choice between a few things, the marker slides to the chosen one
export function Segments({ value, options, onChange }) {
  const index = Math.max(0, options.findIndex(o => o[0] === value));
  return html`<div className="segments" style=${{ '--n': options.length, '--i': index }} role="tablist">
    <i className="segments-mark" />
    ${options.map(([id, title, icon]) => html`<button key=${id} role="tab" aria-selected=${id === value}
      className=${id === value ? 'on' : ''} onClick=${() => onChange(id)}>${icon && html`<${Icon} name=${icon} size=${14} />`}${title}</button>`)}
  </div>`;
}

export function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setDone(true);
    setTimeout(() => setDone(false), 1200);
  };
  return html`<${Button} small icon=${done ? 'check' : 'copy'} onClick=${copy}>${done ? 'Copied' : label}<//>`;
}

// text with + and - lines in colour
export function Diff({ text }) {
  return html`<pre className="code">${(text || '').split('\n').map((line, i) => html`<span key=${i}
    className=${line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'at' : ''}>${line + '\n'}</span>`)}</pre>`;
}

export function Skeleton({ rows = 3, height = 54 }) {
  return html`<div className="skeletons">${Array.from({ length: rows }, (_, i) =>
    html`<div key=${i} className="skeleton" style=${{ height: height + 'px', animationDelay: i * 120 + 'ms' }} />`)}</div>`;
}

export function Empty({ icon = 'grid', children }) {
  return html`<div className="empty"><${Icon} name=${icon} size=${22} /><p>${children}</p></div>`;
}

export function Notice({ kind = '', children }) {
  return html`<div className=${'notice rise ' + kind}><${Icon} name=${kind === 'bad' ? 'alert' : kind === 'good' ? 'check' : 'eye'} size=${16} /><span>${children}</span></div>`;
}

// the score as a ring that fills up
export function Ring({ score, size = 132 }) {
  const shown = useCount(score == null ? 0 : score, 1100);
  const round = 2 * Math.PI * 52;
  const low = score != null && score < 100;
  return html`<svg className=${'ring' + (low ? ' low' : '')} width=${size} height=${size} viewBox="0 0 120 120">
    <defs><linearGradient id="ring-fill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stopColor="var(--ring-a)" /><stop offset="1" stopColor="var(--ring-b)" /></linearGradient></defs>
    <circle className="ring-track" cx="60" cy="60" r="52" fill="none" strokeWidth="10" />
    <circle className="ring-value" cx="60" cy="60" r="52" fill="none" strokeWidth="10" strokeLinecap="round" stroke="url(#ring-fill)"
      strokeDasharray=${round} strokeDashoffset=${round - round * (score || 0) / 100} transform="rotate(-90 60 60)" />
    <text x="60" y="64" textAnchor="middle" className="ring-number">${score == null ? '–' : shown}</text>
    <text x="60" y="82" textAnchor="middle" className="ring-unit">out of 100</text>
  </svg>`;
}

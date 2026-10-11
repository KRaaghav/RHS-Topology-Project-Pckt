// views.js - the two pictures on the Overview: the topology and the building
//
// Both are drawn from what /graph sends, and that comes from the cables and configs in the
// .pkt file and from inventory.csv. Nothing here is typed in by hand except the made up
// rooms of the building that are not in the lab.

import { html, useState, useEffect, useMemo, useWidth, useApp, ask, Icon, Button, Segments, VLAN_COLOURS } from './lib.js';

// ---------------------------------------------------------------- topology

const W = 1200;
const LAYER_Y = [58, 154, 250, 346];
const ACCESS_Y = 462;
const LAYER_KIND = ['internet', 'edge', 'core', 'dist'];

function place(graph) {
  const where = {};
  const kind = {};
  const middle = W / 2 + 40;
  graph.layers.forEach((layer, i) => {
    const y = LAYER_Y[i];
    layer.names.forEach((name, n) => {
      where[name] = i === 0 ? [middle + n * 210, y] : [middle + (n === 0 ? -160 : 160), y];
      kind[name] = LAYER_KIND[i];
    });
  });
  const step = (W - 60) / graph.access.length;
  graph.access.forEach((a, i) => {
    where[a.name] = [30 + step * (i + 0.5), ACCESS_Y];
    kind[a.name] = a.kind;
  });
  return { where, kind, step };
}

function linkPath([x1, y1], [x2, y2]) {
  if (y1 === y2) return `M${x1} ${y1} L${x2} ${y2}`;
  if (y1 > y2) [x1, y1, x2, y2] = [x2, y2, x1, y1];
  const bend = (y1 + y2) / 2;
  return `M${x1} ${y1 + 17} C${x1} ${bend} ${x2} ${bend} ${x2} ${y2 - 17}`;
}

export function Topology({ graph }) {
  const app = useApp();
  const [hover, setHover] = useState(null);
  const [breaking, setBreaking] = useState(false);
  const [dead, setDead] = useState(null);           // what /fail said about the broken device
  const { where, kind, step } = useMemo(() => place(graph), [graph]);
  const nodeWidth = Math.min(100, step - 10);

  useEffect(() => { if (!breaking) setDead(null); }, [breaking]);

  const click = async name => {
    if (!breaking) { app.openConfig(name); return; }
    if (dead && dead.device === name) { setDead(null); return; }
    const reply = await ask('/fail', { device: name });
    if (reply.error) app.toast(reply.error, 'bad');
    else setDead(reply);
  };

  const cut = new Set(dead ? dead.cut : []);
  const state = name => (dead && dead.device === name ? ' dead' : cut.has(name) ? ' cut' : '');

  return html`<div className="topology">
    <div className="topology-bar">
      <p>${breaking
        ? 'Click a router or switch to switch it off and see who loses the internet.'
        : 'Drawn from the cables inside the lab file. Click a router or switch to read its config.'}</p>
      <${Button} small kind=${breaking ? 'danger' : 'ghost'} icon="zap" onClick=${() => setBreaking(!breaking)}>
        ${breaking ? 'Stop breaking things' : 'Break something'}<//>
    </div>
    ${dead && html`<div className=${'verdict rise ' + (dead.lost ? 'bad' : 'good')}>
      <b>${dead.device} is off.</b> ${dead.lost
        ? `${dead.lost} of ${dead.hosts} PCs and servers lose the internet${dead.lost_names.length ? ' (' + dead.lost_names.join(', ') + (dead.lost > dead.lost_names.length ? ', ...' : '') + ')' : ''}. ${dead.why}`
        : `0 of ${dead.hosts} PCs and servers lose the internet. ${dead.why}`}
    </div>`}
    <div className="scroll-x">
      <svg className=${'topo' + (hover ? ' hovering' : '') + (breaking ? ' breaking' : '')} viewBox=${`0 0 ${W} 610`}>
        ${graph.layers.map((layer, i) => html`<g key=${layer.title}>
          <rect className=${'band k-' + LAYER_KIND[i]} x="150" y=${LAYER_Y[i] - 36} width=${W - 170} height="72" rx="14" />
          <text className="band-title" x="14" y=${LAYER_Y[i] - 2}>${layer.title}</text>
          <text className="band-note" x="14" y=${LAYER_Y[i] + 14}>${layer.note}</text>
        </g>`)}
        <text className="band-title" x="14" y=${ACCESS_Y - 30}>Access</text>

        <g>${graph.links.map((link, i) => {
          const off = dead && (dead.device === link.a || dead.device === link.b);
          const hot = hover && (hover === link.a || hover === link.b);
          const d = linkPath(where[link.a], where[link.b]);
          return html`<g key=${link.a + link.b} className=${'link' + (link.count > 1 ? ' thick' : '') + (hot ? ' hot' : '') + (off ? ' off' : '')}>
            <path className="wire" d=${d} style=${{ animationDelay: 200 + i * 18 + 'ms' }} />
            ${!off && html`<path className="flow" d=${d} style=${{ animationDelay: -(i % 7) * 0.4 + 's' }} />`}
          </g>`;
        })}</g>
        ${graph.links.filter(l => l.count > 1).map(l => {
          const [x1, y1] = where[l.a];
          const [x2, y2] = where[l.b];
          return html`<text key=${'t' + l.a + l.b} className="lacp" x=${(x1 + x2) / 2} y=${(y1 + y2) / 2 - 7} textAnchor="middle">LACP x${l.count}</text>`;
        })}

        ${graph.access.map(a => {
          const [x, y] = where[a.name];
          const dots = [];
          Object.keys(a.counts).sort((p, q) => p - q).forEach(vlan => {
            for (let n = 0; n < a.counts[vlan]; n++) dots.push(vlan);
          });
          const rows = Math.ceil(dots.length / 4);
          return html`<g key=${'h' + a.name} className=${'hosts' + state(a.name)}>
            ${dots.map((vlan, n) => html`<circle key=${n} cx=${x - 15 + (n % 4) * 10} cy=${y + 32 + Math.floor(n / 4) * 10} r="3.4"
              fill=${VLAN_COLOURS[vlan] || '#888'} style=${{ animationDelay: 500 + n * 14 + 'ms' }} />`)}
            <text className="room-label" x=${x} y=${y + 42 + rows * 10} textAnchor="middle">${a.label}</text>
          </g>`;
        })}

        ${Object.keys(where).map((name, i) => {
          const [x, y] = where[name];
          const width = kind[name] === 'internet' || LAYER_KIND.includes(kind[name]) ? 118 : nodeWidth;
          return html`<g key=${name} className=${'node k-' + kind[name] + state(name) + (hover === name ? ' hot' : '')}
            style=${{ animationDelay: i * 28 + 'ms' }} tabIndex="0" role="button" aria-label=${name}
            onMouseEnter=${() => setHover(name)} onMouseLeave=${() => setHover(null)}
            onClick=${() => click(name)} onKeyDown=${e => { if (e.key === 'Enter') click(name); }}>
            <rect x=${x - width / 2} y=${y - 17} width=${width} height="34" rx="10" />
            <text x=${x} y=${y + 4} textAnchor="middle" style=${{ fontSize: width < 80 ? '9.5px' : width < 100 ? '10.5px' : '12px' }}>${name}</text>
          </g>`;
        })}

        ${graph.spans.map(span => {
          const first = where['SW-' + span.rooms[0]][0] - step / 2 + 6;
          const last = where['SW-' + span.rooms[span.rooms.length - 1]][0] + step / 2 - 6;
          return html`<g key=${span.wing} className="wing-span">
            <path d=${`M${first} 570 v8 H${last} v-8`} />
            <text x=${(first + last) / 2} y="598" textAnchor="middle">${span.wing} wing</text>
          </g>`;
        })}
      </svg>
    </div>
    <div className="vlans">
      ${graph.vlans.map((v, i) => html`<div key=${v.vlan} className="vlan rise" style=${{ animationDelay: 300 + i * 60 + 'ms' }}>
        <i style=${{ background: VLAN_COLOURS[v.vlan] || '#888' }} />
        <div><b>VLAN ${v.vlan} <span>${v.name}</span></b><small>${v.network}</small><small>gateway ${v.gateway}</small></div>
      </div>`)}
    </div>
  </div>`;
}

// ---------------------------------------------------------------- building

// what is in the main hall of each floor (made up). floorplan.svg and the canvas of the lab
// show the school as a flat floor plan, this view stacks the floors instead
const HALL = {
  1: [['Main office', 'counseling, nurse', 'office', 20], ['MDF', 'server room, IT', 'mdf', 16],
      ['Commons', 'cafeteria', '', 30], ['Gym', 'lockers, PE', '', 34]],
  2: [['Staff lounge', 'workroom', '', 20], ['IDF closet', 'riser from MDF', 'idf', 16],
      ['Open to commons', 'below', 'void', 30], ['Gym', 'bleachers', '', 34]],
};
const FILLER = ['Stairs', 'Classroom', 'Classroom', 'Restrooms', 'Classroom', 'Classroom'];
const PLACES = [0, 1].flatMap(side => [1, 3, 5, 2, 4, 0].map(slot => side + '-' + slot));

export function Building({ graph }) {
  const app = useApp();
  const [mode, setMode] = useState('3d');
  const [floor, setFloor] = useState('all');
  const [picked, setPicked] = useState(null);
  const [ref, width] = useWidth();
  const floors = useMemo(() => {
    const found = new Set(['1']);
    Object.values(graph.wings).forEach(byFloor => Object.keys(byFloor).forEach(f => found.add(f)));
    return Array.from(found).sort();
  }, [graph]);
  const scale = width ? Math.min(1, width / (mode === '3d' ? 900 : 800)) : 1;
  const info = picked && graph.access.find(a => a.name === picked);

  const plate = number => html`<div key=${number} className=${'plate' + (floor !== 'all' && floor !== number ? ' faded' : '')}
    style=${{ '--level': Number(number) - 1 }}>
    <span className="plate-name">Floor ${number}</span>
    <div className="hall">
      ${(HALL[number] || HALL[2]).map(([name, more, what, share]) => {
        const sw = what === 'office' ? 'SW-OFFICE' : what === 'mdf' ? 'SW-MDF' : null;
        return html`<button key=${name} className=${'block ' + what + (sw && picked === sw ? ' picked' : '')} style=${{ flex: share }}
          disabled=${!sw} onClick=${() => setPicked(sw)}>
          <b>${name}</b><small>${more}</small>${sw && html`<i className="switch-dot" />`}
        </button>`;
      })}
    </div>
    <div className="spine"><span>main hall</span></div>
    <div className="wings">
      ${Object.keys(graph.wings).map(wing => {
        const inLab = graph.wings[wing][number] || [];
        const taken = {};
        inLab.forEach((room, i) => { taken[PLACES[i]] = room; });
        const row = side => html`<div className="rooms">${[0, 1, 2, 3, 4, 5].map(slot => {
          const room = taken[side + '-' + slot];
          if (!room) return html`<div key=${slot} className="room">${FILLER[(slot + 3 * side) % 6]}</div>`;
          return html`<button key=${slot} className=${'room lab' + (picked === 'SW-' + room ? ' picked' : '')}
            onClick=${() => setPicked('SW-' + room)}><b>${room}</b><i className="switch-dot" /></button>`;
        })}</div>`;
        return html`<div key=${wing} className="wing">
          <span className="wing-name">${wing} wing</span>
          ${row(0)}<div className="corridor"><i className=${inLab.length ? 'run' : ''} /></div>${row(1)}
        </div>`;
      })}
    </div>
  </div>`;

  return html`<div className="building-view">
    <div className="topology-bar">
      <p>A made up sketch of the school, not the real floor plan. The gold rooms are in the lab. Click one.</p>
      <div className="bar-tools">
        <${Segments} value=${floor} onChange=${setFloor} options=${[['all', 'Both floors']].concat(floors.map(f => [f, 'Floor ' + f]))} />
        <${Segments} value=${mode} onChange=${setMode} options=${[['3d', '3D'], ['flat', 'Flat']]} />
      </div>
    </div>
    <div className="building-grid">
      <div ref=${ref} className=${'scene m-' + mode} style=${{ '--scale': scale, '--floors': floors.length }}>
        <div className="building">${floors.map(plate)}</div>
      </div>
      <aside className="room-info">
        ${info ? html`<div className="rise" key=${info.name}>
          <span className="eyebrow">${info.kind === 'room' ? `${info.wing} wing · floor ${info.floor}` : 'Main hall · floor 1'}</span>
          <h3>${info.kind === 'room' ? 'Room ' + info.room : info.label}</h3>
          <p>${info.kind === 'room' ? (info.named || 'Classroom') : info.kind === 'mdf' ? 'Where the routers, core and distribution switches stand.' : 'Office, counseling and the nurse.'}</p>
          <ul className="facts">
            <li><span>Switch</span><b>${info.name}</b></li>
            ${Object.keys(info.counts).sort((p, q) => p - q).map(vlan => html`<li key=${vlan}>
              <span><i style=${{ background: VLAN_COLOURS[vlan] || '#888' }} />VLAN ${vlan}</span>
              <b>${info.counts[vlan]} ${vlan === '70' ? 'servers' : vlan === '40' ? (info.counts[vlan] === 1 ? 'thing' : 'things') : info.counts[vlan] === 1 ? 'PC' : 'PCs'}</b></li>`)}
            <li><span>Uplinks</span><b>${info.uplinks.join(' + ')}</b></li>
          </ul>
          <${Button} kind="primary" icon="eye" onClick=${() => app.openConfig(info.name)}>Read the switch config<//>
        </div>` : html`<div className="rise">
          <span className="eyebrow">Legend</span>
          <ul className="legend">
            <li><i className="sw lab" />Room in the lab: a 2960 switch, 15 student PCs, 1 teacher PC, a smartboard</li>
            <li><i className="sw office" />Main office: SW-OFFICE, 6 PCs, printer, bell, front door</li>
            <li><i className="sw mdf" />MDF: routers, core, distribution, servers</li>
            <li><i className="sw" />Not in the lab, only there so it looks like a school</li>
            <li><i className="sw run" />Two uplinks from every room to the MDF</li>
          </ul>
          <p className="hint"><${Icon} name="building" size=${15} /> ${graph.spans.reduce((n, span) => n + span.rooms.length, 0)} classrooms in
            ${' ' + Object.keys(graph.wings).length} wings on ${floors.length} floors.</p>
        </div>`}
      </aside>
    </div>
  </div>`;
}

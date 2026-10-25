// The canvas's side of remote control (monet/remote.py; from Adam Designer's remote-tab.ts). While the person has it
// switched on, this page dials the server and answers what their agent asks of it, by name: what the screen shows, go
// to a project, a Note or an area, and a picture of the view. It runs no code of the agent's: what the agent changes
// goes through the server's tools and their rules. Off, there is no line and nothing here answers anything.
//
// It ends by itself after 15 minutes in which neither the person did anything here nor the agent asked anything: the
// page tells the server when a key or the mouse was used (at most every ten seconds) and counts the time down.

const MAX = 200_000, PICTURE = 12_000_000;      // characters of an answer, and of one with a picture in it

let view = null, ws = null, retry = 0, again = 0, deadline = 0, stirred = false, said = '';
let base = '', app = null;
const listeners = new Set();
const changed = () => { for (const fn of listeners) fn(); };

/** What a value of the page is as JSON: Sets and Maps as lists and objects, a cycle cut, three.js kept short. */
function json(value, max = MAX) {
  const seen = new WeakSet();
  const text = JSON.stringify(value === undefined ? null : value, (_k, v) => {
    if (v instanceof Set) return [...v];
    if (v instanceof Map) return Object.fromEntries(v);
    if (typeof v === 'function') return undefined;
    if (v && typeof v === 'object') {
      if (v.isObject3D) return { type: v.type, name: v.name, uuid: v.uuid };
      if (ArrayBuffer.isView(v)) return `[${v.constructor.name} of ${v.length}]`;
      if (seen.has(v)) return '[seen]';
      seen.add(v);
    }
    return v;
  }) ?? 'null';
  return text.length > max ? JSON.stringify({ cut: true, start: text.slice(0, max) }) : text;
}

async function answer(m) {
  try {
    switch (m.what) {
      case 'screen': return { ok: true, json: json(app.screen()) };
      case 'goto': return { ok: true, json: json(await app.goto(m.args)) };
      case 'view': return { ok: true, json: json(app.view(), PICTURE) };
      default: return { ok: false, json: json(`the canvas does not know "${m.what}"`) };
    }
  } catch (e) { return { ok: false, json: json(e instanceof Error ? `${e.name}: ${e.message}` : String(e)) }; }
}

/** "I am here, and this is what I show": when that changes, and every 25 s so that nothing hangs up on a quiet line. */
function say(always = false) {
  if (ws?.readyState !== WebSocket.OPEN) return;
  const now = JSON.stringify({ t: 'state', ...app.where(), hidden: document.hidden });
  if (now === said && !always) return;
  said = now;
  ws.send(now);
}

function hangUp() {
  clearTimeout(again);
  const old = ws; ws = null; said = '';
  if (old) { old.onclose = null; old.close(); }
  changed();
}

function dial() {
  if (ws || !view?.on) return;
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${base}/remote/tab`);
  ws = socket;
  socket.onopen = () => { retry = 0; said = ''; say(); changed(); };
  socket.onmessage = (e) => {
    let m;
    try { m = JSON.parse(String(e.data)); } catch { return; }
    // the time started again: the agent asked something, or I did something in another tab
    if (m.t === 'left') { deadline = performance.now() + m.ms; changed(); return; }
    if (m.t !== 'ask') return;
    answer(m).then((r) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ t: 'result', id: m.id, ...r })); say(); });
  };
  socket.onclose = (e) => {
    if (ws !== socket) return;
    ws = null;
    if (e.code === 4001 || e.code === 4003) { refresh(); return; }      // switched off (here, or in another browser of mine)
    changed();
    if (view?.on) again = setTimeout(dial, Math.min(30_000, 2000 * 2 ** retry++));
  };
}

function take(next) {
  view = next;
  deadline = performance.now() + (next?.left ?? 0);
  if (next?.on) dial(); else hangUp();
  changed();
}

async function refresh() {
  try {
    const r = await fetch(`${base}/remote`, { cache: 'no-store' });
    if (r.ok) take(await r.json());
  } catch { /* the server is away; the next look will tell */ }
  return view;
}

/** The person did something here: the 15 minutes start again, shown at once, told to the server in a moment. */
function stir() {
  if (!view?.on) return;
  stirred = true;
  deadline = performance.now() + view.idle;
}

export const remote = {
  /** api: '/w/<username>/api'. hands: what the page answers with (where, screen, goto, view). first: the state's own view. */
  start(api, hands, first) {
    base = api; app = hands;
    take(first ?? null);
    if (first === undefined) refresh();
    window.addEventListener('hashchange', () => say());
    document.addEventListener('visibilitychange', () => say());
    setInterval(() => say(true), 25_000);
    for (const type of ['pointerdown', 'keydown', 'wheel']) window.addEventListener(type, stir, { capture: true, passive: true });
    setInterval(() => {
      if (stirred && ws?.readyState === WebSocket.OPEN) { stirred = false; ws.send(JSON.stringify({ t: 'alive' })); }
      // the time ran out while this page was looking: the server has ended it; find out, and say so
      if (view?.on && performance.now() > deadline + 1500) refresh();
    }, 10_000);
  },
  /** what the page shows changed (another Note, another area): said to the server if it is another */
  say: () => say(),
  /** ms until it ends by itself, as this page counts it */
  left: () => (view?.on ? Math.max(0, deadline - performance.now()) : 0),
  view: () => view,
  connected: () => ws?.readyState === WebSocket.OPEN,
  onChange(fn) { listeners.add(fn); },
  refresh,
  /** the switch */
  async set(on) {
    const r = await fetch(`${base}/remote`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ on }) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `error ${r.status}`);
    take(data);
  },
};

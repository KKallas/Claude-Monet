// The canvas's line to the person's agent (monet/remote.py; from Adam Designer's remote-tab.ts). This page dials the
// server and answers what the agent asks of it, by name: what the screen shows, go to a project, a Note or an area, and
// a picture of the view. It runs no code of the agent's: what the agent changes goes through the server's tools and
// their rules. Only the person's own page dials, never an admin's looking in.
//
// There was a switch before this (remote control, with 15 minutes on its clock): taken out on 2026-11-13. The agent
// runs on the person's own computer, started by their own hand; its key opens its door.

const MAX = 200_000, PICTURE = 12_000_000;      // characters of an answer, and of one with a picture in it

let view = null, ws = null, retry = 0, again = 0, said = '';
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

function dial() {
  if (ws || !view) return;
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${base}/remote/tab`);
  ws = socket;
  socket.onopen = () => { retry = 0; said = ''; say(); changed(); };
  socket.onmessage = (e) => {
    let m;
    try { m = JSON.parse(String(e.data)); } catch { return; }
    if (m.t !== 'ask') return;
    answer(m).then((r) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ t: 'result', id: m.id, ...r })); say(); });
  };
  socket.onclose = (e) => {
    if (ws !== socket) return;
    ws = null;
    changed();
    if (e.code === 4003) return;      // not mine to dial (logged out, or looking in at another's)
    again = setTimeout(dial, Math.min(30_000, 2000 * 2 ** retry++));
  };
}

function take(next) {
  view = next;
  if (next) dial();
  else { clearTimeout(again); const old = ws; ws = null; said = ''; if (old) { old.onclose = null; old.close(); } }
  changed();
}

async function refresh() {
  try {
    const r = await fetch(`${base}/remote`, { cache: 'no-store' });
    if (r.ok) take(await r.json());
  } catch { /* the server is away; the next look will tell */ }
  return view;
}

export const remote = {
  /** api: '/w/<username>/api'. hands: what the page answers with (where, screen, goto, view). first: the state's own
   *  view: null when this is not the person's own workspace, and then nothing dials. */
  start(api, hands, first) {
    base = api; app = hands;
    take(first ?? null);
    window.addEventListener('hashchange', () => say());
    document.addEventListener('visibilitychange', () => say());
    setInterval(() => say(true), 25_000);
  },
  /** what the page shows changed (another Note, another area): said to the server if it is another */
  say: () => say(),
  /** { seen, tabs, recent }: when the agent was last here, the pages it can see, what it changed lately */
  view: () => view,
  connected: () => ws?.readyState === WebSocket.OPEN,
  onChange(fn) { listeners.add(fn); },
  refresh,
};

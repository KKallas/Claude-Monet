// The terminal of the canvas: a panel along the bottom of the view that talks to Monet local on this very computer
// (skill/monet/scripts/local.py), which runs the person's own agent (claude, codex) or a shell in the project's folder.
//
// The line goes from this page straight to 127.0.0.1: the server is not in between and never sees a byte of it. Monet
// local answers only a page of the Monet it is linked to, and only with a token it knows. This page makes one, keeps it
// in this browser and puts it in the one line it gives the person to start Monet local with (--pair: it goes from the
// page to the person's own terminal by their hand, never to the server). The page picks what runs by name, from Monet
// local's own list; it sends keys, never a command line. What is typed here is the person; the agent it starts reaches Monet through the agent's door,
// like any other.

const KEEP = 'monet.local', PORTS = [47821, 47822, 47823, 47824],      // where Monet local listens: the first that was free (local.py)
   NAMES = { log: 'Activity', claude: 'Claude Code', codex: 'Codex', shell: 'Shell' };
const LINK = /#local=(\d{2,5})\.([A-Za-z0-9_-]{16,})\s*$/;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function paired(text) {
  const m = LINK.exec(text);
  if (!m) return null;
  const pair = { port: Number(m[1]), token: m[2] };
  try { localStorage.setItem(KEEP, JSON.stringify(pair)); } catch { /* kept for this visit only */ }
  return pair;
}
let pair = null;
try { pair = JSON.parse(localStorage.getItem(KEEP)); } catch { /* none */ }
if (!pair?.token) {      // this browser's own, made once: it is in the line the person starts Monet local with
  pair = { port: PORTS[0], token: btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(24)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') };
  try { localStorage.setItem(KEEP, JSON.stringify(pair)); } catch { /* kept for this visit only */ }
}
// the link Monet local printed, opened: taken before the canvas reads the fragment as a project, and gone from the address
const came = paired(location.hash);
if (came) { pair = came; history.replaceState(null, '', location.pathname + location.search); }

/** hooks: { remote (remote.js), mine(): is this my own workspace, project(): the one the canvas shows, link(): my agent link } */
export function createTerminal(view, button, hooks) {
  const root = document.createElement('div');
  root.className = 'term';
  root.hidden = true;
  root.innerHTML = `<div class="term-grip" title="drag: how tall the terminal is"></div>
    <div class="term-bar"><span class="term-tabs"></span><span class="term-where"></span><span class="sp"></span>
      <button data-term="end" title="end what runs here (it keeps running when this panel is only closed)" hidden>End</button>
      <button data-term="close" title="close the panel: what runs in it runs on">×</button></div>
    <div class="term-body"><div class="term-x"></div><div class="term-help" hidden></div></div>`;
  view.append(root);
  const $ = (q) => root.querySelector(q);
  const enc = new TextEncoder();
  let term = null, fit = null, ws = null, run = 'log', about = null, greeted = false, over = false, h = 320, again = 0;
  try { h = Number(localStorage.getItem('monet.term.h')) || h; run = localStorage.getItem('monet.term.run') || run; } catch { /* defaults */ }

  async function xterm() {
    if (term) return;
    document.head.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: 'https://cdn.jsdelivr.net/npm/@xterm/xterm@6.0.0/css/xterm.css' }));
    const [{ Terminal }, { FitAddon }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]);
    term = new Terminal({ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 12.5, cursorBlink: true, scrollback: 5000,
      allowProposedApi: true, theme: { background: '#00000000', foreground: '#b6ffd0', cursor: '#5ef6ff', cursorAccent: '#06110c', selectionBackground: '#1f5a48', green: '#5dff9b', brightGreen: '#8dffb8', yellow: '#ffd75e', brightYellow: '#ffe58a', red: '#ff6b81', brightRed: '#ff8fa0', cyan: '#5ef6ff', brightCyan: '#9dfaff', blue: '#6fb1ff', magenta: '#ff7ad9', brightBlack: '#5b8a72' },
      allowTransparency: true });
    fit = new FitAddon();
    term.loadAddon(fit);
    term.open($('.term-x'));
    const send = (text) => { if (ws?.readyState === WebSocket.OPEN && greeted && run !== 'log') ws.send(enc.encode(text)); };
    term.onData(send);
    term.onBinary((d) => { if (ws?.readyState === WebSocket.OPEN && greeted && run !== 'log') ws.send(Uint8Array.from(d, (c) => c.charCodeAt(0))); });
    term.onResize(({ cols, rows }) => { if (ws?.readyState === WebSocket.OPEN && greeted) ws.send(JSON.stringify({ t: 'resize', cols, rows })); });
    new ResizeObserver(() => { if (!root.hidden) try { fit.fit(); } catch { /* not laid out yet */ } }).observe($('.term-body'));
  }

  function tabs() {
    const can = about?.runs ?? ['claude', 'codex', 'shell'], live = new Set(about?.running ?? []);
    $('.term-tabs').innerHTML = ['log', ...can].map((n) => `<button data-run="${n}" class="${n === run ? 'on' : ''}" title="${n === 'log' ? 'what Monet local is doing on your computer: the same lines it says in your own terminal' : `${NAMES[n]} in the project's folder on this computer`}">${NAMES[n]}${live.has(n) ? ' <i>●</i>' : ''}</button>`).join('');
    $('.term-where').textContent = about ? `${about.project} · ${about.folder}` : '';
    $('.term-where').classList.toggle('warn', !!about && !!hooks.project() && about.project !== hooks.project());
    $('.term-where').title = about && hooks.project() && about.project !== hooks.project() ? `Monet local works on ${about.project}; the canvas shows ${hooks.project()}` : '';
    $('[data-term="end"]').hidden = !(greeted && run !== 'log');
  }

  /** The one line that starts everything on the person's computer: this server's script, their agent link, the project
   *  on screen, and this browser's token. */
  function line() {
    const link = hooks.link();
    return link ? `uv run ${location.origin}/start.py ${link} ${hooks.project() || '<project>'} --pair=${pair.token}` : '';
  }

  function help(why) {
    const box = $('.term-help');
    box.hidden = !why;
    $('.term-x').style.visibility = why ? 'hidden' : '';
    if (!why) return;
    if (why === 'none') { box.innerHTML = `<h3>${NAMES[run]} is not installed on this computer.</h3><p>Choose another above.</p>`; return; }
    const cmd = line();
    box.innerHTML = `<h3>${hooks.project() ? `Work on ${esc(hooks.project())} on this computer` : 'Open a project first'}</h3>
      ${!hooks.mine() ? '<p>Only the person whose workspace this is can start their agent here.</p>' : `
      <p>Paste this one line into a terminal on this computer and leave it running:</p>
      <div class="term-cmd"><pre>${esc(cmd)}</pre><button data-term="copy">Copy</button></div>
      <p class="term-wait"><i></i>looking for it on this computer… this panel comes alive by itself when it runs.</p>
      <p class="muted">It keeps the project's files in <code>~/monet/${esc(hooks.project() || '…')}</code>, builds them there as they change, and shows here what it does.
        It needs <a href="https://docs.astral.sh/uv/getting-started/installation/" target="_blank" rel="noopener">uv</a>.
        The line holds your agent key: it is a password. This page talks to your computer directly; nothing of the terminal goes through ${esc(location.host)}.
        ${why === 'token' ? '<br><b>Monet local runs here but was started for another browser: stop it (Ctrl+C) and start it with this line.</b>' : ''}</p>`}`;
  }

  function hangUp() {
    clearTimeout(again);
    const old = ws;
    ws = null; greeted = false; over = false;
    if (old) { old.onclose = null; old.close(); }
  }

  let tryPort = 0;      // which of the ports is asked next, while none has answered
  function dial() {
    hangUp();
    tabs();
    const ports = [...new Set([pair.port, ...PORTS])], port = ports[tryPort % ports.length];
    const s = new WebSocket(`ws://127.0.0.1:${port}`);
    s.binaryType = 'arraybuffer';
    ws = s;
    s.onopen = () => s.send(JSON.stringify({ token: pair.token, run, cols: term.cols, rows: term.rows }));
    s.onmessage = (e) => {
      if (typeof e.data !== 'string') return term.write(new Uint8Array(e.data));
      let m;
      try { m = JSON.parse(e.data); } catch { return; }
      if (m.t === 'hello') {
        about = m;
        if (m.run === null) { tabs(); return help('none'); }
        greeted = true;
        if (pair.port !== port) { pair.port = port; try { localStorage.setItem(KEEP, JSON.stringify(pair)); } catch { /* not kept */ } }
        tryPort = 0;
        help(null);
        term.reset();
        try { fit.fit(); } catch { /* hidden */ }
        s.send(JSON.stringify({ t: 'resize', cols: term.cols, rows: term.rows }));
        if (m.run !== 'log') about.running = [...new Set([...(about.running ?? []), m.run])];
        tabs();
        term.focus();
        letIn();
      } else if (m.t === 'exit') {
        term.write(`\r\n\x1b[2m${NAMES[run]} ended${m.code ? ` (${m.code})` : ''}. Press Enter to start it again.\x1b[0m\r\n`);
        about.running = (about.running ?? []).filter((n) => n !== run);
        greeted = false; over = true;      // it ended, and said so: the line closing after it is no news
        tabs();
        const once = term.onKey(({ domEvent }) => { if (domEvent.key === 'Enter') { once.dispose(); dial(); } });
      }
    };
    s.onclose = (e) => {
      if (ws !== s) return;
      ws = null;
      if (over) return;
      if (!greeted && about?.run !== null) { help(e.code === 4003 ? 'token' : 'away'); tryPort++; if (!root.hidden) again = setTimeout(dial, tryPort % 4 ? 300 : 2500); }      // not there yet: look again
      else if (e.code !== 1000) { term.write('\r\n\x1b[2mMonet local went away: looking for it…\x1b[0m\r\n'); again = setTimeout(dial, 2500); }
      greeted = false;
      tabs();
    };
  }

  /** The agent in the terminal comes in by the agent's door, which opens only while remote control is on: opening
   *  a terminal is the person letting it in, as the switch under Connect your agent is. */
  async function letIn() {
    const r = hooks.remote;
    if (!hooks.mine() || r.view()?.on) return;
    try { await r.set(true); poke(); } catch { /* said under Connect your agent */ }
  }

  function poke() { if (ws?.readyState === WebSocket.OPEN && greeted) ws.send(JSON.stringify({ t: 'poke' })); }

  function size(next) {
    h = Math.round(Math.max(120, Math.min(view.clientHeight - 80, next)));
    root.style.height = `${h}px`;
    view.style.setProperty('--term-h', root.hidden ? '0px' : `${h}px`);
  }

  async function show(on) {
    root.hidden = !on;
    button.classList.toggle('on', on);
    view.classList.toggle('termed', on);
    size(h);
    if (!on) return;      // closed: the line stays, so what runs is still heard; opening again shows it at once
    await xterm();
    try { fit.fit(); } catch { /* not laid out yet */ }
    if (!ws || !greeted) dial(); else term.focus();
  }

  root.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.run) { run = b.dataset.run; try { localStorage.setItem('monet.term.run', run); } catch { /* not kept */ } about = about && { ...about, run: undefined }; dial(); }
    else if (b.dataset.term === 'close') show(false);
    else if (b.dataset.term === 'end' && ws && greeted) ws.send(JSON.stringify({ t: 'end' }));
    else if (b.dataset.term === 'copy') navigator.clipboard?.writeText(line()).then(() => { b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy'; }, 1500); });
  });
  $('.term-grip').addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const y0 = e.clientY, h0 = h, g = e.currentTarget;
    g.setPointerCapture(e.pointerId);
    document.body.classList.add('row-resizing');
    g.onpointermove = (m) => size(h0 + y0 - m.clientY);
    g.onpointerup = g.onpointercancel = () => {
      g.onpointermove = g.onpointerup = g.onpointercancel = null;
      document.body.classList.remove('row-resizing');
      try { localStorage.setItem('monet.term.h', String(h)); } catch { /* not kept */ }
    };
  });
  button.onclick = () => show(root.hidden);
  if (came) show(true);      // the link was just opened: here is what it is for

  return { show, poke, open: () => !root.hidden, state: () => ({ open: !root.hidden, paired: !!pair, connected: greeted, run, about }) };
}

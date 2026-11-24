// Beside a shared study (/s/<token>): notes on it, for GitHub. Anyone with the link watches; whoever signs in with GitHub writes a title
// and a note, may mark the picture (a pen, boxes, rings, arrows, in a few colours), and Open on GitHub opens a new issue
// of the project's repository with the note filled in, the picture of that moment (the view under the marks) copied to
// paste there, and a link back to the moment (frame and camera). GitHub keeps the note and the picture; nothing of it
// is sent to Monet, which keeps nothing a viewer says. Marks alone, transparent, or the picture can also be saved.
import { esc } from './markdown.js';

const COLOURS = [['#ff3b30', 'red'], ['#5ef6ff', 'cyan'], ['#ffd23f', 'yellow'], ['#4cd964', 'green'], ['#ffffff', 'white']];
const TOOLS = [['pen', '✎', 'draw freely'], ['rect', '▭', 'a box'], ['ring', '◯', 'a ring'], ['arrow', '➚', 'an arrow']];
const WIDE = 1600;      // the picture's long side, in pixels
const MAX_URL = 7800;   // what GitHub's new-issue address takes, with room to spare

/** The new-issue address: the note, the moment and where to paste the picture, shortened to fit. */
export function issueUrl(repo, { title, text, study, project, note, frame, fps, length, link }) {
  const secs = fps ? ` (${(frame / fps).toFixed(1)} s)` : '';
  const tail = `\n\n_(paste the picture here: Ctrl-V, or ⌘-V on a Mac)_\n\n---\n**Study:** ${study} · ${project}/${note} · frame ${frame} of ${length}${secs}\n[Open this moment in Monet](${link})\n`;
  let body = `${text.trim()}${tail}`;
  const make = () => `https://github.com/${repo}/issues/new?${new URLSearchParams({ title: title.trim() || `${study}: a note`, body })}`;
  let url = make();
  for (let keep = text.length; url.length > MAX_URL && keep > 0; keep -= 200) { body = `${text.trim().slice(0, keep)}…${tail}`; url = make(); }
  return url;
}

/** hooks: { share(): {project, study, note, repository, viewer, link}, frame(), fps(), length(), camera(), goTo(frame, camera),
 *  picture(width) → canvas, pause(), notice(text), tell(text) } */
export function createShare(panel, view, hooks) {
  let built = false, marking = false, tool = 'rect', colour = COLOURS[0][0], width = 4, strokes = [], at = null, drawing = null;
  const overlay = view.appendChild(Object.assign(document.createElement('canvas'), { className: 'sh-overlay' }));
  const bar = view.appendChild(Object.assign(document.createElement('div'), { className: 'sh-tools', hidden: true }));
  bar.innerHTML = `${TOOLS.map(([k, ico, t]) => `<button data-tool="${k}" title="${t}">${ico}</button>`).join('')}<span class="sh-sep"></span>
    ${COLOURS.map(([c, n]) => `<button class="sh-c" data-colour="${c}" title="${n}" style="--c:${c}"></button>`).join('')}<span class="sh-sep"></span>
    ${[2, 4, 8].map((w) => `<button data-width="${w}" title="${w} px">${'━'.slice(0, 1)}<small>${w}</small></button>`).join('')}<span class="sh-sep"></span>
    <button data-do="undo" title="the last mark away">↶</button><button data-do="clear" title="every mark away">✕</button><button class="primary" data-do="done">Done</button>`;
  const draft = { get() { try { return JSON.parse(localStorage.getItem('monet.share.draft') ?? '{}'); } catch { return {}; } },
    set(v) { try { localStorage.setItem('monet.share.draft', JSON.stringify(v)); } catch { /* this visit only */ } } };

  function size() {
    const k = devicePixelRatio || 1, w = view.clientWidth, h = view.clientHeight;
    if (overlay.width !== Math.round(w * k) || overlay.height !== Math.round(h * k)) { overlay.width = Math.round(w * k); overlay.height = Math.round(h * k); }
    paint();
  }
  /** Marks on a canvas of any size: they are kept as fractions of the view, so they land where they were drawn. */
  function drawMarks(g, w, h) {
    g.lineCap = 'round'; g.lineJoin = 'round';
    for (const s of [...strokes, ...(drawing ? [drawing] : [])]) {
      const k = Math.max(w, h) / 1000, pts = s.points.map(([x, y]) => [x * w, y * h]);
      g.strokeStyle = s.colour; g.lineWidth = s.width * k * 1.6;
      g.shadowColor = 'rgba(0,0,0,.55)'; g.shadowBlur = 2 * k;
      g.beginPath();
      const [a, b] = [pts[0], pts[pts.length - 1]];
      if (s.tool === 'pen') pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
      else if (s.tool === 'rect') g.rect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      else if (s.tool === 'ring') g.ellipse((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.abs(b[0] - a[0]) / 2 || 1, Math.abs(b[1] - a[1]) / 2 || 1, 0, 0, Math.PI * 2);
      else if (s.tool === 'arrow') {
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), head = Math.max(10 * k, s.width * k * 5);
        g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]);
        g.moveTo(b[0] - head * Math.cos(ang - 0.45), b[1] - head * Math.sin(ang - 0.45)); g.lineTo(b[0], b[1]);
        g.lineTo(b[0] - head * Math.cos(ang + 0.45), b[1] - head * Math.sin(ang + 0.45));
      }
      g.stroke();
    }
    g.shadowBlur = 0;
  }
  function paint() {
    const g = overlay.getContext('2d');
    g.clearRect(0, 0, overlay.width, overlay.height);
    drawMarks(g, overlay.width, overlay.height);
    overlay.classList.toggle('on', marking);
    bar.hidden = !marking;
    bar.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === tool));
    bar.querySelectorAll('[data-colour]').forEach((b) => b.classList.toggle('on', b.dataset.colour === colour));
    bar.querySelectorAll('[data-width]').forEach((b) => b.classList.toggle('on', Number(b.dataset.width) === width));
    const n = panel.querySelector('#shMarks');
    if (n) n.textContent = strokes.length ? `${strokes.length} mark${strokes.length > 1 ? 's' : ''} on the picture, at frame ${at?.frame ?? 0}` : 'no marks';
  }
  new ResizeObserver(size).observe(view);

  const where = (e) => { const r = overlay.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  overlay.addEventListener('pointerdown', (e) => {
    if (!marking || e.button !== 0) return;
    e.preventDefault();
    overlay.setPointerCapture(e.pointerId);
    if (!strokes.length) at = { frame: Math.round(hooks.frame()), camera: hooks.camera() };      // the moment the marks are on
    drawing = { tool, colour, width, points: [where(e)] };
    paint();
  });
  overlay.addEventListener('pointermove', (e) => {
    if (!drawing) return;
    if (drawing.tool === 'pen') drawing.points.push(where(e)); else drawing.points = [drawing.points[0], where(e)];
    paint();
  });
  overlay.addEventListener('pointerup', () => { if (drawing) { if (drawing.points.length > 1) strokes.push(drawing); drawing = null; paint(); } });
  bar.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.tool) tool = b.dataset.tool;
    if (b.dataset.colour) colour = b.dataset.colour;
    if (b.dataset.width) width = Number(b.dataset.width);
    if (b.dataset.do === 'undo') strokes.pop();
    if (b.dataset.do === 'clear') strokes = [];
    if (b.dataset.do === 'done') marking = false;
    if (!strokes.length) at = null;
    paint(); render();
  });

  /** The picture: the view at the marked moment (or as it is), the marks on it. `alone`: the marks only, transparent. */
  async function picture(alone = false) {
    if (at) hooks.goTo(at.frame, at.camera);
    const view = alone ? null : await hooks.picture(WIDE);
    const w = view?.width ?? Math.round(WIDE), h = view?.height ?? Math.round(WIDE * overlay.height / Math.max(1, overlay.width));
    const k = Math.min(1, WIDE / Math.max(w, h));
    const pad = Object.assign(document.createElement('canvas'), { width: Math.round(w * k), height: Math.round(h * k) });
    const g = pad.getContext('2d');
    if (view) g.drawImage(view, 0, 0, pad.width, pad.height);
    drawMarks(g, pad.width, pad.height);
    return new Promise((r) => pad.toBlob(r, 'image/png'));
  }
  const save = async (alone) => {
    const blob = await picture(alone);
    if (!blob) { hooks.tell('the picture could not be made in this browser'); return; }
    const s = hooks.share();
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `${s.study}-${alone ? 'marks' : 'picture'}.png`.replace(/\s+/g, '-') });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  };

  function send() {
    const s = hooks.share(), title = panel.querySelector('#shTitle').value, text = panel.querySelector('#shText').value;
    if (!s.repository) return;
    if (!text.trim() && !strokes.length) { hooks.tell('Write what you mean first, or mark the picture.'); return; }
    const moment = at ?? { frame: Math.round(hooks.frame()), camera: hooks.camera() };
    const link = `${s.link}#f=${moment.frame}&c=${encodeURIComponent(JSON.stringify(moment.camera))}`;
    const url = issueUrl(s.repository, { title, text, study: s.study, project: s.project, note: s.note, frame: moment.frame, fps: hooks.fps(), length: hooks.length(), link });
    // both while the click still counts as the person's: the picture is made as the clipboard asks for it
    let copied = true;
    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') throw new Error('no clipboard');
      navigator.clipboard.write([new ClipboardItem({ 'image/png': picture(false) })]).catch(() => { copied = false; hooks.tell('The picture was not copied (this browser would not): save it with Download picture and drop it into the issue.'); });
    } catch { copied = false; }
    const tab = window.open(url, '_blank', 'noopener');
    hooks.notice(copied ? 'GitHub opens in a new tab: paste the picture into the issue (Ctrl-V, ⌘-V), then Submit there'
      : 'GitHub opens in a new tab: Download picture here and drop it into the issue');
    if (!tab) hooks.tell(`Your browser kept the new tab from opening. Open it from here: ${url.slice(0, 120)}…`);
  }

  function render() {
    const s = hooks.share();
    if (!s) return;
    if (!built) {
      built = true;
      const back = encodeURIComponent(location.pathname);
      if (!s.viewer) {      // watching needs no sign-in: a note does, since it is written on GitHub
        panel.innerHTML = `<div class="card share-card"><h2>A note on ${esc(s.study)}</h2>
          <p class="muted">Anyone with the link may watch this study. To leave a note on it (an issue on GitHub, with a marked picture of the moment), sign in with GitHub.</p>
          ${s.signin ? `<div class="row sh-row"><button class="primary" id="shSignin" title="GitHub tells Monet only who you are; you come back here">Sign in with GitHub</button></div>`
            : '<p class="muted">Signing in with GitHub is not set up on this server, so no note can be left here.</p>'}
          <div class="row sh-row"><button id="shPic" title="the view as it is, as a PNG">Download picture</button></div></div>`;
        panel.querySelector('#shPic').onclick = () => save(false);
        const go = panel.querySelector('#shSignin');
        if (go) go.onclick = () => { location.href = s.signin; };
        return;
      }
      const d = draft.get();
      panel.innerHTML = `<div class="card share-card"><h2>A note on ${esc(s.study)}</h2>
        <p class="muted">Signed in with GitHub as <b>${esc(s.viewer)}</b> · <a href="/auth/github/out?next=${back}">sign out</a></p>
        <p class="muted">${s.repository ? `Your note becomes an issue of <a href="https://github.com/${esc(s.repository)}" target="_blank" rel="noopener noreferrer">${esc(s.repository)}</a>, written by you on GitHub. Nothing you write here is kept by Monet.`
          : 'The owner has not named a GitHub repository for this project yet: save the picture and send it to them another way.'}</p>
        <label class="sh-l">Title<input id="shTitle" maxlength="140" placeholder="the bolt heads should be hex" spellcheck="true"></label>
        <label class="sh-l">Note<textarea id="shText" rows="7" placeholder="what to change, and why. Red box: change shape. Cyan: every bolt that should be hex." spellcheck="true"></textarea></label>
        <div class="row sh-row"><button id="shMark" title="draw on the picture: boxes, rings, arrows, a pen, in colours">✎ Mark the picture</button><span class="muted" id="shMarks"></span></div>
        <div class="row sh-row"><button class="primary" id="shSend" ${s.repository ? '' : 'disabled'} title="a new issue on GitHub with this filled in; the picture is copied for you to paste">Open on GitHub</button></div>
        <div class="row sh-row"><button id="shPic" title="the view with the marks, as a PNG">Download picture</button><button id="shAlone" title="the marks alone, on a transparent PNG the size of the view">Download marks</button></div>
        <p class="muted sh-how">Pause where you mean, turn the view to show it, then mark it. The issue gets a link back to that moment. If the repository is private and you are not in it, GitHub shows you its own “not found”.</p></div>`;
      const t = panel.querySelector('#shTitle'), x = panel.querySelector('#shText');
      t.value = d.title ?? ''; x.value = d.text ?? '';
      const keep = () => draft.set({ title: t.value, text: x.value });
      t.oninput = keep; x.oninput = keep;
      panel.querySelector('#shMark').onclick = () => { hooks.pause(); marking = !marking; paint(); };
      panel.querySelector('#shSend').onclick = send;
      panel.querySelector('#shPic').onclick = () => save(false);
      panel.querySelector('#shAlone').onclick = () => (strokes.length ? save(true) : hooks.notice('no marks yet: Mark the picture first'));
    }
    panel.querySelector('#shMark')?.classList.toggle('on', marking);
    paint();
  }
  size();
  return { render, issueUrl, picture };
}

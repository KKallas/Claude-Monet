// The Docs room: the project's words and scripts beside its shape. PROJECT.md (the brief: what the project is, where
// its repository and issues are, what is done, what comes next), the other Markdown beside the Notes (its docs, its
// own skills for an agent), the Notes' Python, and, read-only, Monet's own skill, scripts and docs. One pane: Markdown
// drawn as it is written (editor.js, CodeMirror); Read shows a doc whole (markdown.js). Nothing is built from a doc; a
// Note saved here is written and waits for a build, which Monet local makes on the person's computer.
//
// What is typed and not saved is kept in this browser (localStorage) with the version it was typed over, so leaving the
// room or the page loses nothing; Save sends that version along, and a file changed meanwhile (by the agent, in another
// window) is not written over unasked.
import { esc, markdown } from './markdown.js';

const SEG = '[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}';
const DOC_RE = new RegExp(`^(?:(?:\\.claude|${SEG})/)?(?:${SEG}/){0,2}${SEG}\\.md$`);
const NOT_DOCS = new Set(['versions', 'out', 'attachments', 'node_modules', '.git']);
/** A doc's path as the server takes it (monet/workspace.py is_doc). */
export const isDoc = (p) => DOC_RE.test(p) && !NOT_DOCS.has(p.split('/')[0]) && !p.split('/').includes('..');
const EMPTY = 'e3b0c44298fc1c14';      // the sha of nothing: a doc that is not there yet
const BRIEF = 'PROJECT.md';

const ago = (iso) => {
  if (!iso) return '';
  const t = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  return t < 90 ? 'just now' : t < 5400 ? `${Math.round(t / 60)} min ago` : t < 129_600 ? `${Math.round(t / 3600)} h ago` : new Date(iso).toLocaleDateString();
};
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) ?? 'null'); } catch { return null; } },
  set(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
};
const pathUrl = (p) => p.split('/').map(encodeURIComponent).join('/');

/** A plain textarea with the editor's face, for when the editor cannot be fetched (offline, the CDN away). */
function plainEditor(parent, hooks) {
  const ta = parent.appendChild(Object.assign(document.createElement('textarea'), { className: 'docs-plain', spellcheck: false }));
  ta.oninput = () => hooks.changed?.(ta.value);
  ta.onkeydown = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); hooks.save?.(); } };
  return { get text() { return ta.value; }, set(text, _k, readonly) { ta.value = text; ta.readOnly = !!readonly; ta.scrollTop = 0; }, focus() { ta.focus(); } };
}

/** hooks: { project(), call(path, method, body) → {status, data}, ask(text, {yes, no, danger}), tell(text),
 *  notice(text), help(): the address of docs/REPOSITORY.md or '' } */
export function createDocs(room, list, hooks) {
  room.innerHTML = `<div class="docs-bar">
      <span class="docs-path" id="docsPath"></span><span class="docs-dirty" id="docsDirty" title="changed and not saved: kept in this browser until it is" hidden>●</span>
      <input id="docsNewPath" placeholder="docs/notes.md   (Enter to start it, Esc to leave it)" spellcheck="false" hidden>
      <span class="docs-what muted" id="docsWhat"></span><span class="sp"></span>
      <button id="docsRead" title="the doc drawn whole, as it reads (links to other docs open them)">Read</button>
      <button id="docsNew" title="a new Markdown file of the project: a doc, or a skill for an agent (.claude/skills/<name>/SKILL.md)">New</button>
      <button id="docsDelete" title="take this doc out of the project (Monet local takes it out of the folder too)">Delete</button>
      <button class="primary" id="docsSave" title="save (Ctrl/⌘-S)">Save</button>
    </div>
    <div class="docs-body"><div class="docs-edit" id="docsEdit"></div><div class="docs-read brief-doc" id="docsReadView" hidden></div></div>`;
  const $ = (s) => room.querySelector(s);
  let editor = null, loading = null, project = null, docs = [], notes = [], manual = null, cur = null, dirty = false, reading = false, elsewhere = false, timer = 0;
  const draftKey = (c = cur) => `monet.draft.${project}.${c.kind}.${c.path}`;
  const kindOf = (path) => (path.endsWith('.py') ? 'py' : 'md');

  async function ready() {
    if (editor) return editor;
    loading ??= import('./editor.js').then((m) => m.makeEditor($('#docsEdit'), { changed, save }))
      .catch(() => { hooks.notice('the editor could not be fetched: a plain one meanwhile'); return plainEditor($('#docsEdit'), { changed, save }); });
    editor = await loading;
    return editor;
  }

  function changed(text) {
    if (!cur || cur.readonly) return;
    dirty = text !== cur.text;
    clearTimeout(timer);
    timer = setTimeout(() => store.set(draftKey(), dirty ? { text, base: cur.sha } : null), 300);
    bar();
    drawList();
  }

  function bar() {
    $('#docsPath').textContent = cur ? (cur.kind === 'note' ? `${cur.path}.py` : cur.path) : '';
    $('#docsDirty').hidden = !dirty;
    const what = !cur ? '' : cur.kind === 'manual' ? '🔒 Monet\'s own: the same for every user and agent, read only'
      : cur.kind === 'note' ? 'a Note: saving runs nothing here, Monet local builds it on your computer'
      : cur.missing ? 'not written yet: a start to fill in' : elsewhere ? 'changed elsewhere meanwhile: Save asks which to keep'
      : cur.updated ? `written ${ago(cur.updated)}` : '';
    $('#docsWhat').textContent = what;
    $('#docsSave').disabled = !cur || cur.readonly || !dirty;
    $('#docsDelete').hidden = !cur || cur.kind !== 'doc' || cur.missing;
    $('#docsRead').hidden = !cur || kindOf(cur.kind === 'note' ? '.py' : cur.path) !== 'md';
    $('#docsRead').classList.toggle('on', reading);
  }

  function row(kind, path, label, extra = '') {
    const on = cur && cur.kind === kind && cur.path === path;
    const unsaved = (on && dirty) || (!on && store.get(`monet.draft.${project}.${kind}.${path}`));
    return `<button class="docs-file${on ? ' on' : ''}" data-kind="${kind}" data-path="${esc(path)}" title="${esc(path)}">${esc(label)}${unsaved ? ' <span class="docs-dirty">●</span>' : ''}${extra}</button>`;
  }
  function drawList() {
    if (!project) { list.innerHTML = '<p class="muted">no project open</p>'; return; }
    const paths = docs.map((d) => d.path);
    const brief = paths.includes(BRIEF) ? '' : ' <span class="muted">(not yet)</span>';
    const monet = manual ?? [];
    list.innerHTML = `<div class="docs-group">Project</div>${row('doc', BRIEF, 'PROJECT.md · the brief', brief)}
      ${paths.filter((p) => p !== BRIEF).map((p) => row('doc', p, p)).join('')}
      ${notes.length ? `<div class="docs-group">Notes</div>${notes.map((n) => row('note', n, `${n}.py`)).join('')}` : ''}
      <details class="docs-monet"${cur?.kind === 'manual' ? ' open' : ''}><summary class="docs-group">🔒 Monet</summary>${monet.map((f) => row('manual', f.path, f.path.replace(/^skill\/monet\//, 'skill/'))).join('')}</details>
      ${hooks.help?.() ? `<a class="docs-help" href="${esc(hooks.help())}" target="_blank" rel="noopener noreferrer">How a project gets a git repository</a>` : ''}`;
    list.querySelectorAll('.docs-file').forEach((b) => { b.onclick = () => openFile(b.dataset.kind, b.dataset.path); });
  }

  async function refresh() {
    project = hooks.project();
    if (!project) { docs = []; notes = []; drawList(); return; }
    const [got, man] = await Promise.all([hooks.call(`/p/${project}/docs`), manual ? null : hooks.call('/manual')]);
    if (got.status === 200) { docs = got.data.docs; notes = got.data.notes; }
    if (man?.status === 200) manual = man.data.files;
    drawList();
  }

  /** What a file is on the server: {text, sha, updated?, readonly?, missing?}. */
  async function fetchFile(kind, path) {
    if (kind === 'manual') { const r = await hooks.call(`/manual/${pathUrl(path)}`); if (r.status !== 200) throw new Error(r.data.error); return { text: r.data.text, sha: '', readonly: true }; }
    if (kind === 'note') { const r = await hooks.call(`/p/${project}/n/${path}`); if (r.status !== 200) throw new Error(r.data.error); return { text: r.data.source, sha: r.data.sha }; }
    const r = await hooks.call(`/p/${project}/doc/${pathUrl(path)}`);
    if (r.status === 200) return { text: r.data.text, sha: r.data.sha, updated: r.data.updated };
    if (r.status !== 404) throw new Error(r.data.error);
    let start = `# ${path.split('/').pop().replace(/\.md$/, '')}\n\n`;
    if (path === BRIEF) { const b = await hooks.call(`/p/${project}/brief`); start = b.data?.template ?? start; }
    return { text: '', sha: EMPTY, missing: true, start };
  }

  async function openFile(kind, path) {
    await ready();
    if (hooks.project() !== project) await refresh();
    let got;
    try { got = await fetchFile(kind, path); } catch (e) { hooks.tell(e.message); return false; }
    cur = { kind, path, ...got };
    elsewhere = false;
    const draft = cur.readonly ? null : store.get(draftKey());
    const text = draft && draft.text !== cur.text ? draft.text : cur.missing ? cur.start : cur.text;
    if (draft && draft.base !== cur.sha) { elsewhere = true; cur.sha = draft.base; }      // Save sends what it was typed over, and asks
    dirty = text !== cur.text;
    editor.set(text, kind === 'note' || path.endsWith('.py') ? 'py' : 'md', !!cur.readonly);
    reading = reading && kind !== 'note' && path.endsWith('.md');
    showRead();
    bar(); drawList();
    if (draft && draft.text !== got.text) hooks.notice('what you typed and did not save is back');
    return true;
  }

  function showRead() {
    $('#docsReadView').hidden = !reading;
    $('#docsEdit').hidden = reading;
    if (reading) {
      $('#docsReadView').innerHTML = markdown(editor.text, cur?.kind === 'doc' ? cur.path : '') || '<p class="muted">nothing written yet</p>';
      $('#docsReadView').querySelectorAll('a[data-doc]').forEach((a) => {
        a.onclick = (e) => { e.preventDefault(); const p = a.dataset.doc; openFile(cur.kind === 'manual' && manual?.some((f) => f.path === p) ? 'manual' : 'doc', p); };
      });
    }
    bar();
  }

  async function save() {
    if (!cur || cur.readonly || !dirty) return;
    const text = editor.text, at = { ...cur };
    const put = (was) => (at.kind === 'note' ? hooks.call(`/p/${project}/n/${at.path}/source`, 'PUT', { source: text, was })
      : hooks.call(`/p/${project}/doc/${pathUrl(at.path)}`, 'PUT', { text, was }));
    let r = await put(at.sha);
    if (r.status === 409 && r.data.current) {
      const keep = await hooks.ask(`${$('#docsPath').textContent} was changed meanwhile (by your agent, or in another window). Keep yours and write over that, or take that one and drop yours?`,
        { yes: 'Keep mine', no: 'Take that one', danger: true });
      if (!keep) {
        store.set(draftKey(at), null);
        cur = { ...at, text: r.data.current.text, sha: r.data.current.sha, missing: false };
        dirty = false; elsewhere = false;
        editor.set(cur.text, at.kind === 'note' ? 'py' : 'md', false);
        bar(); drawList(); showRead();
        return;
      }
      r = await put(r.data.current.sha);
    }
    if (r.status !== 200) { hooks.tell(r.data.error ?? `not saved (${r.status})`); return; }
    store.set(draftKey(at), null);
    if (cur?.kind === at.kind && cur.path === at.path) {
      cur = { ...cur, text, sha: r.data.sha ?? cur.sha, missing: false, updated: new Date().toISOString() };
      dirty = editor.text !== text; elsewhere = false;
    }
    hooks.notice(at.kind === 'note' ? `${at.path}.py saved: it waits for a build (Monet local makes it)` : `${at.path} saved`);
    await refresh();
    bar();
  }

  async function remove() {
    if (!cur || cur.kind !== 'doc' || cur.missing) return;
    if (!(await hooks.ask(`Take ${cur.path} out of the project? Monet local takes it out of the folder too (git still has it, if it was committed).`, { yes: 'Delete', danger: true }))) return;
    const r = await hooks.call(`/p/${project}/doc/${pathUrl(cur.path)}`, 'PUT', { text: '', was: cur.sha });
    if (r.status !== 200) { hooks.tell(r.data.error ?? `not deleted (${r.status})`); return; }
    store.set(draftKey(), null);
    hooks.notice(`${cur.path} deleted`);
    cur = null; dirty = false;
    await refresh();
    await openFile('doc', BRIEF);
  }

  function startNew() {
    const input = $('#docsNewPath');
    input.hidden = false; $('#docsPath').hidden = true;
    input.value = cur?.kind === 'doc' && cur.path.includes('/') ? cur.path.replace(/[^/]+$/, '') : 'docs/';
    input.focus();
    const done = () => { input.hidden = true; $('#docsPath').hidden = false; };
    input.onkeydown = async (e) => {
      if (e.key === 'Escape') return done();
      if (e.key !== 'Enter') return;
      let p = input.value.trim().replace(/^\/+/, '');
      if (p && !p.endsWith('.md')) p += '.md';
      if (!isDoc(p)) { hooks.notice('a .md file, at most four folders deep, of letters, digits, _ . - (e.g. docs/wiring.md or .claude/skills/print/SKILL.md)'); return; }
      done();
      await openFile('doc', p);
    };
    input.onblur = done;
  }

  /** The project changed on the server (the agent, Monet local, another window): the list again, and the open file if
   *  nothing of it is unsaved here. */
  async function poll() {
    if (room.classList.contains('away')) return;
    if (hooks.project() !== project) { cur = null; dirty = false; elsewhere = false; await refresh(); if (project) await openFile('doc', BRIEF); return; }
    if (!project) return;
    await refresh();
    if (!cur || cur.readonly) return;
    let got;
    try { got = await fetchFile(cur.kind, cur.path); } catch { return; }
    if (got.sha === cur.sha || (cur.missing && got.missing)) return;
    if (dirty) { elsewhere = true; bar(); return; }
    cur = { ...cur, ...got };
    editor.set(got.missing ? '' : got.text, cur.kind === 'note' ? 'py' : 'md', false);
    if (reading) showRead();
    bar();
    hooks.notice(`${$('#docsPath').textContent} changed (by your agent, or in another window): shown as it is now`);
  }

  $('#docsSave').onclick = save;
  $('#docsDelete').onclick = remove;
  $('#docsNew').onclick = startNew;
  $('#docsRead').onclick = () => { reading = !reading; showRead(); };

  return {
    /** The room is shown: the list, and the file open before (else the brief). */
    async show() {
      await ready();
      const was = project;
      await refresh();
      if (!cur || was !== project) { cur = null; dirty = false; await openFile('doc', BRIEF); } else bar();
      if (!reading) editor.focus();
    },
    openFile, poll,
    get dirty() { return dirty; },
    get editor() { return editor; },      // for scripts/shot.mjs
  };
}

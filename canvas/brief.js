// The brief of a project: PROJECT.md, the project in words for whoever picks it up next (a person, or an agent on
// another computer with an hour of somebody's tokens). What it is, where its repository and its issues are, what is
// done, the milestones, what to do next, and the log of who did what. The agent reads it first and writes it before
// it stops (the tools brief and write_brief); the person reads and writes it here. It is no Note and no check:
// nothing is built from it, nothing is tested by it. It travels with the folder (Monet local), the archive and
// every saved version.

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Within a line: `code`, **bold**, [words](https://…) and bare addresses. The text is escaped first, and no tag comes
 *  from it: only these patterns make one. */
function inline(text) {
  const codes = [];
  let s = esc(text).replace(/`([^`]+)`/g, (_m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[i]}</code>`);
}

/** As much of Markdown as a brief needs: headings, lists (with boxes to tick), fenced code, paragraphs. */
export function markdown(text) {
  const out = [];
  let list = '', para = [], code = null;
  const endPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  const endList = () => { if (list) { out.push(`</${list}>`); list = ''; } };
  for (const line of String(text ?? '').split('\n')) {
    if (code) {
      if (/^```/.test(line)) { out.push(`<pre>${esc(code.join('\n'))}</pre>`); code = null; } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) { endPara(); endList(); code = []; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line), li = /^\s*(?:([-*])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (h) { endPara(); endList(); out.push(`<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`); continue; }
    if (li) {
      endPara();
      const kind = li[1] ? 'ul' : 'ol';
      if (list !== kind) { endList(); out.push(`<${kind}>`); list = kind; }
      const box = /^\[( |x|X)\]\s+(.*)$/.exec(li[3]);
      out.push(box ? `<li class="${box[1] === ' ' ? 'todo' : 'done'}">${inline(box[2])}</li>` : `<li>${inline(li[3])}</li>`);
      continue;
    }
    if (!line.trim()) { endPara(); endList(); continue; }
    if (list && /^\s+\S/.test(line)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, ` ${inline(line.trim())}</li>`); continue; }
    endList();
    para.push(line);
  }
  if (code) out.push(`<pre>${esc(code.join('\n'))}</pre>`);
  endPara(); endList();
  return out.join('\n');
}

/** hooks: { project(): the one the canvas shows, api(path, method, body), ask(text, {yes, danger}), tell(text),
 *  help(): the address of the page on repositories (docs/REPOSITORY.md), or '' } */
export function createBrief(button, hooks) {
  const dlg = document.body.appendChild(Object.assign(document.createElement('dialog'), { id: 'briefDialog', className: 'brief' }));
  let got = null, editing = false;

  const ago = (iso) => {
    if (!iso) return '';
    const t = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    return t < 90 ? 'just now' : t < 5400 ? `${Math.round(t / 60)} min ago` : t < 129_600 ? `${Math.round(t / 3600)} h ago` : new Date(iso).toLocaleDateString();
  };

  function draw() {
    const head = `<h2>${esc(got.project)} · the brief</h2>
      <p class="muted">PROJECT.md: what this is, where its repository and its issues are, what is done, what comes next. Your agent reads it
        first and brings it up to date before it stops, so anybody (you next week, a friend with tokens to spare, another agent on
        another computer) can go on from here. It travels with the project's folder, its archive and every saved version.
        ${hooks.help?.() ? `<a href="${esc(hooks.help())}" target="_blank" rel="noopener noreferrer">How a project gets a git repository, and what to say to your agent</a>` : ''}</p>`;
    if (editing) {
      dlg.innerHTML = `${head}<textarea id="briefText" spellcheck="false"></textarea>
        <div class="line"><span class="muted" style="flex:1">Markdown. No keys or passwords in it: it is shared with the project.</span>
          <button id="briefCancel">Cancel</button><button class="primary" id="briefSave">Save</button></div>`;
      dlg.querySelector('#briefText').value = got.text || got.template || '';
      dlg.querySelector('#briefCancel').onclick = () => { editing = false; draw(); };
      dlg.querySelector('#briefSave').onclick = save;
      dlg.querySelector('#briefText').focus();
      return;
    }
    dlg.innerHTML = `${head}${got.text ? `<div class="brief-doc">${markdown(got.text)}</div>`
      : '<p class="brief-none">No brief yet. Write the first one, or tell your agent to: it has a start to fill in.</p>'}
      <form method="dialog"><div class="line"><span class="muted" style="flex:1">${got.updated ? `written ${esc(ago(got.updated))} · ${(got.bytes / 1000).toFixed(1)} kB` : ''}</span>
        <button type="button" id="briefEdit">${got.text ? 'Edit' : 'Start one'}</button><button>Close</button></div></form>`;
    dlg.querySelector('#briefEdit').onclick = () => { editing = true; draw(); };
  }

  async function save() {
    const text = dlg.querySelector('#briefText').value;
    try {
      // somebody else may have written it meanwhile (the agent, at the end of its sitting): theirs is not lost unasked
      const now = await hooks.api(`/p/${got.project}/brief`);
      if (now.text !== got.text && !(await hooks.ask('The brief was changed while you wrote (by your agent, or in another window). Keep yours and lose that change?', { yes: 'Keep mine', danger: true }))) return;
      got = await hooks.api(`/p/${got.project}/brief`, 'PUT', { text });
      editing = false;
      mark({ bytes: got.bytes });
      draw();
    } catch (e) { hooks.tell(e.message); }
  }

  /** The button says whether there is one: `row` is the project's `brief` ({bytes, updated} or null). */
  function mark(row) {
    button.hidden = !hooks.project();
    button.classList.toggle('none', !row?.bytes);
    button.title = row?.bytes ? 'the project in words: what it is, where it lives, what is done, what comes next (PROJECT.md)'
      : 'this project has no brief yet: what it is, where it lives, what is done, what comes next (PROJECT.md)';
  }

  async function show() {
    if (!hooks.project()) return;
    try { got = await hooks.api(`/p/${hooks.project()}/brief`); } catch (e) { hooks.tell(e.message); return; }
    editing = false;
    draw();
    if (!dlg.open) dlg.showModal();
  }

  button.onclick = show;
  return { show, mark, open: () => dlg.open };
}

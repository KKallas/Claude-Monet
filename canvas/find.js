// Find: a few words in the box at the top of the panel beside the view, and every list keeps what they name: that
// panel's lists (objects, checks, tags, joints, poses, the BOM), and the Notes' tree on the left with the versions and
// sketches (a Note by its name, or by one of its checks: "pieces" finds the Note that holds that check, among hundreds).
// The person types it; their agent can fill it for them (goto with `find`), which is data, never code.
//
// Every word must be in the row, in any case. `is:<state>` picks by state instead of by words: `is:red` (a failing check,
// a Note that does not build), `is:ok`, `is:agent` (a check an agent added), `is:waiting` (a Note not built for its
// source). Nothing here draws but sift(), which only hides rows of what the canvas drew.

export function query(text) {
  const words = String(text ?? '').toLowerCase().split(/\s+/).filter(Boolean);
  const is = words.filter((w) => w.startsWith('is:') && w.length > 3).map((w) => w.slice(3));
  const plain = words.filter((w) => !w.startsWith('is:'));
  return {
    on: words.length > 0,
    text: String(text ?? '').trim(),
    test: (text, states = []) => is.every((s) => states.includes(s)) && plain.every((w) => String(text ?? '').toLowerCase().includes(w)),
  };
}

/** What a Note is, for `is:` (a row of the project's status). */
export function noteStates(row) {
  if (!row || row.kind === 'module') return ['module'];
  return [row.kind, row.state === 'error' ? 'red' : row.state === 'stale' || row.state === 'unbuilt' ? 'waiting' : 'built', row.changed ? 'changed' : 'saved'];
}

/** A kept check (as /checks gives it), as Find reads it. */
export const checkText = (c) => `${c.id} ${c.what} ${c.expect ?? ''} ${c.why ?? ''}`;

/** The Notes' tree (tree.js) cut down to the Notes that match and the branches that lead to them. `checks`: every
 *  Note's kept checks; a Note whose checks match is kept, with how many (`hits`). Branches are open where it is
 *  kept: what is found is shown, not folded away. */
export function prune(tree, q, checks = {}) {
  if (!q.on) return tree;
  const cut = (t) => {
    const children = t.children.map(cut).filter(Boolean);
    const named = q.test(`${t.name} ${t.row?.kind ?? ''}`, noteStates(t.row));
    const hits = (checks[t.name] ?? []).filter((c) => q.test(checkText(c), [c.by, 'check'])).length;
    return named || hits || children.length ? { ...t, children, hit: named || hits > 0, hits } : null;
  };
  const main = tree.main && cut(tree.main);
  return { ...tree, main, named: tree.named && !!main, others: tree.others.map(cut).filter(Boolean),
    shared: tree.shared.filter((n) => q.test(n, ['module'])) };
}

/** How many Notes the pruned tree found, each counted once however often it is used. */
export function found(tree) {
  const names = new Set();
  const walk = (t) => { if (t.hit) names.add(t.name); t.children.forEach(walk); };
  [tree.main, ...tree.others].filter(Boolean).forEach(walk);
  return names.size;
}

// cards that are no list: what they say is not narrowed
const WHOLE = new Set(['note', 'selection', 'compare', 'sketch', 'source', 'part', 'look', 'save', 'export', 'profile', 'load']);

/** The lists of the panel beside the view, narrowed to `q`: a card's rows (its .check and .fact children) that do not
 *  match are hidden, its head says how many are left, and a card with hits opens (a folded one too) while one with
 *  none shuts. A row may carry data-is="red agent …" for `is:`. */
export function sift(root, q) {
  for (const card of root.querySelectorAll('.card[data-card]')) {
    if (WHOLE.has(card.dataset.card)) continue;
    const body = card.querySelector(':scope > .body');
    const rows = body ? [...body.querySelectorAll(':scope > .check, :scope > .fact, :scope > .why')] : [];
    card.querySelector(':scope > .fold .hits')?.remove();
    card.classList.remove('found', 'missed');
    for (const r of rows) r.hidden = false;
    for (const h of body?.querySelectorAll(':scope > h3') ?? []) h.hidden = false;
    if (!q.on || !rows.length) continue;
    let n = 0;
    for (const r of rows) {
      const ok = q.test(r.textContent, (r.dataset.is ?? '').split(' '));
      r.hidden = !ok;
      if (ok) n++;
    }
    for (const h of body.querySelectorAll(':scope > h3')) {      // a heading (the BOM's Print, Cut, Buy) stays with its rows
      let s = h.nextElementSibling, any = false;
      while (s && s.tagName !== 'H3') { if (!s.hidden && rows.includes(s)) any = true; s = s.nextElementSibling; }
      h.hidden = !any;
    }
    card.classList.add(n ? 'found' : 'missed');
    card.querySelector(':scope > .fold .head')?.insertAdjacentHTML('beforeend', ` <span class="hits">${n} of ${rows.length}</span>`);
  }
}

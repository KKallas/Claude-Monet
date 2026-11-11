// The project as a tree: its main assembly with what it is made of, the other top designs below it, and the helper
// modules apart. From the status rows (each with `uses`: what it imports and what its PLACED puts in it) and the
// project's `main` (the Note called main, or the server's guess). Nothing here draws.

// A Note and what it uses, down to its parts. A Note used twice is in both places; a loop stops where it comes round.
function grow(name, rows, path = []) {
  const row = rows.get(name);
  const kids = path.includes(name) ? [] : (row?.uses ?? []).filter((u) => rows.get(u) && rows.get(u).kind !== 'module');
  const at = [...path, name];
  return { name, row, path: at.join('/'), children: kids.map((k) => grow(k, rows, at)) };
}

export function noteTree(list, main) {
  const rows = new Map((list ?? []).map((r) => [r.name, r]));
  const notes = [...rows.values()].filter((r) => r.kind !== 'module');
  const used = new Set(notes.flatMap((r) => r.uses ?? []));
  const top = notes.filter((r) => !used.has(r.name)).map((r) => r.name);
  const mainName = main?.note && rows.get(main.note)?.kind !== 'module' ? main.note : null;
  const trees = top.filter((n) => n !== mainName).sort((a, b) =>
    (rows.get(b).kind === 'assembly') - (rows.get(a).kind === 'assembly') || a.localeCompare(b)).map((n) => grow(n, rows));
  const head = mainName ? grow(mainName, rows) : null;
  // what no top reaches (a loop of Notes using each other): among the others, so nothing is lost from the list
  const seen = new Set();
  const walk = (t) => { seen.add(t.name); t.children.forEach(walk); };
  [head, ...trees].filter(Boolean).forEach(walk);
  for (const r of notes) if (!seen.has(r.name)) { const t = grow(r.name, rows); trees.push(t); walk(t); }
  return {
    main: head, named: !!main?.named && !!head, others: trees,
    shared: [...rows.values()].filter((r) => r.kind === 'module').map((r) => r.name).sort(),
  };
}

// The paths that must be open for `name` to show (its parents, wherever it is in the tree)
export function pathsTo(tree, name) {
  const out = new Set();
  const look = (t) => {
    let hit = t.name === name;
    for (const c of t.children) if (look(c)) { hit = true; out.add(t.path); }
    return hit;
  };
  [tree.main, ...tree.others].filter(Boolean).forEach(look);
  return out;
}

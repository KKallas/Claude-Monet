// The Notes' tree of the canvas (canvas/tree.js): the main with what it is made of, the other designs, the modules apart
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { noteTree, pathsTo } from '../canvas/tree.js';

const rows = [
  { name: 'cosmos', kind: 'module' },
  { name: 'orb', kind: 'assembly', uses: ['cosmos', 'skin', 'frame'] },
  { name: 'skin', kind: 'note', uses: ['cosmos'] },
  { name: 'frame', kind: 'note', uses: [] },
  { name: 'cube', kind: 'assembly', uses: ['frame', 'caps'] },
  { name: 'caps', kind: 'note', uses: [] },
  { name: 'loose', kind: 'note', uses: [] },
  { name: 'a', kind: 'note', uses: ['b'] },      // a loop: no top reaches it
  { name: 'b', kind: 'note', uses: ['a'] },
];

test('the main on top with its parts, modules left out of the branches', () => {
  const t = noteTree(rows, { note: 'orb', named: false });
  assert.equal(t.main.name, 'orb');
  assert.deepEqual(t.main.children.map((c) => c.name), ['skin', 'frame']);
  assert.equal(t.named, false);
  assert.deepEqual(t.shared, ['cosmos']);
});

test('the other designs: assemblies first, a Note used twice in both, a loop not lost', () => {
  const t = noteTree(rows, { note: 'orb', named: true });
  const names = t.others.map((x) => x.name);
  assert.equal(names[0], 'cube');
  assert.ok(names.includes('loose'));
  assert.ok(names.includes('a') || names.includes('b'));
  const cube = t.others[0];
  assert.deepEqual(cube.children.map((c) => c.name), ['frame', 'caps']);
  const loop = t.others.find((x) => x.name === 'a' || x.name === 'b');
  assert.equal(loop.children[0].children[0].children.length, 0);      // a → b → a, and it stops where it came round
});

test('a Note opened opens the branches that hold it, wherever it is', () => {
  const t = noteTree(rows, { note: 'orb', named: true });
  assert.deepEqual([...pathsTo(t, 'frame')].sort(), ['cube', 'orb']);
  assert.deepEqual([...pathsTo(t, 'orb')], []);
});

test('no main: every top design is listed', () => {
  const t = noteTree(rows, null);
  assert.equal(t.main, null);
  assert.ok(t.others.length >= 3);
});

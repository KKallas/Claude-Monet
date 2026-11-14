// Find (canvas/find.js): a few words narrow the Notes' tree (by name or by a check) and every list beside the view
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { found, noteStates, prune, query } from '../canvas/find.js';
import { noteTree } from '../canvas/tree.js';

const rows = [
  { name: 'cubic', kind: 'module' },
  { name: 'cube', kind: 'assembly', state: 'built', uses: ['cube_caps', 'cube_frame', 'cubic'] },
  { name: 'cube_caps', kind: 'assembly', state: 'built', uses: ['caps_top_01', 'caps_top_02'] },
  { name: 'caps_top_01', kind: 'note', state: 'built', uses: [] },
  { name: 'caps_top_02', kind: 'note', state: 'error', uses: [] },
  { name: 'cube_frame', kind: 'assembly', state: 'stale', uses: ['corner_ppp'] },
  { name: 'corner_ppp', kind: 'note', state: 'built', uses: [] },
  { name: 'lamp', kind: 'note', state: 'built', uses: [] },
];
const checks = {
  cube_caps: [{ id: 'pieces', what: 'pieces', equals: 268, expect: '= 268', why: 'every cap is a piece', by: 'user' }],
  corner_ppp: [{ id: 'fits-bed', what: 'fits_bed', expect: 'fits the bed', why: '', by: 'agent' }],
};
const tree = noteTree(rows, { note: 'cube', named: true });
const names = (t) => (t ? [t.name, ...t.children.flatMap(names)] : []);

test('words: all of them, in any case; is: picks by state', () => {
  const q = query('  Top  CAPS ');
  assert.ok(q.on && q.test('caps_top_01') && !q.test('caps_side_01'));
  assert.ok(!query('').on && query('').test('anything'));
  assert.ok(query('is:red').test('x', ['red']) && !query('is:red').test('x', ['ok']));
  assert.ok(query('is:red pieces').test('pieces = 268', ['red']) && !query('is:red pieces').test('size_x', ['red']));
});

test('nothing to find: the tree as it is', () => {
  assert.equal(prune(tree, query(''), checks), tree);
});

test('a Note by its name, with the branch that leads to it', () => {
  const t = prune(tree, query('top_02'), checks);
  assert.deepEqual(names(t.main), ['cube', 'cube_caps', 'caps_top_02']);
  assert.ok(!t.main.hit && t.main.children[0].children[0].hit);
  assert.deepEqual(t.others, []);
  assert.equal(found(t), 1);
});

test('a Note by one of its checks, and how many of them match', () => {
  const t = prune(tree, query('268'), checks);
  assert.deepEqual(names(t.main), ['cube', 'cube_caps']);
  assert.equal(t.main.children[0].hits, 1);
  const bed = prune(tree, query('fits_bed is:agent'), checks);
  assert.deepEqual(names(bed.main), ['cube', 'cube_frame', 'corner_ppp']);
  assert.equal(prune(tree, query('fits_bed is:user'), checks).main, null);
});

test('by state: what does not build, what waits for the agent; modules by name', () => {
  assert.deepEqual(names(prune(tree, query('is:red'), checks).main), ['cube', 'cube_caps', 'caps_top_02']);
  assert.deepEqual(names(prune(tree, query('is:waiting'), checks).main), ['cube', 'cube_frame']);
  assert.deepEqual(noteStates(rows[0]), ['module']);
  assert.deepEqual(prune(tree, query('cub'), checks).shared, ['cubic']);
  assert.deepEqual(prune(tree, query('lamp'), checks).others.map((t) => t.name), ['lamp']);
});

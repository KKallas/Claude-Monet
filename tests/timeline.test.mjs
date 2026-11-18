// The keyframes of canvas/timeline.js, without a page: run by tests/test_core.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { actionBetween, advance, kept, opened, deleteActions, deleteKeys, expand, keyFrames, moveActions, moveKeys, poseAt, setAction, setKey, tickStep, valueAt, played } from '../canvas/timeline.js';

test('between two keys a joint moves evenly; before the first and after the last it holds', () => {
  const keys = [[10, 0], [20, 90], [40, -90]];
  assert.equal(valueAt(keys, 0), 0);
  assert.equal(valueAt(keys, 15), 45);
  assert.equal(valueAt(keys, 30), 0);
  assert.equal(valueAt(keys, 99), -90);
  assert.equal(valueAt([], 5), undefined);
  assert.deepEqual(poseAt({ tracks: { a: [[0, 1]], b: [] } }, 7), { a: 1 });
});

test('one key to a frame, in order', () => {
  assert.deepEqual(setKey([[0, 1], [10, 2]], 5, 9), [[0, 1], [5, 9], [10, 2]]);
  assert.deepEqual(setKey([[0, 1], [10, 2]], 10, 3), [[0, 1], [10, 3]]);
  assert.deepEqual(keyFrames({ a: [[0, 1], [10, 2]], b: [[10, 0], [4, 0]] }), [0, 4, 10]);
});

test('keys move together, no further than the ends, and take the place of one they land on', () => {
  const tracks = { a: [[0, 1], [10, 2], [20, 3]], b: [[10, 5]] };
  const r = moveKeys(tracks, new Set(['a:10', 'b:10']), 10, 100);
  assert.deepEqual(r.tracks, { a: [[0, 1], [20, 2]], b: [[20, 5]] });
  assert.deepEqual([...r.ids].sort(), ['a:20', 'b:20']);
  assert.deepEqual(moveKeys(tracks, new Set(['a:20']), 500, 30).tracks.a, [[0, 1], [10, 2], [30, 3]]);
  assert.deepEqual(moveKeys(tracks, new Set(['a:10', 'a:20']), -50, 30).tracks.a, [[0, 2], [10, 3]]);
});

test('a key on the line of all keys stands for every key at its frame', () => {
  const tracks = { a: [[0, 1], [10, 2]], b: [[10, 5]] };
  assert.deepEqual([...expand(tracks, new Set(['*:10']))].sort(), ['a:10', 'b:10']);
  assert.deepEqual(deleteKeys(tracks, expand(tracks, new Set(['*:10']))), { a: [[0, 1]] });
});

test('the ruler numbers stand apart', () => {
  assert.equal(tickStep(120, 1200), 10);
  assert.equal(tickStep(120, 6000), 2);
  assert.equal(tickStep(10000, 1000), 1000);
});

test('playing meets the actions: a pause stops, a goto goes on, the end ends or goes round (tests/advance.json)', () => {
  const fx = JSON.parse(readFileSync(new URL('./advance.json', import.meta.url)));
  for (const s of fx.steps) {
    const r = advance(fx.anims[s.anim], { frame: s.frame, lo: s.lo }, s.d, s.loop);
    assert.deepEqual([r.frame, r.lo, r.stop, r.action?.frame ?? null], s.out, JSON.stringify(s));
  }
});

test('a video shows the frames playing would (played, tests/advance.json)', () => {
  const fx = JSON.parse(readFileSync(new URL('./advance.json', import.meta.url)));
  for (const p of fx.played) assert.deepEqual(played(fx.anims[p.anim], p.fps), p.out, `${p.anim} at ${p.fps}`);
});

test('a video follows the actions: to the end, to a pause and held there, a loop of gotos shown once', () => {
  const plain = { fps: 30, length: 60, tracks: {} }, every3 = (to) => Array.from({ length: to / 3 + 1 }, (_, i) => i * 3);
  assert.deepEqual(played(plain, 10), every3(60));
  assert.deepEqual(played({ ...plain, actions: [{ frame: 30, do: 'pause', hold: 1.0 }] }, 10), [...every3(30), ...Array(10).fill(30)]);
  assert.deepEqual(played({ ...plain, actions: [{ frame: 30, do: 'pause' }] }, 10).slice(-2), [27, 30]);
  assert.deepEqual(played({ ...plain, actions: [{ frame: 50, do: 'goto', to: 10 }] }, 3), [0, 10, 20, 30, 40, 10, 20, 30, 40]);
  // two gotos sending playing to each other: shown once, it ends
  assert.ok(played({ ...plain, actions: [{ frame: 20, do: 'goto', to: 40 }, { frame: 40, do: 'goto', to: 20 }] }, 30).length < 100);
});

test('an action is met once, going past it, never where playing starts', () => {
  const acts = [{ frame: 10, do: 'pause' }, { frame: 12, do: 'goto', to: 0 }];
  assert.equal(actionBetween(acts, 0, 9.9), null);
  assert.equal(actionBetween(acts, 9.5, 20).frame, 10);       // the first of two in one step
  assert.equal(actionBetween(acts, 10, 11), null);            // played on from a pause: not met again
  assert.equal(actionBetween([], 0, 100), null);
});

test('actions: one to a frame, moved from frame 1 to the end, taken away', () => {
  let acts = setAction([], 30, { do: 'pause' });
  acts = setAction(acts, 10, { do: 'goto', to: 0 });
  acts = setAction(acts, 30, { do: 'pause', hold: 2 });
  assert.deepEqual(acts, [{ do: 'goto', to: 0, frame: 10 }, { do: 'pause', hold: 2, frame: 30 }]);
  const m = moveActions(acts, new Set(['!:10']), -50, 60);
  assert.deepEqual(m.actions.map((a) => a.frame), [1, 30]);
  assert.deepEqual([...m.ids], ['!:1']);
  assert.deepEqual(moveActions(acts, new Set(['!:10']), 20, 60).actions.map((a) => a.frame), [30]);      // landed on the other
  assert.deepEqual(deleteActions(acts, new Set(['!:30', 'a:30'])).map((a) => a.frame), [10]);
  assert.deepEqual(setAction(acts, 10, null).map((a) => a.frame), [30]);
});

test('light lines: "~name" on the timeline, kept apart as lights in the project', () => {
  const a = { fps: 24, length: 48, tracks: { leaf: [[0, 0]] }, lights: { led: [[0, 0], [24, 1]], haze: [[0, 0.5]] }, actions: [] };
  const o = opened(a);
  assert.deepEqual(Object.keys(o.tracks).sort(), ['leaf', '~haze', '~led']);
  assert.equal(o.lights, undefined);
  assert.deepEqual(poseAt(o, 12), { leaf: 0, '~led': 0.5, '~haze': 0.5 });
  assert.deepEqual(kept(o), { fps: 24, length: 48, tracks: { leaf: [[0, 0]] }, lights: { led: [[0, 0], [24, 1]], haze: [[0, 0.5]] }, actions: [] });
  assert.equal(kept(opened({ fps: 30, length: 10, tracks: {} })).lights, undefined);
});

test('a study keeps its camera, section and parts as lines, and gives them back as it was given them', async () => {
  const { kept, opened, poseAt, viewLine } = await import('../canvas/timeline.js');
  const cam = (x) => ({ proj: 'persp', p: [x, -100, 80], t: [0, 0, 10], u: [0, 0, 1], z: 1, fov: 35 });
  const study = { of: 'arm', fps: 30, length: 120, tracks: { j1: [[0, 0], [60, 45]] }, actions: [],
    camera: [[0, cam(100)], [120, cam(0)]], section: { axis: 'Y', flip: false, keys: [[0, 0.4], [100, 0.6]] },
    visible: { 'tool/cover': [[0, 1], [60, 0]] }, clear: { housing: [[0, 1], [90, 0.2]] }, view: { style: 'shaded', edges: true } };
  const a = opened(structuredClone(study));
  assert.deepEqual(Object.keys(a.tracks).sort(), ['%housing', '@camera', '@section', '^tool/cover', 'j1']);
  assert.deepEqual(a.section, { axis: 'Y', flip: false });
  assert.deepEqual(kept(a), study);
  const at = poseAt(a, 30);
  assert.deepEqual(at['@camera'].p, [75, -100, 80]);            // the camera moves straight, number by number
  assert.equal(at['@camera'].proj, 'persp');
  assert.ok(Math.abs(at['@section'] - 0.46) < 1e-9);
  assert.equal(at['^tool/cover'], 1);                            // shown until the key that hides it: held, not faded
  assert.equal(poseAt(a, 59.9)['^tool/cover'], 1);
  assert.equal(poseAt(a, 60)['^tool/cover'], 0);
  assert.ok(Math.abs(poseAt(a, 45)['%housing'] - 0.6) < 1e-9);
  assert.ok(viewLine('@camera') && viewLine('^x') && viewLine('%x') && !viewLine('j1') && !viewLine('~lamp'));
});

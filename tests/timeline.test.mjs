// The keyframes of canvas/timeline.js, without a page: run by tests/test_core.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { actionBetween, advance, kept, opened, deleteActions, deleteKeys, expand, keyFrames, moveActions, moveKeys, poseAt, setAction, setKey, tickStep, valueAt } from '../canvas/timeline.js';

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

test('playing meets the actions as the server plays them for a video (tests/advance.json)', () => {
  const fx = JSON.parse(readFileSync(new URL('./advance.json', import.meta.url)));
  for (const s of fx.steps) {
    const r = advance(fx.anims[s.anim], { frame: s.frame, lo: s.lo }, s.d, s.loop);
    assert.deepEqual([r.frame, r.lo, r.stop, r.action?.frame ?? null], s.out, JSON.stringify(s));
  }
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

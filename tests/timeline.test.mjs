// The keyframes of canvas/timeline.js, without a page: run by tests/test_core.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deleteKeys, expand, keyFrames, moveKeys, poseAt, setKey, tickStep, valueAt } from '../canvas/timeline.js';

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

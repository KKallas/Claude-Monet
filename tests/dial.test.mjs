// The arithmetic of the dials (canvas/dial.js) and of the rails' width (canvas/rails.js): run by tests/test_core.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { along, decimals, snap } from '../canvas/dial.js';
import { ICON_W, TEXT_MAX, TEXT_MIN, settle } from '../canvas/rails.js';

test('a value is kept in range and put on the step, without the float tail', () => {
  assert.equal(snap(0.30000000000000004, 0, 1, 0.1), 0.3);
  assert.equal(snap(7.26, 0, 10, 0.5), 7.5);
  assert.equal(snap(-500, -180, 180, 0.5), -180);
  assert.equal(snap(2, 0, 1.5, 0.01), 1.5);
  assert.equal(snap(0.4567, 0, 1, 0.002), 0.456);
});

test('the presets are per cent of the way from the low end', () => {
  assert.deepEqual([0, 25, 50, 75, 100].map((p) => along(p, -180, 180, 0.5)), [-180, -90, 0, 90, 180]);
  assert.deepEqual([0, 25, 50, 75, 100].map((p) => along(p, 0, 1.5, 0.01)), [0, 0.38, 0.75, 1.13, 1.5]);
});

test('decimals of a step', () => {
  assert.equal(decimals(0.5), 1);
  assert.equal(decimals(0.002), 3);
  assert.equal(decimals(1e-7), 7);
  assert.equal(decimals(2), 0);
});

test('the rails settle to icons under the threshold and to labels from it', () => {
  assert.equal(settle(60), ICON_W);
  assert.equal(settle(TEXT_MIN - 1), ICON_W);
  assert.equal(settle(TEXT_MIN), TEXT_MIN);
  assert.equal(settle(999), TEXT_MAX);
});

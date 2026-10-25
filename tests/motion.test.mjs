// node --test tests/motion.test.mjs   (where the canvas puts the parts at a pose; run by pytest too, where node is there,
// which also holds it against monet/joints.py on the MG400)
import test from 'node:test';
import assert from 'node:assert/strict';
import { apply, drivers, frames, handle, span, values } from '../canvas/motion.js';

const close = (a, b, eps = 1e-9) => a.forEach((x, i) => assert.ok(Math.abs(x - b[i]) <= eps, `${a} is not ${b}`));
// a frame with a lid on a hinge, a knob sliding on the lid, a wheel geared to the hinge, and a loose part
const model = {
  bodies: { frame: ['a', 'b'], lid: ['lid'], knob: ['knob'], wheel: ['wheel'], loose: ['loose'] },
  ground: ['frame'], free: ['loose'], tree: ['hinge', 'gear', 'slide'], follow_order: ['hinge', 'slide', 'gear'],
  joints: {
    frame: { kind: 'rigid', resolved: true },
    hinge: { kind: 'revolute', moves: 'lid', on: 'frame', origin: [10, 0, 0], dir: [0, 1, 0], range: [0, 90], follows: null, resolved: true },
    slide: { kind: 'slider', moves: 'knob', on: 'lid', origin: [0, 0, 0], dir: [1, 0, 0], range: null, follows: null, resolved: true },
    gear: { kind: 'revolute', moves: 'wheel', on: 'frame', origin: [0, 0, 0], dir: [0, 0, 1], range: null, follows: { hinge: 2 }, resolved: true },
  },
};

test('followers are worked out from the drivers', () => {
  assert.deepEqual(drivers(model), ['hinge', 'slide']);
  assert.equal(values(model, { hinge: 30 }).gear, 60);
  assert.equal(values(model, { gear: 99 }).gear, 0);          // a follower is never moved by hand
});

test('a quarter turn about +Y, right hand: +X goes to -Z; what rides on it turns with it', () => {
  const f = frames(model, { hinge: 90, slide: 2 });
  close(apply(f.frame, [3, 4, 5]), [3, 4, 5]);
  close(apply(f.lid, [20, 0, 0]), [10, 0, -10]);
  close(apply(f.knob, [20, 0, 0]), [10, 0, -12]);
  close(apply(f.wheel, [1, 0, 0]), [-1, 0, 0]);               // geared at two to one: half a turn
});

test('a drag moves the joint the body hangs on; the ground and rigid parts of it are held', () => {
  assert.deepEqual(handle(model, 'knob'), { joint: 'slide' });
  assert.deepEqual(handle(model, 'wheel'), { joint: 'hinge' });  // a follower: its driver
  assert.deepEqual(handle(model, 'loose'), { free: true, body: 'loose' });
  assert.equal(handle(model, 'frame'), null);
  assert.deepEqual(span(model.joints.hinge), [0, 90]);
  assert.deepEqual(span(model.joints.gear), [-180, 180]);
});

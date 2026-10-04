// node --test tests/measure.test.mjs   (the measuring geometry of the canvas; run by pytest too, where node is there)
import test from 'node:test';
import assert from 'node:assert/strict';
import { angle, betweenSegments, closest, onSegment, onTriangle, segmentTriangle, throughTriangle } from '../canvas/measure.js';

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);
const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
// a 10 x 10 square in the plane z = h, as two triangles
const square = (h, x = 0, y = 0) => [[[x, y, h], [x + 10, y, h], [x + 10, y + 10, h]], [[x, y, h], [x + 10, y + 10, h], [x, y + 10, h]]];

test('point to segment: inside, and past each end', () => {
  assert.deepEqual(onSegment([5, 3, 0], [0, 0, 0], [10, 0, 0]), [5, 0, 0]);
  assert.deepEqual(onSegment([-4, 3, 0], [0, 0, 0], [10, 0, 0]), [0, 0, 0]);
  assert.deepEqual(onSegment([14, 3, 0], [0, 0, 0], [10, 0, 0]), [10, 0, 0]);
});

test('point to triangle: over the face, an edge and a corner', () => {
  const [a, b, c] = [[0, 0, 0], [10, 0, 0], [0, 10, 0]];
  assert.deepEqual(onTriangle([2, 2, 7], a, b, c), [2, 2, 0]);
  assert.deepEqual(onTriangle([5, -3, 0], a, b, c), [5, 0, 0]);
  assert.deepEqual(onTriangle([-2, -2, 1], a, b, c), [0, 0, 0]);
  assert.deepEqual(onTriangle([10, 10, 0], a, b, c), [5, 5, 0]);
});

test('two segments: crossing at a height, parallel, end to end', () => {
  near(d(...betweenSegments([0, 0, 0], [10, 0, 0], [5, -5, 3], [5, 5, 3])), 3);
  near(d(...betweenSegments([0, 0, 0], [10, 0, 0], [0, 4, 0], [10, 4, 0])), 4);
  near(d(...betweenSegments([0, 0, 0], [10, 0, 0], [13, 4, 0], [20, 4, 0])), 5);
});

test('a segment through a triangle touches it', () => {
  const t = [[0, 0, 0], [10, 0, 0], [0, 10, 0]];
  assert.deepEqual(throughTriangle([2, 2, -1], [2, 2, 1], ...t), [2, 2, 0]);
  assert.equal(throughTriangle([20, 20, -1], [20, 20, 1], ...t), null);
  near(d(...segmentTriangle([2, 2, -1], [2, 2, 1], ...t)), 0);
  near(d(...segmentTriangle([2, 2, 3], [4, 4, 5], ...t)), 3);
});

test('closest: the pairs a person measures', () => {
  near(closest({ points: [[0, 0, 0]] }, { points: [[3, 4, 12]] }).d, 13);                      // corner to corner
  near(closest({ points: [[5, 5, 7]] }, { triangles: square(0) }).d, 7);                       // corner to face
  near(closest({ triangles: square(0) }, { triangles: square(22.4) }).d, 22.4);                // two parallel faces
  near(closest({ triangles: square(0) }, { triangles: square(0, 14, 0) }).d, 4);               // side by side, in one plane
  near(closest({ segments: [[[0, 0, 5], [10, 0, 5]]] }, { triangles: square(0) }).d, 5);       // an edge over a face
  near(closest({ segments: [[[0, 0, 0], [10, 0, 0]]] }, { segments: [[[0, 6, 8], [10, 6, 8]]] }).d, 10);
  const r = closest({ points: [[5, 5, 7]] }, { triangles: square(0) });
  assert.deepEqual([r.a, r.b, r.about], [[5, 5, 7], [5, 5, 0], false]);
});

test('closest: too much to do exactly is said to be about', () => {
  const many = (h) => Array.from({ length: 400 }, (_, i) => square(h, (i % 20) * 10, Math.floor(i / 20) * 10)).flat();
  const r = closest({ triangles: many(0) }, { triangles: many(3) });
  assert.equal(r.about, true);
  near(r.d, 3, 1e-6);
});

test('angles', () => {
  near(angle({ line: [1, 0, 0] }, { line: [0, 1, 0] }), 90);
  near(angle({ line: [1, 0, 0] }, { line: [-2, 0, 0] }), 0);
  near(angle({ normal: [0, 0, 1] }, { normal: [0, 1, 0] }), 90);
  near(angle({ line: [1, 0, 0] }, { normal: [0, 0, 1] }), 0, 1e-6);          // the line lies in the face
  near(angle({ line: [0, 0, 1] }, { normal: [0, 0, 1] }), 90);         // the line stands on the face
  near(angle({ line: [1, 1, 0] }, { line: [1, 0, 0] }), 45, 1e-6);
  assert.equal(angle({ line: [1, 0, 0] }, {}), null);
});

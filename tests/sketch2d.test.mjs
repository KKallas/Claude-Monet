// node --test tests/sketch2d.test.mjs   (what the sketch tools do to curves; run by pytest too, where node is there)
import test from 'node:test';
import assert from 'node:assert/strict';
import { elements, fillet, flatten, isClosed, lengthOf, meet, nearest, nearestCorner, offset, ovalThrough, toPath, trim } from '../canvas/sketch2d.js';

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);
const nearPt = (p, q, eps = 1e-3) => assert.ok(Math.hypot(p[0] - q[0], p[1] - q[1]) <= eps, `${p} is not ${q}`);
const line = (...pts) => ({ type: 'polyline', points: pts, closed: false });
const rect = (u, v, w, h) => ({ type: 'rect', at: [u, v], size: [w, h] });
const circle = (u, v, r) => ({ type: 'circle', center: [u, v], r });
const Q = Math.tan(Math.PI / 8);      // the bulge of a quarter turn

test('a bulge is an arc: a quarter circle about the origin', () => {
  const [arc] = elements(line([1, 0, Q], [0, 1]));
  assert.equal(arc.kind, 'arc');
  nearPt(arc.c, [0, 0]); near(arc.r, 1); near(arc.sweep, Math.PI / 2);
  near(lengthOf(line([1, 0, Q], [0, 1])), Math.PI / 2);
  near(lengthOf(line([1, 0, -Q], [0, 1])), Math.PI / 2);          // the other way round: about (1, 1)
  nearPt(elements(line([1, 0, -Q], [0, 1]))[0].c, [1, 1]);
  const pts = flatten(line([1, 0, Q], [0, 1]));
  for (const p of pts) near(Math.hypot(...p), 1, 1e-9);
});

test('lengths, and what is closed', () => {
  near(lengthOf(rect(0, 0, 10, 4)), 28);
  near(lengthOf(circle(0, 0, 5)), 10 * Math.PI);
  near(lengthOf({ type: 'ellipse', center: [0, 0], rx: 5, ry: 5, rotation: 30 }), 10 * Math.PI, 1e-2);
  assert.deepEqual([rect(0, 0, 1, 1), circle(0, 0, 1), line([0, 0], [1, 1]), { type: 'polyline', points: [[0, 0], [1, 0], [0, 1]], closed: true }].map(isClosed), [true, true, false, true]);
});

test('where things meet', () => {
  const [l] = elements(line([-10, 0], [10, 0])), [c] = elements(circle(0, 0, 5));
  assert.equal(meet(l, c).length, 2);
  assert.equal(meet(elements(line([-10, 5], [10, 5]))[0], c).length, 1);            // touching
  assert.equal(meet(elements(line([-10, 6], [10, 6]))[0], c).length, 0);
  nearPt(meet(elements(line([0, 0], [10, 10]))[0], elements(line([0, 10], [10, 0]))[0])[0], [5, 5]);
  assert.equal(meet(elements(line([0, 0], [1, 1]))[0], elements(line([0, 10], [10, 0]))[0]).length, 0);     // would meet, were it longer
  assert.equal(meet(c, elements(circle(8, 0, 5))[0]).length, 2);
  const [quarter] = elements(line([5, 0, Q], [0, 5]));                              // only the first quarter of that circle
  assert.equal(meet(elements(line([-10, 3], [10, 3]))[0], quarter).length, 1);
});

test('nearest: the curve, and where on it', () => {
  const hit = nearest([rect(0, 0, 10, 4), circle(20, 0, 3)], [5, -1]);
  assert.deepEqual([hit.curve, hit.element], [0, 0]);
  near(hit.d, 1); near(hit.t, 0.5);
  assert.equal(nearest([rect(0, 0, 10, 4), circle(20, 0, 3)], [20, 4]).curve, 1);
  assert.deepEqual([nearestCorner([rect(0, 0, 10, 4)], [9.5, 4.2]).vertex, nearestCorner([circle(0, 0, 1)], [0, 0])], [2, null]);
});

test('trim: a line across a rectangle loses what sticks out, or what is inside', () => {
  const curves = [rect(0, 0, 10, 10), line([-5, 5], [15, 5])];
  // click the stub on the left: it goes, the rest stays as one line from the rectangle's side
  assert.deepEqual(trim(curves, nearest(curves, [-3, 5])), [rect(0, 0, 10, 10), line([0, 5], [15, 5])]);
  // click the middle: two stubs are left
  assert.deepEqual(trim(curves, { curve: 1, element: 0, t: 0.5 }), [rect(0, 0, 10, 10), line([-5, 5], [0, 5]), line([10, 5], [15, 5])]);
  // click the rectangle's right side above the line: the rectangle opens there, and is one line the rest of the way round
  assert.deepEqual(trim(curves, { curve: 0, element: 1, t: 0.75 }), [line([10, 10], [0, 10], [0, 0], [10, 0], [10, 5]), curves[1]]);
  // and below the line
  assert.deepEqual(trim(curves, { curve: 0, element: 1, t: 0.25 })[0], line([10, 5], [10, 10], [0, 10], [0, 0], [10, 0]));
});

test('trim: a side with nothing crossing it goes whole', () => {
  const out = trim([rect(0, 0, 10, 4)], { curve: 0, element: 0, t: 0.5 });      // the bottom side
  assert.deepEqual(out, [{ type: 'polyline', closed: false, points: [[10, 0], [10, 4], [0, 4], [0, 0]] }]);
  assert.deepEqual(trim([line([0, 0], [5, 0], [5, 5])], { curve: 0, element: 0, t: 0.5 }), [line([5, 0], [5, 5])]);
  assert.deepEqual(trim([line([0, 0], [5, 0])], { curve: 0, element: 0, t: 0.5 }), []);
});

test('trim: a circle cut by a line keeps the arc that was not clicked', () => {
  const curves = [circle(0, 0, 5), line([-10, 0], [10, 0])];
  const top = trim(curves, nearest([curves[0]], [0, 6]));           // click the top: the bottom half is left
  assert.equal(top.length, 2);
  const [arc] = elements(top[0]);
  nearPt(arc.a, [-5, 0]); nearPt(arc.b, [5, 0]); near(Math.abs(arc.sweep), Math.PI, 1e-5); nearPt(arc.c, [0, 0]);
  nearPt(flatten(top[0])[Math.floor(flatten(top[0]).length / 2)], [0, -5], 1e-2);        // it is the lower half
  near(lengthOf(top[0]), 5 * Math.PI, 1e-4);
  assert.deepEqual(trim([circle(0, 0, 5)], { curve: 0, element: 0, t: 0.3 }), []);      // nothing crosses it: it goes
  // and the line, clicked inside the circle, is left as its two ends
  assert.deepEqual(trim(curves, { curve: 1, element: 0, t: 0.5 }).slice(1), [line([-10, 0], [-5, 0]), line([5, 0], [10, 0])]);
});

test('trim: an arc inside a line keeps its roundness on both sides of the cut', () => {
  const curves = [line([5, 0, Q], [0, 5]), line([0, 0], [10, 10])];      // a quarter circle, crossed on the diagonal
  const out = trim(curves, { curve: 0, element: 0, t: 0.25 });            // click before the crossing
  assert.equal(out.length, 2);
  const [left] = elements(out[0]);
  nearPt(left.c, [0, 0]); near(left.r, 5, 1e-3); near(left.sweep, Math.PI / 4, 1e-4); nearPt(left.b, [0, 5]);
});

test('fillet: a square corner, rounded', () => {
  const { curves } = fillet([rect(0, 0, 10, 10)], { curve: 0, vertex: 1 }, 2);
  assert.equal(curves[0].points.length, 5);
  assert.deepEqual(curves[0].points[1].slice(0, 2), [8, 0]);
  assert.deepEqual(curves[0].points[2], [10, 2]);
  const arc = elements(curves[0])[1];
  nearPt(arc.c, [8, 2]); near(arc.r, 2); near(arc.sweep, Math.PI / 2);
  near(lengthOf(curves[0]), 40 - 4 + Math.PI, 1e-5);
  assert.equal(isClosed(curves[0]), true);
  // the other way round turns right: the bulge is negative, the centre still inside the corner
  const right = fillet([line([0, 0], [0, 10], [10, 10])], { curve: 0, vertex: 1 }, 2).curves[0];
  assert.ok(right.points[1][2] < 0);
  nearPt(elements(right)[1].c, [2, 8]);
});

test('fillet: what cannot be rounded says why', () => {
  assert.match(fillet([rect(0, 0, 10, 4)], { curve: 0, vertex: 1 }, 5).error, /too large.*at most 4/);
  assert.equal(fillet([rect(0, 0, 10, 4)], { curve: 0, vertex: 1 }, 3).error, undefined);      // 3 does fit
  assert.match(fillet([line([0, 0], [5, 0], [5, 5])], { curve: 0, vertex: 0 }, 1).error, /an end/);
  assert.match(fillet([circle(0, 0, 5)], { curve: 0, vertex: 0 }, 1).error, /corner of a rectangle or a line/);
  assert.match(fillet([line([0, 0], [5, 0], [10, 0])], { curve: 0, vertex: 1 }, 1).error, /straight on/);
  const once = fillet([rect(0, 0, 10, 10)], { curve: 0, vertex: 1 }, 2).curves;
  assert.match(fillet(once, { curve: 0, vertex: 2 }, 1).error, /two straight lines/);
});

test('offset: out and in, by the side that is pointed at', () => {
  assert.deepEqual(offset(circle(0, 0, 5), 2, [9, 0]), circle(0, 0, 7));
  assert.deepEqual(offset(circle(0, 0, 5), 2, [1, 0]), circle(0, 0, 3));
  assert.equal(offset(circle(0, 0, 5), 6, [1, 0]), null);
  assert.deepEqual(offset(rect(0, 0, 10, 4), 1, [5, -3]), rect(-1, -1, 12, 6));
  assert.deepEqual(offset(rect(0, 0, 10, 4), 1, [5, 2]), rect(1, 1, 8, 2));
  assert.equal(offset(rect(0, 0, 10, 4), 2, [5, 2]), null);
  assert.deepEqual(offset({ type: 'ellipse', center: [0, 0], rx: 6, ry: 3, rotation: 0 }, 1, [0, 9]), { type: 'ellipse', center: [0, 0], rx: 7, ry: 4, rotation: 0 });
  assert.deepEqual(offset(line([0, 0], [10, 0]), 2, [5, 5]), line([0, 2], [10, 2]));
  assert.deepEqual(offset(line([0, 0], [10, 0], [10, 10]), 2, [5, 5]), line([0, 2], [8, 2], [8, 10]));       // inside the corner
  assert.deepEqual(offset(line([0, 0], [10, 0], [10, 10]), 2, [5, -5]), line([0, -2], [12, -2], [12, 10]));  // outside it
  const tri = { type: 'polyline', points: [[0, 0], [10, 0], [0, 10]], closed: true };
  const grown = offset(tri, 1, [-5, -5]);
  assert.equal(grown.closed, true);
  assert.deepEqual(grown.points[0], [-1, -1]);
  near(lengthOf(grown) > lengthOf(tri) ? 1 : 0, 1);
});

test('the oval through three clicks', () => {
  assert.deepEqual(ovalThrough([-6, 0], [6, 0], [2, 3]), { type: 'ellipse', center: [0, 0], rx: 6, ry: 3, rotation: 0 });
  const tilted = ovalThrough([0, 0], [10, 10], [0, 4]);
  assert.deepEqual([tilted.center, tilted.rotation], [[5, 5], 45]);
  near(tilted.rx, Math.SQRT2 * 5, 1e-3); near(tilted.ry, 2 * Math.SQRT2, 1e-3);
  assert.equal(ovalThrough([0, 0], [0, 0], [1, 1]), null);
  assert.equal(ovalThrough([0, 0], [10, 0], [5, 0]), null);
  assert.equal(toPath(tilted), null);
});

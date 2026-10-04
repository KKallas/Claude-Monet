// The geometry of a sketch: curves on a plane, in millimetres, and what the tools do to them.
//
// A curve is one of
//   {type: 'polyline', points: [[u, v] or [u, v, bulge], ...], closed}
//   {type: 'rect', at: [u, v], size: [w, h]}
//   {type: 'circle', center: [u, v], r}
//   {type: 'ellipse', center: [u, v], rx, ry, rotation}      rotation in degrees, of the rx axis from +u
// A bulge makes the stretch from that point to the next an arc instead of a line: tan(angle / 4), positive when the
// arc turns left (counter-clockwise), as in DXF. That is how a fillet and a trimmed circle are kept exactly.
//
// Plain arrays, no DOM, no three.js: it runs in node for its tests. Offset, trim and fillet follow what Adam Designer
// offers (docs/designer/29); the oval is its three-click one (docs/designer/40).

const TAU = Math.PI * 2;
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const mul = (a, k) => [a[0] * k, a[1] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const turn = (a) => ((a % TAU) + TAU) % TAU;
const r3 = (v) => Math.round(v * 1000) / 1000;
const r6 = (v) => Math.round(v * 1e9) / 1e9;      // bulges and turns: fine enough that a radius comes back to the micron
const clamp01 = (t) => Math.max(0, Math.min(1, t));

/** A rectangle or a polyline as a path {points: [[u, v, bulge]], closed}; null for a circle or an ellipse. */
export function toPath(curve) {
  if (curve.type === 'rect') {
    const [u, v] = curve.at, [w, h] = curve.size;
    return { points: [[u, v, 0], [u + w, v, 0], [u + w, v + h, 0], [u, v + h, 0]], closed: true };
  }
  if (curve.type !== 'polyline') return null;
  const points = curve.points.map((p) => [p[0], p[1], p[2] ?? 0]);
  return { points, closed: !!curve.closed && points.length > 2 };
}

/** A path as the polyline it is kept as. */
export function fromPath(path) {
  const n = path.points.length;
  return { type: 'polyline', closed: !!path.closed && n > 2,
    points: path.points.map((p, i) => ((p[2] && (path.closed || i < n - 1)) ? [r3(p[0]), r3(p[1]), r6(p[2])] : [r3(p[0]), r3(p[1])])) };
}

function arcBetween(p0, p1, bulge) {      // the arc from p0 to p1 that a bulge stands for
  const d = dist(p0, p1), sweep = 4 * Math.atan(bulge);
  const mid = mul(add(p0, p1), 0.5), left = [-(p1[1] - p0[1]) / d, (p1[0] - p0[0]) / d];
  const c = add(mid, mul(left, (d / 2) / Math.tan(sweep / 2)));
  return { kind: 'arc', c, r: dist(c, p0), a0: Math.atan2(p0[1] - c[1], p0[0] - c[0]), sweep, a: p0, b: p1 };
}

/** The points of an ellipse, all the way round (the first again at the end). */
function ellipsePoints(e, n = 72) {
  const k = (e.rotation ?? 0) * Math.PI / 180, cs = Math.cos(k), sn = Math.sin(k);
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = (i % n) * TAU / n, x = e.rx * Math.cos(t), y = e.ry * Math.sin(t);
    return [e.center[0] + x * cs - y * sn, e.center[1] + x * sn + y * cs];
  });
}

/** What a curve is made of: straight {kind: 'line', a, b} and round {kind: 'arc', c, r, a0, sweep, a, b} elements. */
export function elements(curve) {
  if (curve.type === 'circle') return [{ kind: 'arc', c: curve.center, r: curve.r, a0: 0, sweep: TAU, full: true, a: add(curve.center, [curve.r, 0]), b: add(curve.center, [curve.r, 0]) }];
  if (curve.type === 'ellipse') { const p = ellipsePoints(curve); return p.slice(0, -1).map((a, i) => ({ kind: 'line', a, b: p[i + 1] })); }
  const path = toPath(curve), n = path.points.length, out = [];
  for (let i = 0; i < (path.closed ? n : n - 1); i++) {
    const p = path.points[i], q = path.points[(i + 1) % n];
    out.push(Math.abs(p[2]) > 1e-9 && dist(p, q) > 1e-9 ? arcBetween([p[0], p[1]], [q[0], q[1]], p[2]) : { kind: 'line', a: [p[0], p[1]], b: [q[0], q[1]] });
  }
  return out;
}

const pointAt = (el, t) => (el.kind === 'line' ? add(el.a, mul(sub(el.b, el.a), t)) : [el.c[0] + el.r * Math.cos(el.a0 + el.sweep * t), el.c[1] + el.r * Math.sin(el.a0 + el.sweep * t)]);

function paramOf(el, p) {      // where along the element a point is: 0 at its start, 1 at its end (may fall outside)
  if (el.kind === 'line') { const d = sub(el.b, el.a); return dot(sub(p, el.a), d) / dot(d, d); }
  const ang = Math.atan2(p[1] - el.c[1], p[0] - el.c[0]);
  const t = turn((ang - el.a0) * Math.sign(el.sweep)) / Math.abs(el.sweep);
  // just before the start reads as almost a whole turn: fold it back to just below 0
  return t > 1 + 1e-7 && t * Math.abs(el.sweep) > TAU - 1e-7 ? (t * Math.abs(el.sweep) - TAU) / Math.abs(el.sweep) : t;
}
const within = (t) => t >= -1e-7 && t <= 1 + 1e-7;

/** A curve as straight runs fine enough to draw and to hit: [[u, v], ...]; closed ones end where they began. */
export function flatten(curve) {
  if (curve.type === 'ellipse') return ellipsePoints(curve);
  const out = [];
  for (const el of elements(curve)) {
    if (!out.length) out.push(el.a);
    if (el.kind === 'line') { out.push(el.b); continue; }
    const steps = Math.max(2, Math.min(180, Math.ceil(Math.abs(el.sweep) / (5 * Math.PI / 180))));
    for (let k = 1; k <= steps; k++) out.push(pointAt(el, k / steps));
  }
  return out;
}

export function lengthOf(curve) {
  if (curve.type === 'ellipse') { const p = ellipsePoints(curve, 360); return p.slice(1).reduce((s, q, i) => s + dist(p[i], q), 0); }
  return elements(curve).reduce((s, el) => s + (el.kind === 'line' ? dist(el.a, el.b) : Math.abs(el.sweep) * el.r), 0);
}

export const isClosed = (curve) => curve.type !== 'polyline' || (!!curve.closed && curve.points.length > 2);

/** Where two elements meet: [[u, v], ...]. Lines lying along each other are not counted. */
export function meet(e1, e2) {
  if (e1.kind === 'line' && e2.kind === 'line') {
    const d1 = sub(e1.b, e1.a), d2 = sub(e2.b, e2.a), den = cross(d1, d2);
    if (Math.abs(den) < 1e-12) return [];
    const w = sub(e2.a, e1.a), t = cross(w, d2) / den, u = cross(w, d1) / den;
    return within(t) && within(u) ? [add(e1.a, mul(d1, t))] : [];
  }
  if (e1.kind === 'line' || e2.kind === 'line') {
    const [line, arc] = e1.kind === 'line' ? [e1, e2] : [e2, e1];
    const d = sub(line.b, line.a), f = sub(line.a, arc.c);
    const A = dot(d, d), B = 2 * dot(f, d), C = dot(f, f) - arc.r * arc.r, disc = B * B - 4 * A * C;
    if (disc < -1e-9 || A < 1e-18) return [];
    const s = Math.sqrt(Math.max(0, disc));
    const ts = s < 1e-7 ? [-B / (2 * A)] : [(-B - s) / (2 * A), (-B + s) / (2 * A)];
    return ts.filter(within).map((t) => add(line.a, mul(d, t))).filter((p) => arc.full || within(paramOf(arc, p)));
  }
  const d = dist(e1.c, e2.c);
  if (d < 1e-9 || d > e1.r + e2.r + 1e-9 || d < Math.abs(e1.r - e2.r) - 1e-9) return [];
  const a = (e1.r * e1.r - e2.r * e2.r + d * d) / (2 * d), h = Math.sqrt(Math.max(0, e1.r * e1.r - a * a));
  const u = mul(sub(e2.c, e1.c), 1 / d), m = add(e1.c, mul(u, a)), n = [-u[1], u[0]];
  const pts = h < 1e-7 ? [m] : [add(m, mul(n, h)), sub(m, mul(n, h))];
  return pts.filter((p) => (e1.full || within(paramOf(e1, p))) && (e2.full || within(paramOf(e2, p))));
}

function closestOn(el, p) {
  if (el.kind === 'line') { const t = clamp01(paramOf(el, p)); return { t, point: pointAt(el, t) }; }
  let t = el.full ? turn(Math.atan2(p[1] - el.c[1], p[0] - el.c[0])) / TAU : paramOf(el, p);
  if (!el.full && !within(t)) t = dist(p, el.a) < dist(p, el.b) ? 0 : 1;
  t = clamp01(t);
  return { t, point: pointAt(el, t) };
}

/** The curve nearest to a point: {curve, element, t, d, point}, or null when there are none. */
export function nearest(curves, p) {
  let best = null;
  curves.forEach((c, curve) => elements(c).forEach((el, element) => {
    const { t, point } = closestOn(el, p), d = dist(point, p);
    if (!best || d < best.d) best = { curve, element, t, d, point };
  }));
  return best;
}

/** The corner nearest to a point: {curve, vertex, d, point}. Corners are the points of rectangles and polylines. */
export function nearestCorner(curves, p) {
  let best = null;
  curves.forEach((c, curve) => (toPath(c)?.points ?? []).forEach((q, vertex) => {
    const d = dist(q, p);
    if (!best || d < best.d) best = { curve, vertex, d, point: [q[0], q[1]] };
  }));
  return best;
}

const subBulge = (el, t0, t1) => (el.kind === 'arc' ? Math.tan(el.sweep * (t1 - t0) / 4) : 0);

/**
 * Trim: take away the stretch of a curve under `hit` ({curve, element, t} from nearest()), from the crossing before
 * it to the crossing after it. With no crossing on that stretch the whole stretch goes (a whole circle, a whole
 * side). Returns the new list of curves.
 */
export function trim(curves, hit) {
  const target = curves[hit.curve], els = elements(target), el = els[hit.element];
  const out = curves.filter((_, i) => i !== hit.curve), put = (c) => { if (c) out.splice(hit.curve + put.n++, 0, c); };
  put.n = 0;
  // every place another element crosses this one
  const cuts = [];
  curves.forEach((c, ci) => elements(c).forEach((other, ei) => {
    if (ci === hit.curve && ei === hit.element) return;
    for (const p of meet(el, other)) cuts.push(el.full ? turn(Math.atan2(p[1] - el.c[1], p[0] - el.c[0])) / TAU : paramOf(el, p));
  }));

  if (el.full) {      // a circle: what is left is the arc from the crossing after the click round to the one before it
    const ts = [...new Set(cuts.map((t) => r6(turn(t * TAU) / TAU)))].sort((a, b) => a - b);
    if (ts.length < 2) return out;
    const after = ts.find((t) => t > hit.t) ?? ts[0], before = [...ts].reverse().find((t) => t < hit.t) ?? ts[ts.length - 1];
    const sweep = turn((before - after) * TAU) || TAU;
    put({ type: 'polyline', closed: false, points: [[...pointAt(el, after).map(r3), r6(Math.tan(sweep / 4))], pointAt(el, before).map(r3)] });
    return out;
  }

  const inside = cuts.filter((t) => t > 1e-6 && t < 1 - 1e-6);
  const ta = Math.max(0, ...inside.filter((t) => t < hit.t)), tb = Math.min(1, ...inside.filter((t) => t > hit.t));
  // an ellipse is cut as the many short lines it is drawn with
  const path = toPath(target) ?? { points: flatten(target).slice(0, -1).map((p) => [p[0], p[1], 0]), closed: true };
  const n = path.points.length, i = hit.element, P = path.points;
  const A = ta > 1e-6 ? [...pointAt(el, ta), 0] : null;                        // where the stretch before the gap ends
  const B = tb < 1 - 1e-6 ? [...pointAt(el, tb), subBulge(el, tb, 1)] : null;  // where the stretch after it begins
  const start = [P[i][0], P[i][1], A ? subBulge(el, 0, ta) : 0];
  if (path.closed) {
    const ring = [];
    if (B) ring.push(B);
    for (let k = 1; k < n; k++) ring.push([...P[(i + k) % n]]);
    ring.push(start);
    if (A) ring.push(A);
    put(ring.length >= 2 ? fromPath({ points: ring, closed: false }) : null);
  } else {
    const head = [...P.slice(0, i).map((p) => [...p]), start, ...(A ? [A] : [])];
    const tail = [...(B ? [B] : []), ...P.slice(i + 1).map((p) => [...p])];
    put(head.length >= 2 ? fromPath({ points: head, closed: false }) : null);
    put(tail.length >= 2 ? fromPath({ points: tail, closed: false }) : null);
  }
  return out;
}

/**
 * Fillet: round a corner of a rectangle or a polyline with radius r. `corner` is {curve, vertex} from
 * nearestCorner(). Returns {curves}, or {error} when it cannot be done.
 */
export function fillet(curves, corner, r) {
  const path = toPath(curves[corner.curve]);
  if (!path || !(r > 0)) return { error: 'a fillet rounds a corner of a rectangle or a line' };
  const n = path.points.length, k = corner.vertex;
  if (!path.closed && (k === 0 || k === n - 1)) return { error: 'that is an end, not a corner' };
  const prev = path.points[(k - 1 + n) % n], here = path.points[k], next = path.points[(k + 1) % n];
  if (Math.abs(prev[2]) > 1e-9 || Math.abs(here[2]) > 1e-9) return { error: 'only a corner between two straight lines can be rounded' };
  const a = sub(prev, here), b = sub(next, here), la = Math.hypot(...a), lb = Math.hypot(...b);
  const angle = Math.acos(Math.max(-1, Math.min(1, dot(a, b) / (la * lb))));
  if (angle < 1e-6 || Math.PI - angle < 1e-6) return { error: 'there is no corner here: the lines run straight on' };
  const back = r / Math.tan(angle / 2);      // how far from the corner the round begins
  if (back > la - 1e-9 || back > lb - 1e-9) return { error: `too large for this corner: at most ${r3(Math.min(la, lb) * Math.tan(angle / 2))} mm fits` };
  const left = cross(sub(here, prev), sub(next, here)) > 0;
  const t1 = add(here, mul(a, back / la)), t2 = add(here, mul(b, back / lb));
  const points = [...path.points.slice(0, k), [...t1, Math.tan((Math.PI - angle) / 4) * (left ? 1 : -1)], [...t2, 0], ...path.points.slice(k + 1)];
  const out = [...curves];
  out[corner.curve] = fromPath({ points, closed: path.closed });
  return { curves: out };
}

/**
 * Offset: a copy of a curve, d millimetres away from it, on the side where `towards` is. Circles, ellipses and
 * rectangles stay what they are (an ellipse only nearly: its true offset is not an ellipse); a polyline keeps sharp
 * corners, and its arcs become short lines. Returns the new curve, or null when nothing is left of it.
 */
export function offset(curve, d, towards) {
  if (!(d > 0)) return null;
  if (curve.type === 'circle') {
    const r = curve.r + (dist(towards, curve.center) > curve.r ? d : -d);
    return r > 1e-6 ? { type: 'circle', center: curve.center, r: r3(r) } : null;
  }
  if (curve.type === 'ellipse') {
    const k = -(curve.rotation ?? 0) * Math.PI / 180, q = sub(towards, curve.center);
    const x = q[0] * Math.cos(k) - q[1] * Math.sin(k), y = q[0] * Math.sin(k) + q[1] * Math.cos(k);
    const s = (x / curve.rx) ** 2 + (y / curve.ry) ** 2 > 1 ? d : -d;
    return curve.rx + s > 1e-6 && curve.ry + s > 1e-6 ? { ...curve, rx: r3(curve.rx + s), ry: r3(curve.ry + s) } : null;
  }
  if (curve.type === 'rect') {
    const [u, v] = curve.at, [w, h] = curve.size;
    const s = towards[0] < u || towards[0] > u + w || towards[1] < v || towards[1] > v + h ? d : -d;
    return w + 2 * s > 1e-6 && h + 2 * s > 1e-6 ? { type: 'rect', at: [r3(u - s), r3(v - s)], size: [r3(w + 2 * s), r3(h + 2 * s)] } : null;
  }
  const closed = isClosed(curve), pts = flatten(curve);
  const run = closed ? pts.slice(0, -1) : pts, n = run.length;
  if (n < 2) return null;
  // which side: left or right of the stretch nearest to `towards`
  const near = nearest([{ type: 'polyline', points: run, closed }], towards);
  const a = run[near.element], b = run[(near.element + 1) % n];
  const side = cross(sub(b, a), sub(towards, a)) >= 0 ? 1 : -1;
  const lines = [];
  for (let i = 0; i < (closed ? n : n - 1); i++) {
    const p = run[i], q = run[(i + 1) % n], len = dist(p, q);
    if (len < 1e-9) continue;
    const shift = mul([-(q[1] - p[1]) / len, (q[0] - p[0]) / len], d * side);
    lines.push({ a: add(p, shift), b: add(q, shift) });
  }
  if (!lines.length) return null;
  const join = (l1, l2) => {      // where two shifted lines meet; if they run the same way, where the first ends
    const d1 = sub(l1.b, l1.a), d2 = sub(l2.b, l2.a), den = cross(d1, d2);
    return Math.abs(den) < 1e-9 ? l1.b : add(l1.a, mul(d1, cross(sub(l2.a, l1.a), d2) / den));
  };
  const out = [];
  if (!closed) out.push(lines[0].a);
  for (let i = 0; i < lines.length - (closed ? 0 : 1); i++) out.push(join(lines[i], lines[(i + 1) % lines.length]));
  if (!closed) out.push(lines[lines.length - 1].b); else out.unshift(out.pop());
  return { type: 'polyline', closed, points: out.map((p) => [r3(p[0]), r3(p[1])]) };
}

/**
 * The oval through three clicks, as in Adam Designer: the first two are the ends of one whole axis, at any angle;
 * the third sets how far the other axis reaches from that line. null while it has no size.
 */
export function ovalThrough(a, b, c) {
  const axis = sub(b, a), len = Math.hypot(...axis);
  if (len < 1e-6) return null;
  const ry = Math.abs(cross(axis, sub(c, a))) / len;
  if (ry < 1e-6) return null;
  return { type: 'ellipse', center: mul(add(a, b), 0.5).map(r3), rx: r3(len / 2), ry: r3(ry), rotation: r3(Math.atan2(axis[1], axis[0]) * 180 / Math.PI) };
}

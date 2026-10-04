// Measuring: the shortest distance between two things, and the angle between them.
//
// A thing is whatever can be selected, reduced to what it is made of: points, straight segments (an edge, as the
// preview draws it) and triangles (a face, as the preview draws it). Flat faces and straight edges are exact;
// curved ones are as fine as the preview mesh (0.05 mm). No DOM and no three.js here: plain arrays, so it runs in
// node for its tests.

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const clamp = (v) => Math.max(0, Math.min(1, v));

/** The nearest point of segment ab to p. */
export function onSegment(p, a, b) {
  const ab = sub(b, a), l = dot(ab, ab);
  return add(a, mul(ab, l ? clamp(dot(sub(p, a), ab) / l) : 0));
}

/** The nearest point of triangle abc to p (Ericson, Real-Time Collision Detection 5.1.5). */
export function onTriangle(p, a, b, c) {
  const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return add(a, mul(ab, d1 / (d1 - d3)));
  const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return add(a, mul(ac, d2 / (d2 - d6)));
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return add(b, mul(sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))));
  const k = 1 / (va + vb + vc);
  return add(a, add(mul(ab, vb * k), mul(ac, vc * k)));
}

/** The nearest points of two segments: [on the first, on the second] (Ericson 5.1.9). */
export function betweenSegments(p1, q1, p2, q2) {
  const d1 = sub(q1, p1), d2 = sub(q2, p2), r = sub(p1, p2);
  const a = dot(d1, d1), e = dot(d2, d2), f = dot(d2, r);
  let s, t;
  if (a <= 1e-12 && e <= 1e-12) return [p1, p2];
  if (a <= 1e-12) { s = 0; t = clamp(f / e); } else {
    const c = dot(d1, r);
    if (e <= 1e-12) { t = 0; s = clamp(-c / a); } else {
      const b = dot(d1, d2), den = a * e - b * b;
      s = den > 1e-12 ? clamp((b * f - c * e) / den) : 0;
      t = (b * s + f) / e;
      if (t < 0) { t = 0; s = clamp(-c / a); } else if (t > 1) { t = 1; s = clamp((b - c) / a); }
    }
  }
  return [add(p1, mul(d1, s)), add(p2, mul(d2, t))];
}

/** Where segment pq passes through triangle abc, or null (Möller–Trumbore). */
export function throughTriangle(p, q, a, b, c) {
  const d = sub(q, p), e1 = sub(b, a), e2 = sub(c, a), h = cross(d, e2), det = dot(e1, h);
  if (Math.abs(det) < 1e-12) return null;
  const s = sub(p, a), u = dot(s, h) / det;
  if (u < 0 || u > 1) return null;
  const qv = cross(s, e1), v = dot(d, qv) / det;
  if (v < 0 || u + v > 1) return null;
  const t = dot(e2, qv) / det;
  return t >= 0 && t <= 1 ? add(p, mul(d, t)) : null;
}

/** The nearest points of a segment and a triangle: [on the segment, on the triangle]. */
export function segmentTriangle(p, q, a, b, c) {
  const x = throughTriangle(p, q, a, b, c);
  if (x) return [x, x];
  let best = [p, onTriangle(p, a, b, c)];
  const other = [q, onTriangle(q, a, b, c)];
  if (dist(...other) < dist(...best)) best = other;
  for (const [u, v] of [[a, b], [b, c], [c, a]]) {
    const pair = betweenSegments(p, q, u, v);
    if (dist(...pair) < dist(...best)) best = pair;
  }
  return best;
}

const LIMIT = 400000;   // pairs looked at exactly; beyond that, corners only, and the answer is marked "about"
const thin = (list, n) => (list.length <= n ? list : list.filter((_, i) => i % Math.ceil(list.length / n) === 0));

/**
 * The shortest way from thing A to thing B. A thing is {points: [[x, y, z]], segments: [[a, b]], triangles: [[a, b, c]]}.
 * Returns {d, a, b, about}: the distance, the point on A, the point on B, and whether it is only approximate.
 */
export function closest(A, B) {
  let best = { d: Infinity, a: null, b: null, about: false };
  const take = (a, b) => { const d = dist(a, b); if (d < best.d) best = { ...best, d, a, b }; };
  const P = (t) => t.points ?? [], S = (t) => t.segments ?? [], T = (t) => t.triangles ?? [];
  const work = S(A).length * S(B).length + S(A).length * T(B).length + T(A).length * S(B).length + 6 * T(A).length * T(B).length;
  if (work > LIMIT) {
    // too much to do properly in a browser: the corners of each against the other, thinned out
    const corners = (t) => thin([...P(t), ...S(t).flat(), ...T(t).flat()], 1500);
    const ca = corners(A), cb = corners(B);
    for (const p of ca) for (const q of cb) take(p, q);
    for (const p of ca) for (const t of thin(T(B), 3000)) take(p, onTriangle(p, ...t));
    for (const q of cb) for (const t of thin(T(A), 3000)) take(onTriangle(q, ...t), q);
    return { ...best, about: true };
  }
  for (const p of P(A)) {
    for (const q of P(B)) take(p, q);
    for (const s of S(B)) take(p, onSegment(p, ...s));
    for (const t of T(B)) take(p, onTriangle(p, ...t));
  }
  for (const q of P(B)) {
    for (const s of S(A)) take(onSegment(q, ...s), q);
    for (const t of T(A)) take(onTriangle(q, ...t), q);
  }
  for (const s of S(A)) {
    for (const u of S(B)) take(...betweenSegments(...s, ...u));
    for (const t of T(B)) take(...segmentTriangle(...s, ...t));
  }
  for (const t of T(A)) {
    for (const u of S(B)) { const [x, y] = segmentTriangle(...u, ...t); take(y, x); }
    for (const u of T(B)) {
      for (const [p, q] of [[t[0], t[1]], [t[1], t[2]], [t[2], t[0]]]) take(...segmentTriangle(p, q, ...u));
      for (const [p, q] of [[u[0], u[1]], [u[1], u[2]], [u[2], u[0]]]) { const [x, y] = segmentTriangle(p, q, ...t); take(y, x); }
    }
  }
  return best;
}

/**
 * The angle in degrees between two things that have a direction: {line: [x, y, z]} (a straight edge, the axis of a
 * round face) or {normal: [x, y, z]} (a flat face). Two lines or two faces: 0 when parallel, 90 when square.
 * A line and a face: 0 when the line lies in the face, 90 when it stands on it. null when either has no direction.
 */
export function angle(a, b) {
  const da = a?.line ?? a?.normal, db = b?.line ?? b?.normal;
  if (!da || !db) return null;
  const c = Math.min(1, Math.abs(dot(da, db)) / (Math.hypot(...da) * Math.hypot(...db)));
  const between = Math.acos(c) * 180 / Math.PI;
  return (a.line && b.normal) || (a.normal && b.line) ? 90 - between : between;
}

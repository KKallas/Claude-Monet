// Joints in the browser: where every part is at a pose, as monet/joints.py works it out on the server. The model is
// the build's `motion` (bodies, joints with their axes, the order to place them in); matrices are plain row-major
// arrays of 16, as numpy has them, so this runs and is tested without three.js.

export const IDENTITY = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

export function multiply(a, b) {
  const out = new Array(16).fill(0);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) out[i * 4 + j] += a[i * 4 + k] * b[k * 4 + j];
  return out;
}

export function apply(m, [x, y, z]) {
  return [m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11]];
}

// a turn of `degrees` about the line through origin along the unit vector d, right hand
export function rotation(origin, [x, y, z], degrees) {
  const a = degrees * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), C = 1 - c;
  const R = [[c + x * x * C, x * y * C - z * s, x * z * C + y * s], [y * x * C + z * s, c + y * y * C, y * z * C - x * s], [z * x * C - y * s, z * y * C + x * s, c + z * z * C]];
  const t = [0, 1, 2].map((i) => origin[i] - (R[i][0] * origin[0] + R[i][1] * origin[1] + R[i][2] * origin[2]));
  return [...R[0], t[0], ...R[1], t[1], ...R[2], t[2], 0, 0, 0, 1];
}

const moves = (row) => row.kind !== 'rigid' && row.resolved;

/** Every joint's value: the drivers' as given, the followers' worked out from them, the rest 0. */
export function values(model, given = {}) {
  const out = {};
  for (const [name, row] of Object.entries(model.joints)) if (!moves(row) || !row.follows) out[name] = moves(row) ? Number(given[name] ?? 0) : 0;
  for (const name of model.follow_order) {
    const row = model.joints[name];
    if (row.follows) out[name] = Object.entries(row.follows).reduce((sum, [k, f]) => sum + f * (out[k] ?? 0), 0);
  }
  return out;
}

/** {body: matrix} at these joint values; free bodies where `free` puts them. */
export function frames(model, given = {}, free = {}) {
  const v = values(model, given), out = {};
  for (const b of Object.keys(model.bodies)) out[b] = free[b] ? [...free[b]] : IDENTITY();
  for (const name of model.tree) {
    const row = model.joints[name];
    let T = IDENTITY();
    if (row.kind === 'revolute') T = rotation(row.origin, row.dir, v[name]);
    else if (row.kind === 'slider') { T[3] = row.dir[0] * v[name]; T[7] = row.dir[1] * v[name]; T[11] = row.dir[2] * v[name]; }
    out[row.moves] = multiply(out[row.on], T);
  }
  return out;
}

export function bodyOf(model) {
  const out = {};
  for (const [b, parts] of Object.entries(model.bodies)) for (const p of parts) out[p] = b;
  return out;
}

/** The joints moved by hand: they move, they are found, they follow nothing. */
export const drivers = (model) => Object.entries(model.joints).filter(([, r]) => moves(r) && !r.follows).map(([n]) => n);

/** What a drag on this body moves: its own joint if moved by hand; a follower's first driver; up the tree past
 *  rigid joints. {joint} or {free: true} or null (it is held: the ground, or hung on the ground rigidly). */
export function handle(model, body) {
  const by = Object.fromEntries(model.tree.map((n) => [model.joints[n].moves, n]));
  for (let b = body, k = 0; b != null && k < 64; k++) {
    const name = by[b];
    if (name == null) return model.free.includes(b) ? { free: true, body: b } : null;
    const row = model.joints[name];
    if (row.kind !== 'rigid') {
      if (!row.follows) return { joint: name };
      const lead = Object.entries(row.follows).sort((a, c) => Math.abs(c[1]) - Math.abs(a[1]))[0];
      return lead && model.joints[lead[0]] && !model.joints[lead[0]].follows ? { joint: lead[0] } : null;
    }
    b = row.on;
  }
  return null;
}

/** The range a driver may be moved in, as the slider shows it. */
export function span(row) {
  if (row.range) return row.range;
  return row.kind === 'revolute' ? [-180, 180] : [-100, 100];
}

/** Where a tip is with the joints at these values. */
export function tipAt(model, tip, given = {}) {
  const t = model.tips[tip];
  return apply(frames(model, given)[t.body], t.at);
}

// x for A x = b, A 3 x 3
function solve3(A, b) {
  const m = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < 3; c++) {
    let p = c;
    for (let r = c + 1; r < 3; r++) if (Math.abs(m[r][c]) > Math.abs(m[p][c])) p = r;
    [m[c], m[p]] = [m[p], m[c]];
    for (let r = 0; r < 3; r++) {
      if (r === c) continue;
      const f = m[r][c] / m[c][c];
      for (let k = c; k < 4; k++) m[r][k] -= f * m[c][k];
    }
  }
  return [0, 1, 2].map((i) => m[i][3] / m[i][i]);
}

/** Inverse kinematics, as solve() in monet/joints.py: the values of the joints moved by hand (and not locked)
 *  that put the tip at target, from the pose it is in, never leaving a joint's range. Out of reach, it stops
 *  where the tip comes nearest; `off` says how far that is. {values, tip, off, reached} */
export function solve(model, tip, target, start = {}, iterations = 200) {
  const names = drivers(model).filter((n) => !model.joints[n].locked);
  const spans = names.map((n) => model.joints[n].range ?? (model.joints[n].kind === 'revolute' ? [-180, 180] : [-1e6, 1e6]));
  const clamp = (x) => x.map((v, i) => Math.min(spans[i][1], Math.max(spans[i][0], v)));
  let q = clamp(names.map((n) => Number(start[n] ?? 0)));
  const at = (x) => tipAt(model, tip, { ...start, ...Object.fromEntries(names.map((n, i) => [n, x[i]])) });
  const norm = (v) => Math.hypot(...v);
  let best = null;
  for (let k = 0; k < iterations; k++) {
    const here = at(q), e = target.map((v, i) => v - here[i]);
    if (!best || norm(e) < best[1]) best = [[...q], norm(e)];
    if (norm(e) < 1e-4) break;
    const J = q.map((_, i) => { const d = [...q]; d[i] += 1e-3; const p = at(d); return p.map((v, r) => (v - here[r]) / 1e-3); });     // columns
    const JJt = [0, 1, 2].map((r) => [0, 1, 2].map((c) => J.reduce((s, col) => s + col[r] * col[c], 0) + (r === c ? 1 : 0)));
    const y = solve3(JJt, e);
    let step = J.map((col) => col[0] * y[0] + col[1] * y[1] + col[2] * y[2]);
    const big = Math.max(...step.map(Math.abs));
    if (big > 10) step = step.map((v) => v * 10 / big);      // at most 10 degrees (or mm) a step
    q = clamp(q.map((v, i) => v + step[i]));
  }
  const [qb, off] = best;
  const values = Object.fromEntries(drivers(model).map((n) => [n, Number(start[n] ?? 0)]));
  names.forEach((n, i) => { values[n] = qb[i]; });
  return { values, tip: at(qb), off, reached: off <= 0.05 };
}

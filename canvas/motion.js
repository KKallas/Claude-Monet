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

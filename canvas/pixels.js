// Pixels (issue #10): a lamp of many small white shells, each lit from the LEDs under it, each its own colour. What a
// LIGHTS `pixels` light names, as the build found it (faces.json `pixels`: each pixel's faces, box and LEDs), shaded in
// the parts' own materials:
//  - a pixel is brightest over its LEDs and its walls are dimmer (from each LED's distance, direction and depth under the
//    shell, normalised by the pixel's own 97th percentile), and driven hard its colour runs to white;
//  - the surfaces between the pixels are lit by them (light from under a rim lands on the white beside it), fading
//    within `spill_mm` of the pixel's box: a grid holds the four nearest pixels of every cell, read per fragment;
//  - patterns (the animation's `patterns`, lights.PATTERNS on the server) set every pixel's colour at a time t:
//    solid, chase (white-cored pulses walking the pixels), wave, scan, rainbow, sparkle, off.
// After the lamp agent's offline renderer (tools/lightshow.py in the lamp project), which this replaces.
import * as THREE from 'three';

const W = 1024;      // texels to a row of the data textures
const MAX_LEDS = 24;      // a pixel's LEDs the shader adds up (the nearest are the ones that count)

// ---- a little seeded randomness: the same pattern every time it plays, here and in a video ----------------------------
function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const hex = (h, fallback) => new THREE.Color(h ?? fallback);      // three's colour management: the working (linear) colour
function hsv(h, s, v, out) {
  h = ((h % 1) + 1) % 1 * 6;
  const i = Math.floor(h), f = h - i, p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
  return out.setRGB(r, g, b, THREE.SRGBColorSpace);
}
function texture(n, texels) {
  const rows = Math.max(1, Math.ceil((n * texels) / W));
  const t = new THREE.DataTexture(new Float32Array(W * rows * 4), W, rows, THREE.RGBAFormat, THREE.FloatType);
  t.needsUpdate = true;
  return t;
}

export function createPixels() {
  let pixels = [], lights = [], leds = 0, grid = null, active = false;
  const tex = { pix: texture(1, 3), led: texture(1, 2), col: texture(1, 1), grid: texture(1, 1) };
  const uniforms = {
    uPixTex: { value: tex.pix }, uLedTex: { value: tex.led }, uColTex: { value: tex.col }, uGridTex: { value: tex.grid },
    uGridMin: { value: new THREE.Vector3() }, uGridN: { value: new THREE.Vector3(1, 1, 1) }, uCell: { value: 1 },
    uSpill: { value: 8 }, uOn: { value: 0 }, uGain: { value: 2.1 }, uSpillGain: { value: 0.8 },
  };
  const walks = new Map();      // per light: the chase's walks, made once

  /** The pixels of the `pixels` lights in `list`, from faces.json (`described`) and the parts on show. */
  function set(list, described, parts) {
    lights = (list ?? []).filter((L) => L.kind === 'pixels');
    pixels = []; walks.clear(); active = false;
    if (!lights.length || !parts?.length) return;
    const faces = described?.faces ?? [], byName = new Map(parts.map((p) => [p.name, p]));
    const geom = parts.find((p) => p.mesh)?.mesh.geometry;
    if (!geom) return;
    const index = geom.index.array, position = geom.attributes.position.array, normal = geom.attributes.normal?.array;
    const attr = new Float32Array(position.length / 3);
    for (const L of lights) {
      let found = described?.pixels?.[L.name];
      if (!found) {      // built before the light was a pixels light: every part it names one pixel, without LEDs
        const m = matcher(L.glow);
        found = parts.filter((p) => m(p.name) && p.tris).map((p) => ({ part: p.name, tris: [p.tris], bbox: p.bbox, leds: [] }));
      }
      for (const q of found) {
        if (!byName.has(q.part) && !q.tris) continue;
        const tris = q.tris ?? q.faces.flatMap(([s, c]) => Array.from({ length: c }, (_, k) => faces[s + k]?.tris).filter(Boolean));
        const verts = new Set();
        for (const [t0, tn] of tris) for (let t = t0; t < t0 + tn; t++) for (let k = 0; k < 3; k++) verts.add(index[t * 3 + k]);
        if (!verts.size) continue;
        const b = q.bbox;
        pixels.push({ light: L.name, part: q.part, verts: [...verts], lo: [b[0], b[1], b[2]], hi: [b[3], b[4], b[5]],
          c: [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2], leds: (q.leds ?? []).slice(0) });
      }
    }
    if (!pixels.length) return;
    // which way a pixel looks: its LEDs' normals, else away from the middle of all of them
    const mid = [0, 1, 2].map((k) => pixels.reduce((s, p) => s + p.c[k], 0) / pixels.length);
    for (const p of pixels) {
      let n = p.leds.reduce((s, l) => [s[0] + l[3], s[1] + l[4], s[2] + l[5]], [0, 0, 0]);
      if (Math.hypot(...n) < 1e-6) n = p.c.map((x, k) => x - mid[k]);
      const len = Math.hypot(...n) || 1;
      p.n = n.map((x) => x / len);
      // a pixel's LEDs: the nearest to its middle first, at most MAX_LEDS
      p.leds.sort((a, b) => Math.hypot(a[0] - p.c[0], a[1] - p.c[1], a[2] - p.c[2]) - Math.hypot(b[0] - p.c[0], b[1] - p.c[1], b[2] - p.c[2]));
      p.leds = p.leds.slice(0, MAX_LEDS);
    }
    // the pixel's id on each of its vertices (0: no pixel), on every part's geometry (they share their attributes)
    pixels.forEach((p, i) => { for (const v of p.verts) attr[v] = i + 1; });
    const at = new THREE.BufferAttribute(attr, 1);
    for (const p of parts) p.mesh?.geometry.setAttribute('pixel', at);
    // brightness from the LEDs at every vertex, and the pixel's 97th percentile of it: what full brightness is
    for (const p of pixels) {
      if (!p.leds.length) { p.norm = 0; continue; }
      const e = p.verts.map((v) => led(p.leds, position[v * 3], position[v * 3 + 1], position[v * 3 + 2])).sort((a, b) => a - b);
      p.norm = e[Math.min(e.length - 1, Math.floor(e.length * 0.97))] || 1;
    }
    upload(normal);
    active = true;
  }
  function led(list, x, y, z) {
    let e = 0;
    for (const l of list) {
      const dx = x - l[0], dy = y - l[1], dz = z - l[2], d2 = dx * dx + dy * dy + dz * dz + 4, has = Math.abs(l[3]) + Math.abs(l[4]) + Math.abs(l[5]) > 0;
      const cs = has ? Math.min(1, Math.max(0, (dx * l[3] + dy * l[4] + dz * l[5]) / Math.sqrt(d2))) : 1;
      e += (has ? 0.3 + 0.7 * cs : 1) * (l[6] * l[6]) / d2;
    }
    return e;
  }
  function upload() {
    const N = pixels.length;
    leds = pixels.reduce((s, p) => s + p.leds.length, 0);
    for (const k of ['pix', 'led', 'col', 'grid']) tex[k].dispose();
    tex.pix = texture(N, 3); tex.led = texture(Math.max(1, leds), 2); tex.col = texture(N, 1);
    const P = tex.pix.image.data, Ld = tex.led.image.data;
    let s = 0;
    pixels.forEach((p, i) => {
      P.set([...p.lo, p.norm, ...p.hi, s, ...p.n, p.leds.length], i * 12);
      for (const l of p.leds) {
        const has = Math.abs(l[3]) + Math.abs(l[4]) + Math.abs(l[5]) > 0 ? 1 : 0;
        Ld.set([l[0], l[1], l[2], l[6], l[3], l[4], l[5], has], s * 8);
        s++;
      }
    });
    // the grid of the four nearest pixels to each cell, for the light between them
    const spill = Math.max(1, ...lights.map((L) => L.spill_mm ?? 8)), reach = spill * 3;
    const lo = [0, 1, 2].map((k) => Math.min(...pixels.map((p) => p.lo[k])) - reach), hi = [0, 1, 2].map((k) => Math.max(...pixels.map((p) => p.hi[k])) + reach);
    const ext = Math.max(...hi.map((h, k) => h - lo[k]));
    const cell = Math.max(spill * 1.25, ext / 72);
    const n = lo.map((l, k) => Math.max(1, Math.ceil((hi[k] - l) / cell)));
    const cells = n[0] * n[1] * n[2], best = new Float32Array(cells * 4), dist = new Float32Array(cells * 4).fill(Infinity);
    const half = cell * Math.sqrt(3) / 2;
    pixels.forEach((p, i) => {
      const a = [0, 1, 2].map((k) => Math.max(0, Math.floor((p.lo[k] - reach - half - lo[k]) / cell)));
      const b = [0, 1, 2].map((k) => Math.min(n[k] - 1, Math.floor((p.hi[k] + reach + half - lo[k]) / cell)));
      for (let z = a[2]; z <= b[2]; z++) for (let y = a[1]; y <= b[1]; y++) for (let x = a[0]; x <= b[0]; x++) {
        const c = [lo[0] + (x + 0.5) * cell, lo[1] + (y + 0.5) * cell, lo[2] + (z + 0.5) * cell];
        const d = Math.hypot(...[0, 1, 2].map((k) => Math.max(p.lo[k] - c[k], 0, c[k] - p.hi[k])));
        if (d > reach + half) continue;
        const o = (x + n[0] * (y + n[1] * z)) * 4;
        let w = -1;
        for (let k = 0; k < 4; k++) if (d < dist[o + k] && (w < 0 || dist[o + k] > dist[o + w])) w = k;
        if (w >= 0) { dist[o + w] = d; best[o + w] = i + 1; }
      }
    });
    tex.grid = texture(cells, 1);
    tex.grid.image.data.set(best);
    Object.assign(uniforms.uPixTex, { value: tex.pix }); uniforms.uLedTex.value = tex.led; uniforms.uColTex.value = tex.col; uniforms.uGridTex.value = tex.grid;
    uniforms.uGridMin.value.set(...lo); uniforms.uGridN.value.set(...n); uniforms.uCell.value = cell; uniforms.uSpill.value = spill;
    grid = { lo, n, cell };
  }

  // ---- patterns ------------------------------------------------------------------------------------------------------
  const tmp = new THREE.Color(), base = new THREE.Color(), core = new THREE.Color(), shown = new THREE.Color(), hsl = { h: 0, s: 0, l: 0 };
  let meta = null;      // what the patterns need of the pixels: centres, neighbours, a phase each, the size of it all
  function prepare() {
    if (meta?.of === pixels) return meta;
    const N = pixels.length, C = pixels.map((p) => p.c);
    const lo = [0, 1, 2].map((k) => Math.min(...C.map((c) => c[k]))), hi = [0, 1, 2].map((k) => Math.max(...C.map((c) => c[k])));
    const mid = lo.map((l, k) => (l + hi[k]) / 2), ext = Math.max(1, ...hi.map((h, k) => h - lo[k]));
    const nb = C.map((c, i) => C.map((d, j) => [j, Math.hypot(c[0] - d[0], c[1] - d[1], c[2] - d[2])]).filter(([j]) => j !== i).sort((a, b) => a[1] - b[1]).slice(0, 6));
    const spacing = nb.map((x) => x[0]?.[1] ?? ext).sort((a, b) => a - b)[Math.floor(N / 2)] || ext / 10;
    const r = rng(5), phase = C.map(() => r());
    meta = { of: pixels, C, lo, hi, mid, ext, nb: nb.map((x) => x.map(([j]) => j)), spacing, phase };
    return meta;
  }
  function walk(m, start, steps, seed) {
    const r = rng(seed), path = [start];
    let dir = null;
    for (let s = 0; s < steps; s++) {
      const cur = path[path.length - 1], recent = new Set(path.slice(-12));
      let best = -1, score = -Infinity;
      for (const j of m.nb[cur]) {
        if (recent.has(j)) continue;
        const v = m.C[j].map((x, k) => x - m.C[cur][k]), len = Math.hypot(...v) || 1;
        const sc = (dir ? 1.5 * (v[0] * dir[0] + v[1] * dir[1] + v[2] * dir[2]) / len : 0) + r();
        if (sc > score) { score = sc; best = j; }
      }
      if (best < 0) best = m.nb[cur][Math.floor(r() * m.nb[cur].length)] ?? cur;
      const v = m.C[best].map((x, k) => x - m.C[cur][k]), len = Math.hypot(...v) || 1;
      dir = v.map((x) => x / len);
      path.push(best);
    }
    return path;
  }
  function walksOf(light, idx, pulses) {
    const key = `${light}:${pulses}`;
    if (!walks.has(key)) {
      const m = prepare(), r = rng(11), starts = [idx[Math.floor(r() * idx.length)]];
      while (starts.length < pulses) {      // the next start: the pixel farthest from those already taken
        let far = idx[0], fd = -1;
        for (const i of idx) { const d = Math.min(...starts.map((s) => Math.hypot(...m.C[i].map((x, k) => x - m.C[s][k])))); if (d > fd) { fd = d; far = i; } }
        starts.push(far);
      }
      walks.set(key, starts.map((s, w) => walk(m, s, 2400, 11 + w)));
    }
    return walks.get(key);
  }

  /** Every pixel's colour now: `level(light)` 0…1, `patternOf(light)` → {spec, t} or null (the light's own colour). */
  function update(level, patternOf) {
    if (!active) return;
    const m = prepare(), out = tex.col.image.data;
    const groups = new Map();
    pixels.forEach((p, i) => { if (!groups.has(p.light)) groups.set(p.light, []); groups.get(p.light).push(i); });
    for (const L of lights) {
      const idx = groups.get(L.name) ?? [], lv = level(L.name), got = patternOf?.(L.name), spec = got?.spec ?? { kind: 'solid' }, t = got?.t ?? 0;
      base.copy(hex(spec.color, L.color)); core.copy(hex(spec.core, '#ffffff'));
      base.getHSL(hsl, THREE.SRGBColorSpace);
      const sp = spec.speed ?? 1;
      if (spec.kind === 'chase') {
        const pulses = spec.pulses ?? 6, speed = spec.speed ?? 9, trail = spec.trail ?? 8, ws = walksOf(L.name, idx, pulses);
        const sc = m.spacing * 0.6, sg = m.spacing * 1.5, coreV = new Float32Array(pixels.length), glowV = new Float32Array(pixels.length);
        ws.forEach((path, w) => {
          const x = ((t + w * 0.37) * speed) % (path.length - 1), i0 = Math.floor(x), f = x - i0;
          const a = m.C[path[i0]], b = m.C[path[i0 + 1]], head = a.map((v, k) => v * (1 - f) + b[k] * f);
          for (const i of idx) {
            const d = Math.hypot(m.C[i][0] - head[0], m.C[i][1] - head[1], m.C[i][2] - head[2]);
            coreV[i] = Math.max(coreV[i], Math.exp(-((d / sc) ** 2)));
            glowV[i] = Math.max(glowV[i], 0.45 * Math.exp(-((d / sg) ** 2)));
          }
          for (let k = 1; k <= trail && i0 - k >= 0; k++) glowV[path[i0 - k]] = Math.max(glowV[path[i0 - k]], 0.9 * Math.exp(-(k - 1 + f) / (trail / 3.6)));
        });
        for (const i of idx) {
          const v = Math.min(1, Math.max(coreV[i], glowV[i]) + 0.025), c = Math.min(1, coreV[i] ** 1.5);
          hsv(hsl.h - 0.04 * glowV[i], hsl.s * (1 - c), v * lv, tmp);
          if (spec.core) tmp.lerp(core.clone().multiplyScalar(v * lv), c);
          shown.copy(tmp).convertLinearToSRGB();
          out.set([shown.r, shown.g, shown.b], i * 4);
        }
        continue;
      }
      for (const i of idx) {
        const c = m.C[i];
        if (spec.kind === 'off') tmp.setRGB(0, 0, 0);
        else if (spec.kind === 'wave') {
          const k1 = 6.7 / m.ext, k2 = 4.6 / m.ext;
          const a = 0.5 + 0.5 * Math.sin((c[0] * 0.6 - c[1] * 0.5 + c[2] * 0.62) * k1 - t * 1.9 * sp);
          const b = 0.5 + 0.5 * Math.sin((-c[0] * 0.7 - c[1] * 0.2 - c[2] * 0.68) * k2 + t * 1.3 * sp + 1.7);
          const w = (a * b) ** 1.6, v = 0.16 + 0.84 * Math.min(1, w + 0.1 * (0.5 + 0.5 * Math.sin(2 * Math.PI * (m.phase[i] + t * 0.7))));
          hsv(hsl.h - 0.06 * w, hsl.s * (1 - 0.6 * w * w), v, tmp);      // brighter: toward cyan, its core toward white
        } else if (spec.kind === 'scan') {
          const ax = { x: 0, y: 1, z: 2 }[(spec.axis ?? '-z').replace('-', '')], down = (spec.axis ?? '-z').startsWith('-');
          const span = m.hi[ax] - m.lo[ax] + m.ext * 0.4, u = ((t * sp) % 2) / 2, at = down ? m.hi[ax] + m.ext * 0.2 - u * span : m.lo[ax] - m.ext * 0.2 + u * span;
          const v = Math.max(0.04, Math.exp(-(((c[ax] - at) / (m.ext * 0.1)) ** 2)));
          tmp.copy(base).multiplyScalar(v);
        } else if (spec.kind === 'rainbow') {
          const ang = Math.atan2(c[1] - m.mid[1], c[0] - m.mid[0]) / (2 * Math.PI);
          hsv(ang * 2 + t * 0.35 * sp, 0.9, 0.55 + 0.45 * Math.sin(2 * Math.PI * (m.phase[i] + t * 1.3 * sp)), tmp);
        } else if (spec.kind === 'sparkle') {
          const k = Math.floor(t * 9), rate = spec.rate ?? 0.06;
          tmp.copy(base).multiplyScalar(0.18);
          for (let back = 0; back < 4; back++) {
            const r = rng((1000 + k - back) * 7919 + i * 31)();
            if (r < rate) { const f = 0.85 ** (back * 2); tmp.lerp(core, f); }
          }
        } else tmp.copy(base);
        tmp.multiplyScalar(lv);
        shown.copy(tmp).convertLinearToSRGB();
        out.set([shown.r, shown.g, shown.b], i * 4);
      }
    }
    tex.col.needsUpdate = true;
  }

  /** The shading put into a part's material (its own shader hook kept): pixels and the light between them. */
  function patch(material) {
    if (!material || material.userData.pixels || !('emissive' in material)) return;
    material.userData.pixels = true;
    const before = material.onBeforeCompile, key = material.customProgramCacheKey;
    material.onBeforeCompile = (shader, r) => {
      before?.call(material, shader, r);
      Object.assign(shader.uniforms, uniforms);
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nattribute float pixel;\nvarying float vPixel;\nvarying vec3 vBuilt;\nvarying vec3 vBuiltNormal;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvPixel = pixel; vBuilt = position; vBuiltNormal = normal;');
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
uniform sampler2D uPixTex, uLedTex, uColTex, uGridTex;
uniform vec3 uGridMin, uGridN; uniform float uCell, uSpill, uOn, uGain, uSpillGain;
varying float vPixel; varying vec3 vBuilt; varying vec3 vBuiltNormal;
vec4 pxAt(sampler2D t, int i) { return texelFetch(t, ivec2(i % ${W}, i / ${W}), 0); }
vec3 pxSpill(vec3 p, int self, out float wsum) {
  ivec3 c = ivec3(floor((p - uGridMin) / uCell)), n = ivec3(uGridN);
  wsum = 0.0;
  if (any(lessThan(c, ivec3(0))) || any(greaterThanEqual(c, n))) return vec3(0.0);
  vec4 ids = pxAt(uGridTex, c.x + n.x * (c.y + n.y * c.z));
  vec3 acc = vec3(0.0);
  wsum = 0.0;
  for (int k = 0; k < 4; k++) {
    int id = int(ids[k] + 0.5) - 1;
    if (id < 0 || id == self) continue;
    vec3 lo = pxAt(uPixTex, id * 3).xyz, hi = pxAt(uPixTex, id * 3 + 1).xyz;
    float d = length(max(max(lo - p, p - hi), 0.0));
    float w = 1.7 * exp(-d / uSpill);
    acc += w * pxAt(uColTex, id).rgb;
    wsum += w;
  }
  return acc;
}`)
        .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
if (uOn > 0.5) {
  int pid = int(vPixel + 0.5) - 1;
  if (pid >= 0) {
    vec4 a = pxAt(uPixTex, pid * 3), b = pxAt(uPixTex, pid * 3 + 1), c = pxAt(uPixTex, pid * 3 + 2);
    int s = int(b.w + 0.5), n = int(c.w + 0.5);
    float e = 0.0;
    for (int i = 0; i < ${MAX_LEDS}; i++) {
      if (i >= n) break;
      vec4 L = pxAt(uLedTex, (s + i) * 2), N = pxAt(uLedTex, (s + i) * 2 + 1);
      vec3 D = vBuilt - L.xyz; float d2 = dot(D, D) + 4.0;
      float k = N.w > 0.5 ? 0.3 + 0.7 * clamp(dot(D, N.xyz) / sqrt(d2), 0.0, 1.0) : 1.0;
      e += k * L.w * L.w / d2;
    }
    float br = a.w > 0.0 ? 0.25 + 1.05 * pow(clamp(e / a.w, 0.0, 1.3), 1.1) : 0.9;
    if (abs(dot(normalize(vBuiltNormal), c.xyz)) < 0.5) br *= 0.75;      // its walls: dimmer than its face
    vec3 em = pxAt(uColTex, pid).rgb * br;      // as shown (sRGB), then into light below
    float m = max(em.r, max(em.g, em.b));
    em *= uGain / (1.0 + (uGain / 1.3 - 1.0) * m);      // dim ones lifted about uGain times (as a haze lifts them), full ones to 1.3
    em += max(0.0, max(em.r, max(em.g, em.b)) - 1.0) * 0.55;      // driven hard, an LED behind white plastic runs to white
    float ws;
    vec3 near = pxSpill(vBuilt, pid, ws);
    em += 0.5 * near / max(ws, 1.0) * uGain;      // its neighbours' light on its walls: half their average (the offline renderer's 0.5 of its blur)
    totalEmissiveRadiance += pow(min(em, vec3(1.4)), vec3(2.2));
    diffuseColor.rgb *= 0.55;      // a shell lit from inside: the room's light matters less on it
  } else {
    float ws;
    vec3 sp = pxSpill(vBuilt, -1, ws) * uGain * uSpillGain;      // white between them, lit from under their rims
    totalEmissiveRadiance += pow(min(sp, vec3(1.2)), vec3(2.2)) * diffuseColor.rgb;
  }
}`);
    };
    material.customProgramCacheKey = () => `${key ? key.call(material) : ''}|monet-pixels`;
    material.needsUpdate = true;
  }

  return {
    set, update, patch,
    get active() { return active; },
    get count() { return pixels.length; },
    /** Drawn or not (the lights on or off). */
    show(on) { uniforms.uOn.value = on && active ? 1 : 0; },
    uniforms,
  };
}

// a part's name against a MATERIALS-style pattern: caps_*, a|b
function matcher(pattern) {
  const alts = String(pattern).split('|').map((a) => a.trim()).filter(Boolean)
    .map((a) => new RegExp(`^${a.replace(/[.+^${}()[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`));
  return (name) => alts.some((r) => r.test(name));
}

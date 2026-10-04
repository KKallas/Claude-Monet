// The canvas: see the part, point at it, own the checks. The agent works through the other door (MCP);
// this page follows along by asking the project for its revision every two seconds.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { angle, closest } from './measure.js';
import { MATERIALS, STYLES, createLook } from './look.js';
import { basis, createSketcher, outline, strokes } from './sketch.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const wid = location.pathname.split('/')[2];
const root = `/w/${wid}/api`;
const PALETTE = ['#e26f28', '#2896c8', '#3caa5a', '#be46aa', '#d2aa1e', '#5a64dc', '#dc4650', '#14a096'];
const BASE = new THREE.Color('#b9c2d6'), PICK = new THREE.Color('#ffd23f');
// an assembly: every part in a colour of its own, quiet enough that a tag or a pointed-at face still stands out
const PARTS = ['#8fa8d6', '#d6a58f', '#9cc7a4', '#c9a3d0', '#d4c58a', '#8fc7cf', '#d49aa8', '#a9b0e0', '#b8cf94', '#e0b48a', '#9fb8b0', '#c7b1a0'];

async function api(path, method = 'GET', body) {
  const r = await fetch(root + path, { method, headers: body ? { 'content-type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `error ${r.status}`);
  return data;
}

// what is selected: any mix of points, lines, faces and objects, by their number in this build
const nothing = () => ({ vertex: new Set(), edge: new Set(), face: new Set(), part: new Set() });
const NAMES = { vertex: ['point', 'points'], edge: ['line', 'lines'], face: ['face', 'faces'], part: ['object', 'objects'] };

// what is on screen
const S = { state: null, project: null, proj: null, note: null, data: null, faces: [], parts: [], edges: [], points: [], hotPart: null, hidden: new Set(),
  room: 'part', lastPart: null, lastAssembly: null, sketchName: '', sketchRole: '',
  mode: 'face', sel: nothing(), boxTool: false, measuring: false, inspect: null, point: null, hot: null, tagSel: null, rev: null, compare: null, message: '', saveResult: null };

// ---- the 3D view -------------------------------------------------------------------------------------
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);   // millimetres, Z up, as in the Notes
const view = $('#view'), canvas = $('#gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.localClippingEnabled = true;
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 10000);
scene.add(camera);
const hemi = new THREE.HemisphereLight(0xffffff, 0x556070, 1.1), head = new THREE.DirectionalLight(0xffffff, 1.6);
scene.add(hemi);
head.position.set(0.5, 0.8, 1);
camera.add(head);
let saved = {};
try { saved = JSON.parse(localStorage.getItem('monet.view') || '{}'); } catch { /* no storage */ }
const look = createLook(renderer, scene, { hemi, head });
look.set(saved.style ?? 'rendered');
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = false;
controls.screenSpacePanning = true;
const loader = new GLTFLoader();
const groups = { part: new THREE.Group(), a: new THREE.Group(), b: new THREE.Group() };
Object.values(groups).forEach((g) => scene.add(g));
const cut = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);
const wipeA = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0), wipeB = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
const box = new THREE.Box3(), size = new THREE.Vector3(), centre = new THREE.Vector3();
let radius = 100, meshes = [], shared = null, edgesOn = true, xray = false, sectionOn = false, explode = 0, partColours = true;
const home = new THREE.Vector3();   // the middle of the assembly as it is put together

// selected lines and points are drawn over everything, thick enough to see
const selLines = new LineSegments2(new LineSegmentsGeometry(), new LineMaterial({ color: 0xffd23f, linewidth: 3.5, depthTest: false, transparent: true }));
const selDots = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: 0xffd23f, size: 11, sizeAttenuation: false, depthTest: false, transparent: true }));
// the measured distance: a line between the two nearest points, with its length written beside it
const dimLine = new LineSegments2(new LineSegmentsGeometry(), new LineMaterial({ color: 0x5fd0ff, linewidth: 2.5, depthTest: false, transparent: true }));
const dimDots = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: 0x5fd0ff, size: 9, sizeAttenuation: false, depthTest: false, transparent: true }));
for (const o of [selLines, selDots, dimLine, dimDots]) { o.renderOrder = 10; o.frustumCulled = false; o.visible = false; o.material.toneMapped = false; scene.add(o); }
// a tag that is pointed at in the panel shows through the part, like a hologram: wherever it is, it can be seen
const holo = new THREE.Group();
holo.renderOrder = 8;
scene.add(holo);
// the sketches of the part: what the user drew on its faces, always in sight
const drawn = new THREE.Group();
scene.add(drawn);
const sketch = createSketcher({ scene, camera, controls, canvas, view, corners: () => S.points.map((v) => v.at), changed: () => { roomBar(); showSketches(); renderPanel(true); } });

// compared versions are always drawn plainly: their colours are the distance map
const material = () => new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0, roughness: 0.8, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });

// what a part is made of and its colour: set per Note (and per part of an assembly, by its name) in the project
function lookOf(part) {
  const looks = S.proj?.looks ?? {}, name = S.parts.length > 1 ? S.parts[part]?.name : S.note;
  const spec = looks[name] ?? {};
  const kind = MATERIALS[spec.material] ? spec.material : 'pla';
  return { material: kind, color: spec.color || MATERIALS[kind].color, name };
}

// give every part the material of the style it is shown in
function dress() {
  const edge = look.edge();
  for (const one of groups.part.children) {
    for (const o of one.children) {
      if (o.isMesh) { o.material.dispose(); o.material = look.material(lookOf(one.userData.part)); }
      else if (o.userData.edges) { o.material.color.set(edge.color); o.material.opacity = edge.opacity; o.material.transparent = edge.opacity < 1; }
      else if (o.userData.dots) o.material.color.set(edge.color);
    }
  }
  $('#partColours').hidden = !(S.parts.length > 1 && !S.compare && look.style === 'shaded');
  styleAll(); paint();
}

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h, false);
  for (const o of [selLines, dimLine, ...holo.children, ...drawn.children]) o.material.resolution?.set(w, h);
  sketch.resize();
  const half = radius * 1.2, aspect = w / Math.max(1, h);
  Object.assign(camera, { left: -half * aspect, right: half * aspect, top: half, bottom: -half, near: 0.01, far: radius * 40 });
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(view);

const LOOK = { iso: [1, -1, 0.8], top: [0, -0.0001, 1], front: [0, -1, 0], right: [1, 0, 0] };
function lookFrom(name) {
  if (name !== 'fit') camera.position.copy(centre).addScaledVector(new THREE.Vector3(...LOOK[name]).normalize(), radius * 8);
  else camera.position.sub(controls.target).normalize().multiplyScalar(radius * 8).add(centre);
  camera.zoom = 1;
  controls.target.copy(centre);
  resize();
  controls.update();
}

function frame(object, keepCamera) {
  if (object === groups.part) for (const one of object.children) one.position.set(0, 0, 0);   // measured put together; spread() follows
  box.setFromObject(object);
  if (box.isEmpty()) return;
  box.getSize(size); box.getCenter(centre);
  if (object === groups.part) home.copy(centre);
  radius = Math.max(1, size.length() / 2);
  if (!keepCamera) lookFrom('iso');
  setSection();
}

async function loadInto(group, url, plain) {
  const gltf = await loader.loadAsync(url);
  group.clear();
  let found = null, lines = null;
  gltf.scene.traverse((o) => {
    if (o.isMesh) {
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
      if (plain || !o.geometry.attributes.color) {
        const n = o.geometry.attributes.position.count, c = new Float32Array(n * 3);
        for (let i = 0; i < n; i++) BASE.toArray(c, i * 3);
        o.geometry.setAttribute('color', new THREE.BufferAttribute(c, 3));
      }
      o.material = material();
      found = o;
    } else if (o.isLine) {
      o.material = new THREE.LineBasicMaterial({ color: 0x10131b });
      o.userData.edges = true;
      lines = o;
    }
  });
  group.add(gltf.scene);
  return { mesh: found, lines };
}

// The draft arrives as one mesh, its triangles grouped part by part. Give every part an object of its own (they
// share the vertices), so a part can be hidden, coloured and pulled out of the assembly. A plain Note is one part.
function assemble({ mesh, lines }) {
  meshes = []; shared = null;
  groups.part.clear();
  if (!mesh) return;
  const g = mesh.geometry;
  shared = { colour: g.attributes.color, index: g.index.array, position: g.attributes.position.array, segs: lines ? lines.geometry.attributes.position.array : new Float32Array(0) };
  const parts = S.parts.length ? S.parts : [{ tris: [0, g.index.count / 3], edges: [0, shared.segs.length / 6] }];
  parts.forEach((part, i) => {
    const pg = new THREE.BufferGeometry();
    for (const k of ['position', 'normal', 'color']) pg.setAttribute(k, g.attributes[k]);
    pg.setIndex(g.index);
    pg.setDrawRange(part.tris[0] * 3, part.tris[1] * 3);
    if (part.bbox) {
      pg.boundingBox = new THREE.Box3(new THREE.Vector3(...part.bbox.slice(0, 3)), new THREE.Vector3(...part.bbox.slice(3)));
      pg.boundingSphere = pg.boundingBox.getBoundingSphere(new THREE.Sphere());
    }
    const one = new THREE.Group(), m = new THREE.Mesh(pg, new THREE.MeshBasicMaterial());     // dress() gives it its material
    m.userData.part = one.userData.part = i;
    one.add(m);
    if (lines && part.edges[1]) {
      const lg = new THREE.BufferGeometry();
      lg.setAttribute('position', lines.geometry.attributes.position);
      lg.setDrawRange(part.edges[0] * 2, part.edges[1] * 2);
      if (part.bbox) { lg.boundingBox = pg.boundingBox; lg.boundingSphere = pg.boundingSphere; }
      const l = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x10131b, toneMapped: false }));
      l.userData.edges = true;
      one.add(l);
    }
    // the corner points, shown while points are what is being picked
    const mine = S.points.filter((v) => v.p === i).flatMap((v) => v.at);
    if (mine.length) {
      const dg = new THREE.BufferGeometry();
      dg.setAttribute('position', new THREE.Float32BufferAttribute(mine, 3));
      const dots = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0x10131b, size: 5, sizeAttenuation: false, toneMapped: false }));
      dots.userData.dots = true;
      one.add(dots);
    }
    groups.part.add(one);
    meshes.push(m);
  });
  dress();
}

const ZERO = new THREE.Vector3();
const offsetOf = (part) => groups.part.children[part]?.position ?? ZERO;   // where an exploded part has gone

// pull the parts away from the middle of the assembly, each along its own direction
function spread() {
  for (const one of groups.part.children) {
    const b = S.parts[one.userData.part]?.bbox;
    if (b) one.position.set((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2).sub(home).multiplyScalar(explode);
    one.visible = !S.hidden.has(one.userData.part);
  }
  showSelection();
}

function styleAll() {
  for (const [key, g] of Object.entries(groups)) {
    g.traverse((o) => {
      if (o.userData.dots) { o.visible = S.mode === 'vertex' || S.measuring; return; }
      // lines are always drawn while lines are what is being picked
      if (o.userData.edges) { o.visible = edgesOn || (key === 'part' && (S.mode === 'edge' || S.measuring || look.style === 'hidden')); o.material.clippingPlanes = sectionOn && key === 'part' ? [cut] : []; return; }
      if (!o.isMesh) return;
      const m = o.material;
      m.clippingPlanes = key === 'part' ? (sectionOn ? [cut] : []) : (S.compare?.mode === 'wipe' ? [key === 'a' ? wipeA : wipeB] : []);
      const fade = S.compare?.mode === 'fade' ? (key === 'a' ? 1 - S.compare.mix : S.compare.mix) : 1;
      const opacity = key === 'part' ? (xray ? 0.25 : 1) : fade;
      m.transparent = opacity < 1; m.opacity = opacity; m.depthWrite = opacity >= 1;
      m.needsUpdate = true;
    });
  }
}

function setSection() {
  const axis = 'XYZ'.indexOf($('#sectionAxis').value), t = Number($('#sectionAt').value);
  cut.normal.set(0, 0, 0).setComponent(axis, -1);
  cut.constant = box.min.getComponent(axis) + (box.max.getComponent(axis) - box.min.getComponent(axis)) * t;
  const mix = S.compare?.mix ?? 0.5, x = box.min.x + (box.max.x - box.min.x) * mix;
  wipeA.constant = x; wipeB.constant = -x;
}

// colour the faces: the parts of an assembly, tagged faces on hover, what is selected
function paint() {
  if (!shared) return;
  const colour = shared.colour, index = shared.index;
  const bare = look.base();
  for (let i = 0; i < colour.count; i++) bare.toArray(colour.array, i * 3);
  const range = (start, count, c) => { for (let k = start * 3; k < (start + count) * 3; k++) c.toArray(colour.array, index[k] * 3); };
  const fill = (ids, c) => { for (const id of ids) { const f = S.faces[id]; if (f) range(f.tris[0], f.tris[1], c); } };
  const many = S.parts.length > 1, coloured = many && partColours && look.style === 'shaded';
  S.parts.forEach((part, i) => {
    const picked = S.sel.part.has(i), lit = picked || i === S.hotPart;
    if (coloured) range(part.tris[0], part.tris[1], new THREE.Color(PARTS[i % PARTS.length]).lerp(picked ? PICK : new THREE.Color('#ffffff'), lit ? 0.5 : 0));
    else if (lit) range(part.tris[0], part.tris[1], bare.clone().lerp(PICK, picked ? 0.6 : 0.3));
  });
  const tags = Object.keys(S.data?.tags ?? {});
  tags.forEach((name, n) => { if (S.hot === name || S.tagSel === name) fill(S.data.tag_hits?.[name]?.faces ?? [], new THREE.Color(PALETTE[n % PALETTE.length])); });
  fill(S.sel.face, PICK);
  colour.needsUpdate = true;
}

function faceOfTriangle(t) {
  let lo = 0, hi = S.faces.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (S.faces[mid].tris[0] <= t) lo = mid; else hi = mid - 1; }
  return S.faces[lo];
}
const partOfFace = (i) => S.parts.findIndex((p) => i >= p.faces[0] && i < p.faces[0] + p.faces[1]);

// ---- selecting: points, lines, faces, objects ----------------------------------------------------------------
// A click picks one; Shift adds, Ctrl (or Cmd) takes away. A drag with Shift or Ctrl held, or any drag while the
// Box tool is on, draws a box: left to right it takes whatever it touches, right to left only what is wholly inside.

// from where a thing is to where it is on the screen (canvas pixels) and how deep (smaller is nearer)
function projector() {
  camera.updateMatrixWorld();
  const e = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse).elements;
  const r = canvas.getBoundingClientRect();
  return (x, y, z) => [(e[0] * x + e[4] * y + e[8] * z + e[12] + 1) / 2 * r.width, (1 - (e[1] * x + e[5] * y + e[9] * z + e[13])) / 2 * r.height,
    e[2] * x + e[6] * y + e[10] * z + e[14]];
}

function toSegment(px, py, ax, ay, bx, by) {   // how far, and how far along
  const dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
  const t = len ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len)) : 0;
  return [Math.hypot(px - ax - t * dx, py - ay - t * dy), t];
}

function pick(x, y, mode = S.mode) {
  const r = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2((x / r.width) * 2 - 1, -(y / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(meshes.filter((m) => m.parent.visible), false).find((h) => !sectionOn || cut.distanceToPoint(h.point) >= 0);
  // where on the part, not where on the screen: an exploded part has been moved
  S.point = hit ? hit.point.clone().sub(hit.object.parent.position).toArray().map((v) => Math.round(v * 100) / 100) : null;
  if (mode === 'face') return hit ? { kind: 'face', i: faceOfTriangle(hit.faceIndex).i } : null;
  if (mode === 'part') return hit ? { kind: 'part', i: hit.object.userData.part } : null;
  // points and lines are too thin to hit: take the nearest one within reach of the cursor that is not behind the surface
  const to = projector(), front = hit ? to(hit.point.x, hit.point.y, hit.point.z)[2] : Infinity;
  const slack = 2 / (camera.far - camera.near);   // a millimetre of depth: an edge lies on the faces it bounds
  let best = null;
  if (mode === 'vertex') {
    for (const v of S.points) {
      if (S.hidden.has(v.p)) continue;
      const o = offsetOf(v.p), [px, py, pz] = to(v.at[0] + o.x, v.at[1] + o.y, v.at[2] + o.z), d = Math.hypot(px - x, py - y);
      if (d < 10 && pz <= front + slack && (!best || d < best.d)) best = { kind: 'vertex', i: v.i, d };
    }
  } else {
    const s = shared.segs;
    for (const e of S.edges) {
      if (S.hidden.has(e.p)) continue;
      const o = offsetOf(e.p);
      for (let k = e.segs[0] * 6; k < (e.segs[0] + e.segs[1]) * 6; k += 6) {
        const a = to(s[k] + o.x, s[k + 1] + o.y, s[k + 2] + o.z), b = to(s[k + 3] + o.x, s[k + 4] + o.y, s[k + 5] + o.z);
        const [d, t] = toSegment(x, y, a[0], a[1], b[0], b[1]);
        if (d < 8 && a[2] + (b[2] - a[2]) * t <= front + slack && (!best || d < best.d)) best = { kind: 'edge', i: e.i, d };
      }
    }
  }
  return best;
}

function hitsBox(ax, ay, bx, by, x0, y0, x1, y1) {   // does any of the segment lie inside the box (Liang–Barsky)
  let t0 = 0, t1 = 1;
  const dx = bx - ax, dy = by - ay;
  for (const [p, q] of [[-dx, ax - x0], [dx, x1 - ax], [-dy, ay - y0], [dy, y1 - ay]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return true;
}

function boxPick(x0, y0, x1, y1, touching) {
  const to = projector(), inside = (p) => p[0] >= x0 && p[0] <= x1 && p[1] >= y0 && p[1] <= y1, out = [];
  if (S.mode === 'vertex') {
    for (const v of S.points) {
      const o = offsetOf(v.p);
      if (!S.hidden.has(v.p) && inside(to(v.at[0] + o.x, v.at[1] + o.y, v.at[2] + o.z))) out.push({ kind: 'vertex', i: v.i });
    }
  } else if (S.mode === 'edge') {
    const s = shared.segs;
    for (const e of S.edges) {
      if (S.hidden.has(e.p)) continue;
      const o = offsetOf(e.p);
      let any = false, all = true;
      for (let k = e.segs[0] * 6; k < (e.segs[0] + e.segs[1]) * 6 && (touching ? !any : all); k += 6) {
        const a = to(s[k] + o.x, s[k + 1] + o.y, s[k + 2] + o.z), b = to(s[k + 3] + o.x, s[k + 4] + o.y, s[k + 5] + o.z);
        if (inside(a) && inside(b)) any = true; else { all = false; if (hitsBox(a[0], a[1], b[0], b[1], x0, y0, x1, y1)) any = true; }
      }
      if (touching ? any : all) out.push({ kind: 'edge', i: e.i });
    }
  } else {
    // faces and objects: by the corners of their triangles
    const pos = shared.position, index = shared.index;
    const test = (start, count, o) => {
      let any = false, all = true;
      for (let k = start * 3; k < (start + count) * 3 && (touching ? !any : all); k++) {
        const v = index[k] * 3;
        if (inside(to(pos[v] + o.x, pos[v + 1] + o.y, pos[v + 2] + o.z))) any = true; else all = false;
      }
      return touching ? any : all;
    };
    S.parts.forEach((part, p) => {
      if (S.hidden.has(p)) return;
      const o = offsetOf(p);
      if (S.mode === 'part') { if (test(part.tris[0], part.tris[1], o)) out.push({ kind: 'part', i: p }); return; }
      for (let i = part.faces[0]; i < part.faces[0] + part.faces[1]; i++) if (test(S.faces[i].tris[0], S.faces[i].tris[1], o)) out.push({ kind: 'face', i });
    });
    // a box drawn wholly inside one big face touches it without holding any of its corners
    const under = touching && pick((x0 + x1) / 2, (y0 + y1) / 2);
    if (under) out.push(under);
  }
  return out;
}

function select(items, how) {
  if (!how.add && !how.remove) S.sel = nothing();
  for (const { kind, i } of items) (how.remove ? S.sel[kind].delete(i) : S.sel[kind].add(i));
  selectionChanged();
}

function showSelection() {
  paint();
  const lines = [], dots = [];
  if (shared) {
    for (const i of S.sel.edge) {
      const e = S.edges[i]; if (!e) continue;
      const o = offsetOf(e.p), s = shared.segs;
      for (let k = e.segs[0] * 6; k < (e.segs[0] + e.segs[1]) * 6; k += 3) lines.push(s[k] + o.x, s[k + 1] + o.y, s[k + 2] + o.z);
    }
    for (const i of S.sel.vertex) { const v = S.points[i]; if (v) { const o = offsetOf(v.p); dots.push(v.at[0] + o.x, v.at[1] + o.y, v.at[2] + o.z); } }
  }
  selLines.visible = lines.length > 0 && !S.compare;
  if (lines.length) { selLines.geometry.dispose(); selLines.geometry = new LineSegmentsGeometry().setPositions(lines); }
  selDots.visible = dots.length > 0 && !S.compare;
  selDots.geometry.dispose();
  selDots.geometry = new THREE.BufferGeometry();
  selDots.geometry.setAttribute('position', new THREE.Float32BufferAttribute(dots, 3));
  showMeasure(); showTag();
}

const count = () => S.sel.vertex.size + S.sel.edge.size + S.sel.face.size + S.sel.part.size;
// the one face, when a single face is all that is selected
const theFace = () => (S.sel.face.size === 1 && count() === 1 ? S.faces[[...S.sel.face][0]] : null);
const partName = (p) => (S.parts.length > 1 ? S.parts[p]?.name ?? null : null);
const r2 = (v) => Math.round(v * 100) / 100, r3 = (v) => Math.round(v * 1000) / 1000;
const at3 = (arr, k) => [arr[k], arr[k + 1], arr[k + 2]];
const axisOf = (n) => { const i = n.findIndex((v) => Math.abs(v) > 0.9999); return i < 0 ? null : `${n[i] > 0 ? '+' : '−'}${'XYZ'[i]}`; };

// A selected thing as what it is made of (points, segments, triangles: what measure.js works on), which way it
// points if it has a way, and the facts about it alone. In the part's own millimetres, not where it was exploded to.
function thing(kind, i) {
  if (kind === 'vertex') { const v = S.points[i]; return v && { kind, part: v.p, points: [v.at], facts: [['x, y, z', v.at.map(r3).join(', ')]] }; }
  if (kind === 'edge') {
    const e = S.edges[i]; if (!e) return null;
    const segments = [], g = shared.segs;
    for (let k = e.segs[0] * 6; k < (e.segs[0] + e.segs[1]) * 6; k += 6) segments.push([at3(g, k), at3(g, k + 3)]);
    const facts = [['length', `${r3(e.len)} mm`]];
    if (e.type === 'circle') facts.push(['diameter', `${r3(2 * e.r)} mm`], ['radius', `${r3(e.r)} mm`], ['centre', e.c.map(r3).join(', ')]);
    else facts.push(['from', e.a.map(r3).join(', ')], ['to', e.b.map(r3).join(', ')]);
    return { kind, part: e.p, segments, facts, dir: e.type === 'line' ? { line: e.b.map((v, k) => v - e.a[k]) } : null };
  }
  const triangles = (start, n) => {
    const out = [], pos = shared.position, ix = shared.index;
    for (let k = start * 3; k < (start + n) * 3; k += 3) out.push([at3(pos, ix[k] * 3), at3(pos, ix[k + 1] * 3), at3(pos, ix[k + 2] * 3)]);
    return out;
  };
  if (kind === 'face') {
    const f = S.faces[i]; if (!f) return null;
    const facts = [['area', `${r3(f.area)} mm²`]];
    if (f.type === 'plane') {
      const ax = axisOf(f.normal);
      facts.push(['faces', ax ?? f.normal.map(r3).join(', ')]);
      if (ax) facts.push(['at', `${ax[1].toLowerCase()} = ${r3(f.center['XYZ'.indexOf(ax[1])])}`]);
    }
    if (f.type === 'cylinder') facts.push([f.concave ? 'hole diameter' : 'diameter', `${r3(2 * f.radius)} mm`], ['axis', axisOf(f.axis)?.[1] ?? f.axis.map(r3).join(', ')]);
    return { kind, part: partOfFace(i), triangles: triangles(f.tris[0], f.tris[1]), facts,
      dir: f.type === 'plane' ? { normal: f.normal } : f.type === 'cylinder' ? { line: f.axis } : null };
  }
  const q = S.parts[i];
  return q && { kind, part: i, triangles: triangles(q.tris[0], q.tris[1]),
    facts: [['size', `${[0, 1, 2].map((k) => r3(q.bbox[k + 3] - q.bbox[k])).join(' × ')} mm`], ['volume', `${r3(q.volume / 1000)} cm³`]] };
}

// What the selection says, as Inspect does in Fusion: one thing, its own facts; two things, the shortest distance
// between them, how that splits along the axes, and the angle; more, what they add up to.
function inspect() {
  const things = Object.keys(NAMES).flatMap((kind) => [...S.sel[kind]].map((i) => thing(kind, i))).filter(Boolean);
  const out = { rows: [], dim: null };
  if (things.length === 1) out.rows = things[0].facts;
  else if (things.length === 2) {
    const [A, B] = things, c = closest(A, B), ang = angle(A.dir, B.dir);
    const flat = A.dir?.normal && B.dir?.normal && ang < 0.01;
    out.rows.push([c.d < 1e-9 ? 'they touch' : flat ? 'distance' : 'shortest distance', `${c.about ? '≈ ' : ''}${r3(c.d)} mm`, true]);
    if (c.d >= 1e-9) out.rows.push(['along x, y, z', c.b.map((v, k) => r3(Math.abs(v - c.a[k]))).join(', ')]);
    if (ang != null) out.rows.push(['angle', `${r3(ang)}°`]);
    if (c.about) out.rows.push(['', 'large things: measured between their corners, so about']);
    if (c.d >= 1e-9) out.dim = { a: c.a, b: c.b, pa: A.part, pb: B.part, text: `${c.about ? '≈ ' : ''}${r3(c.d)}` };
  } else if (things.length > 2) {
    const E = [...S.sel.edge].map((i) => S.edges[i]).filter(Boolean), F = [...S.sel.face].map((i) => S.faces[i]).filter(Boolean);
    if (E.length) out.rows.push(['total length', `${r3(E.reduce((a, e) => a + e.len, 0))} mm`, true]);
    if (F.length) out.rows.push(['total area', `${r3(F.reduce((a, f) => a + f.area, 0))} mm²`, true]);
  }
  return out;
}
const measures = () => Object.fromEntries((S.inspect?.rows ?? []).filter(([k]) => k).map(([k, v]) => [k, v]));

function showMeasure() {
  const d = !S.compare && S.inspect?.dim;
  dimLine.visible = dimDots.visible = !!d;
  $('#dim').hidden = !d;
  if (!d) return;
  const a = offsetOf(d.pa).clone().add(new THREE.Vector3(...d.a)), b = offsetOf(d.pb).clone().add(new THREE.Vector3(...d.b));
  dimLine.geometry.dispose();
  dimLine.geometry = new LineSegmentsGeometry().setPositions([...a.toArray(), ...b.toArray()]);
  dimDots.geometry.dispose();
  dimDots.geometry = new THREE.BufferGeometry();
  dimDots.geometry.setAttribute('position', new THREE.Float32BufferAttribute([...a.toArray(), ...b.toArray()], 3));
  d.mid = a.add(b).multiplyScalar(0.5);
  $('#dim').textContent = `${d.text} mm`;
}

function showSketches() {
  for (const o of drawn.children) { o.geometry.dispose(); o.material.dispose(); }
  drawn.clear();
  if (!S.data?.tags || S.compare) return;
  Object.entries(S.data.tags).forEach(([name, t], n) => {
    if (t.kind !== 'sketch' || !t.plane || (sketch.state.active && sketch.state.editing === name)) return;
    const b = basis(t.plane), lit = name === S.hot || name === S.tagSel;
    const l = strokes((t.curves ?? []).map((c) => outline(c, b)), PALETTE[n % PALETTE.length], lit ? 4 : 2, sketch.state.active ? 0.35 : 0.9);
    l.material.resolution.set(view.clientWidth, view.clientHeight);
    drawn.add(l);
  });
}

// a tag, seen through the part: its faces as a glow, its lines and points on top of everything
function showTag() {
  showSketches();
  for (const o of holo.children) { o.geometry.dispose(); o.material.dispose(); }
  holo.clear();
  const name = S.hot ?? S.tagSel, hits = S.data?.tag_hits?.[name];
  if (!hits || !shared || S.compare) return;
  const colour = new THREE.Color(PALETTE[Object.keys(S.data.tags).indexOf(name) % PALETTE.length]);
  const pos = shared.position, ix = shared.index, tris = [];
  const add = (start, n, o) => { for (let k = start * 3; k < (start + n) * 3; k++) { const v = ix[k] * 3; tris.push(pos[v] + o.x, pos[v + 1] + o.y, pos[v + 2] + o.z); } };
  for (const i of hits.faces) { const f = S.faces[i]; if (f) add(f.tris[0], f.tris[1], offsetOf(partOfFace(i))); }
  for (const i of hits.parts) { const q = S.parts[i]; if (q) add(q.tris[0], q.tris[1], offsetOf(i)); }
  if (tris.length) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(tris, 3));
    holo.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.4, depthTest: false, depthWrite: false, side: THREE.DoubleSide })));
  }
  const lines = [], dots = [];
  for (const i of hits.edges) {
    const e = S.edges[i]; if (!e) continue;
    const o = offsetOf(e.p), g = shared.segs;
    for (let k = e.segs[0] * 6; k < (e.segs[0] + e.segs[1]) * 6; k += 3) lines.push(g[k] + o.x, g[k + 1] + o.y, g[k + 2] + o.z);
  }
  for (const i of hits.points) { const v = S.points[i]; if (v) { const o = offsetOf(v.p); dots.push(v.at[0] + o.x, v.at[1] + o.y, v.at[2] + o.z); } }
  if (lines.length) {
    const l = new LineSegments2(new LineSegmentsGeometry().setPositions(lines), new LineMaterial({ color: colour, linewidth: 4, depthTest: false, transparent: true }));
    l.material.resolution.set(view.clientWidth, view.clientHeight);
    holo.add(l);
  }
  if (dots.length) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(dots, 3));
    holo.add(new THREE.Points(g, new THREE.PointsMaterial({ color: colour, size: 13, sizeAttenuation: false, depthTest: false, transparent: true })));
  }
  for (const o of holo.children) { o.renderOrder = 8; o.frustumCulled = false; o.material.toneMapped = false; }
}

function selectedItems() {
  const out = [];
  for (const i of S.sel.part) { const p = S.parts[i]; if (p) out.push({ kind: 'part', name: p.name, volume: p.volume, bbox: p.bbox }); }
  for (const i of S.sel.face) { const f = S.faces[i]; if (f) { const { tris, ...rest } = f; out.push({ kind: 'face', ...rest, part: partName(partOfFace(i)) }); } }
  for (const i of S.sel.edge) { const e = S.edges[i]; if (e) { const { segs, p, ...rest } = e; out.push({ kind: 'edge', ...rest, part: partName(p) }); } }
  for (const i of S.sel.vertex) { const v = S.points[i]; if (v) out.push({ kind: 'vertex', at: v.at, part: partName(v.p) }); }
  return out;
}

function selectionChanged() {
  S.inspect = shared ? inspect() : null;
  showSelection(); showMeasure(); renderPanel(true);
  if (!S.project || !S.note) return;
  const items = selectedItems(), face = theFace();
  const tags = Object.entries(S.data?.tag_faces ?? {}).filter(([, ids]) => face && ids.includes(face.i)).map(([k]) => k);
  // the agent is told what is pointed at: selection() on its side
  api(`/p/${S.project}/selection`, 'POST', items.length ? { note: S.note, mode: S.mode, count: items.length, items: items.slice(0, 100), measure: measures(),
    face, point: face ? S.point : null, tags, part: face ? partName(partOfFace(face.i)) : null } : {}).catch(() => {});
}

let press = null;
const marquee = $('#marquee');
view.addEventListener('pointerdown', (e) => {   // before the orbit controls see it: a drag that draws a box must not turn the view
  if (sketch.state.active) { if (e.target === canvas) sketch.down(e); return; }      // drawing: a click places a point
  if (e.target !== canvas || e.button !== 0) return;
  const boxing = !S.compare && meshes.length > 0 && (S.boxTool || e.shiftKey || e.ctrlKey || e.metaKey);
  press = { x: e.clientX, y: e.clientY, boxing, add: e.shiftKey, remove: e.ctrlKey || e.metaKey, moved: false };
  if (boxing) controls.enabled = false;
}, true);
window.addEventListener('pointermove', (e) => {
  if (!press?.boxing) return;
  if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 4) press.moved = true;
  if (!press.moved) return;
  const r = view.getBoundingClientRect();
  Object.assign(marquee.style, { left: `${Math.min(e.clientX, press.x) - r.left}px`, top: `${Math.min(e.clientY, press.y) - r.top}px`,
    width: `${Math.abs(e.clientX - press.x)}px`, height: `${Math.abs(e.clientY - press.y)}px` });
  marquee.classList.toggle('touching', e.clientX >= press.x);
  marquee.hidden = false;
});
window.addEventListener('pointerup', (e) => {
  if (!press) return;
  const p = press, r = canvas.getBoundingClientRect();
  press = null; controls.enabled = true; marquee.hidden = true;
  if (!meshes.length || S.compare) return;
  if (p.boxing && p.moved) {
    select(boxPick(Math.min(e.clientX, p.x) - r.left, Math.min(e.clientY, p.y) - r.top, Math.max(e.clientX, p.x) - r.left, Math.max(e.clientY, p.y) - r.top, e.clientX >= p.x), p);
  } else if (Math.hypot(e.clientX - p.x, e.clientY - p.y) <= 4 && e.target === canvas) {
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (S.room === 'sketch') {      // no sketch under way: a click on a flat face starts one there
      const one = pick(x, y, 'face');
      if (one && S.faces[one.i].type === 'plane') startSketch({ face: S.faces[one.i] });
    } else if (S.measuring && !p.add && !p.remove) {
      // measuring: a point if one is near, else a line, else the face (or the object, when objects are being picked)
      const one = pick(x, y, 'vertex') ?? pick(x, y, 'edge') ?? pick(x, y, S.mode === 'part' ? 'part' : 'face');
      select(one ? [one] : [], { add: !!one && count() < 2 });      // two at a time: a third click starts again
    } else {
      const one = pick(x, y);
      select(one ? [one] : [], p);
    }
  }
});
canvas.addEventListener('contextmenu', (e) => e.preventDefault());   // Ctrl-click on a Mac is a selection, not a menu
canvas.addEventListener('pointermove', (e) => { if (sketch.state.active) sketch.move(e); });
canvas.addEventListener('pointerleave', () => { if (sketch.state.active) sketch.leave(); });
window.addEventListener('keydown', (e) => {
  if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName ?? '')) return;
  if (sketch.state.active && sketch.key(e)) e.preventDefault();
});

function setMode(mode) {
  S.mode = mode;
  document.querySelectorAll('[data-sel]').forEach((b) => b.classList.toggle('on', b.dataset.sel === mode));
  styleAll(); renderPanel();
}
document.querySelectorAll('[data-sel]').forEach((b) => { b.onclick = () => setMode(b.dataset.sel); });
$('#boxTool').onclick = (e) => { S.boxTool = !S.boxTool; e.target.classList.toggle('on', S.boxTool); canvas.style.cursor = S.boxTool ? 'crosshair' : ''; };
$('#measure').onclick = (e) => { S.measuring = !S.measuring; e.target.classList.toggle('on', S.measuring); styleAll(); renderPanel(); };

const label = $('#dim'), spot = new THREE.Vector3();
// ---- three places to work: Sketch (a drawing on a face), Part (one object), Assembly (objects put together) -----
const kindOf = (name) => S.proj?.notes.find((n) => n.name === name)?.kind;
function roomBar() {
  document.body.dataset.room = S.room;
  document.querySelectorAll('[data-room]').forEach((b) => b.classList.toggle('on', b.dataset.room === S.room));
  document.querySelectorAll('[data-rooms]').forEach((el) => el.classList.toggle('away', !el.dataset.rooms.split(' ').includes(S.room)));
  document.querySelectorAll('[data-sketching]').forEach((el) => el.classList.toggle('away', S.room !== 'sketch' || !sketch.state.active));
  document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === sketch.state.tool));
  $('#sketchSnap').classList.toggle('on', sketch.state.snap);
  $('.hint').innerHTML = S.room === 'sketch' ? (sketch.state.active
    ? 'click: place a point · click the first point: close · Enter: end the line · Esc: drop it · Backspace: step back<br>lines up with corners (pink) and the 1 mm grid · Shift: free · right-drag: move the page · wheel: zoom'
    : 'click a flat face to draw on it')
    : 'drag: orbit · right-drag: pan · wheel: zoom<br>click: select · Shift: add · Ctrl: take away · Shift- or Ctrl-drag: box';
  canvas.style.cursor = S.room === 'sketch' ? 'crosshair' : S.boxTool ? 'crosshair' : '';
}
function startSketch(what) {
  S.room = 'sketch';
  S.sketchName = what.name ?? ''; S.sketchRole = what.tag?.role ?? '';
  S.sel = nothing(); S.inspect = null; showSelection();
  sketch.begin(what);
}
function leaveSketch() {
  sketch.end();
  S.room = kindOf(S.note) === 'assembly' ? 'assembly' : 'part';
  roomBar(); showSketches(); renderPanel(true);
}
const notice = (text) => { busy(text); setTimeout(() => { if ($('#busy').textContent === text) busy(); }, 3500); };
async function goRoom(room) {
  if (!S.proj) return;
  if (room === 'sketch') {
    if (S.room === 'sketch') return;
    if (kindOf(S.note) !== 'note') {      // a sketch is drawn on a part: go to one first
      const part = S.proj.notes.find((n) => n.kind === 'note' && n.name === S.lastPart) ?? S.proj.notes.find((n) => n.kind === 'note');
      if (!part) return notice('there is no part in this project to draw on');
      await open(S.project, part.name);
    }
    const face = theFace();
    if (face?.type === 'plane') startSketch({ face });
    else { S.room = 'sketch'; roomBar(); renderPanel(true); }
    return;
  }
  if (S.room === 'sketch') sketch.end();
  if (room === 'assembly') {
    const a = S.proj.notes.find((n) => n.kind === 'assembly' && n.name === S.lastAssembly) ?? S.proj.notes.find((n) => n.kind === 'assembly');
    if (!a) { S.room = kindOf(S.note) === 'assembly' ? 'assembly' : 'part'; roomBar(); renderPanel(true); return notice('no assembly in this project yet: ask your agent to put the parts together in a Note'); }
    return open(S.project, a.name);
  }
  // to a part: the object selected in the assembly if it has a Note, else the part that was open last
  const picked = S.sel.part.size === 1 ? S.parts[[...S.sel.part][0]]?.name : null;
  const part = S.proj.notes.find((n) => n.kind === 'note' && n.name === picked) ?? S.proj.notes.find((n) => n.kind === 'note' && n.name === (kindOf(S.note) === 'note' ? S.note : S.lastPart))
    ?? S.proj.notes.find((n) => n.kind === 'note');
  if (!part) { S.room = 'assembly'; roomBar(); return notice('there is no part in this project yet'); }
  if (part.name === S.note) { S.room = 'part'; roomBar(); showSketches(); renderPanel(true); return; }
  return open(S.project, part.name);
}
document.querySelectorAll('[data-room]').forEach((b) => { b.onclick = () => goRoom(b.dataset.room); });
document.querySelectorAll('[data-tool]').forEach((b) => { b.onclick = () => sketch.setTool(b.dataset.tool); });
$('#sketchSnap').onclick = () => { sketch.state.snap = !sketch.state.snap; roomBar(); };

(function loop() {
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, camera);
  if (S.inspect?.dim?.mid && !label.hidden) {     // the length of the measured line, beside its middle
    spot.copy(S.inspect.dim.mid).project(camera);
    label.style.transform = `translate(${(spot.x + 1) / 2 * view.clientWidth + 10}px, ${(1 - spot.y) / 2 * view.clientHeight - 12}px)`;
  }
})();

// ---- toolbar ---------------------------------------------------------------------------------------------
document.querySelectorAll('[data-cam]').forEach((b) => { b.onclick = () => lookFrom(b.dataset.cam); });
$('#edges').onclick = (e) => { edgesOn = !edgesOn; e.target.classList.toggle('on', edgesOn); styleAll(); };
$('#style').innerHTML = Object.entries(STYLES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
$('#style').value = look.style;
$('#style').onchange = (e) => {
  look.set(e.target.value);
  try { localStorage.setItem('monet.view', JSON.stringify({ style: look.style })); } catch { /* not remembered */ }
  dress(); renderPanel();
};
$('#xray').onclick = (e) => { xray = !xray; e.target.classList.toggle('on', xray); styleAll(); };
$('#section').onclick = (e) => {
  sectionOn = !sectionOn; e.target.classList.toggle('on', sectionOn);
  $('#sectionAxis').hidden = $('#sectionAt').hidden = !sectionOn; setSection(); styleAll();
};
$('#sectionAxis').onchange = $('#sectionAt').oninput = () => { setSection(); };
$('#explode').oninput = (e) => {
  explode = Number(e.target.value);
  spread();
  camera.zoom = 1 / (1 + explode * 0.85);   // step back as it grows, so it stays in view
  camera.updateProjectionMatrix();
};
$('#partColours').onclick = (e) => { partColours = !partColours; e.target.classList.toggle('on', partColours); paint(); };
function assemblyBar() {
  const on = S.parts.length > 1 && !S.compare;
  for (const id of ['#asmSep', '#explodeLabel', '#explode']) $(id).hidden = !on;
  $('#partColours').hidden = !(on && look.style === 'shaded');
  $('#explode').value = explode;
}

// ---- compare: the diff as the thing you trust --------------------------------------------------------------
let blink = null;
async function compare(a, b = 'draft') {
  busy(`comparing v${a} with ${b === 'draft' ? 'the draft' : 'v' + b}…`);
  try {
    const q = `a=${a}&b=${b}`;
    const summary = await api(`/p/${S.project}/n/${S.note}/diff?${q}`);
    await Promise.all([loadInto(groups.a, `${root}/p/${S.project}/n/${S.note}/diff.glb?${q}&side=a&r=${summary.stamp.slice(0, 12)}`),
      loadInto(groups.b, `${root}/p/${S.project}/n/${S.note}/diff.glb?${q}&side=b&r=${summary.stamp.slice(0, 12)}`)]);
    S.compare = { a, b, summary, mode: 'added', mix: 0.5 };
    S.sel = nothing(); S.inspect = null;
    showSelection();
    assemblyBar();
    $('#compare').hidden = false;
    $('#compareLabel').textContent = `v${a} → ${b === 'draft' ? 'draft' : 'v' + b}`;
    frame(groups.b, true);
    compareMode('added');
  } catch (e) { alert(e.message); }
  busy();
  renderPanel(true);
}
function compareMode(mode) {
  clearInterval(blink);
  S.compare.mode = mode;
  document.querySelectorAll('[data-mode]').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
  $('#mix').hidden = !(mode === 'fade' || mode === 'wipe');
  groups.part.visible = false;
  groups.a.visible = mode !== 'added'; groups.b.visible = mode !== 'removed';
  if (mode === 'blink') { let on = false; blink = setInterval(() => { on = !on; groups.a.visible = on; groups.b.visible = !on; }, 450); }
  setSection(); styleAll();
}
function compareOff() {
  clearInterval(blink);
  S.compare = null; $('#compare').hidden = true;
  groups.a.clear(); groups.b.clear(); groups.part.visible = true;
  frame(groups.part, true); spread(); assemblyBar(); styleAll(); renderPanel(true);
}
document.querySelectorAll('[data-mode]').forEach((b) => { b.onclick = () => compareMode(b.dataset.mode); });
$('#mix').oninput = (e) => { S.compare.mix = Number(e.target.value); setSection(); styleAll(); };
$('#compareOff').onclick = compareOff;

// ---- folding: every panel on the side can be shut, and stays as it was left -----------------------------------
const FOLDED_AT_FIRST = { source: true };
let folds = {};
try { folds = JSON.parse(localStorage.getItem('monet.folds') || '{}'); } catch { /* no storage: nothing is remembered */ }
const folded = (key) => folds[key] ?? !!FOLDED_AT_FIRST[key];
function fold(key) {
  folds[key] = !folded(key);
  try { localStorage.setItem('monet.folds', JSON.stringify(folds)); } catch { /* as above */ }
  document.querySelectorAll(`[data-card="${key}"]`).forEach((c) => c.classList.toggle('folded', folds[key]));
}
// a card of the panel: a head that folds it (with something to its right) and a body
const card = (key, head, body, right = '') => `<div class="card ${folded(key) ? 'folded' : ''}" data-card="${key}">
  <div class="fold" data-fold="${key}"><span class="chev"></span><span class="head">${head}</span><span class="r">${right}</span></div><div class="body">${body}</div></div>`;
document.querySelectorAll('aside [data-card]').forEach((c) => c.classList.toggle('folded', folded(c.dataset.card)));
$('aside').addEventListener('click', (e) => { const f = e.target.closest('[data-fold]'); if (f) fold(f.dataset.fold); });

// ---- loading -----------------------------------------------------------------------------------------------
function busy(text) { $('#busy').hidden = !text; $('#busy').textContent = text || ''; }
const state = (n) => (n.kind === 'module' ? '' : n.state === 'error' ? 'red' : n.state === 'unbuilt' ? '' : n.changed ? 'yellow' : 'green');
const order = { assembly: 0, note: 1, module: 2 };

function renderSide() {
  // Assembly shows the assemblies; Part and Sketch show the parts (and the modules they share)
  const mine = S.proj.notes.filter((n) => (S.room === 'assembly' ? n.kind === 'assembly' : n.kind !== 'assembly'));
  const sorted = [...mine].sort((a, b) => order[a.kind] - order[b.kind] || a.name.localeCompare(b.name));
  $('#notes').innerHTML = sorted.map((n) => `<div class="item ${n.name === S.note ? 'sel' : ''}" data-note="${esc(n.name)}" title="${n.kind === 'module' ? 'a helper module, imported by Notes' : n.kind === 'assembly' ? 'an assembly: Notes put together' : n.state === 'error' ? 'does not build' : n.changed ? 'changed since the last save' : 'saved'}">
    <span class="dot ${state(n)}"></span>${esc(n.name)}${n.kind === 'note' ? '' : ` <small>${n.kind}</small>`}</div>`).join('')
    || `<div class="item muted">${S.room === 'assembly' ? 'no assembly yet' : 'no parts yet: ask your agent for one'}</div>`;
  $('#versions').innerHTML = [...S.proj.versions].reverse().map((v) => {
    const mine = v.notes[S.note]?.v === v.n;
    return `<div class="item" data-version="${v.n}" title="${esc(v.message)}\n${new Date(v.at).toLocaleString()}${v.commit ? '\ngit ' + esc(v.commit) : ''}\nclick: compare with the draft">
      <span class="dot ${mine ? 'green' : ''}"></span>v${v.n} <small>${esc(v.message || '')}</small></div>`;
  }).join('') || '<div class="item muted">nothing saved yet</div>';
}
$('#notes').onclick = (e) => { const el = e.target.closest('[data-note]'); if (el) open(S.project, el.dataset.note); };
$('#versions').onclick = (e) => { const el = e.target.closest('[data-version]'); if (el && S.data?.is_note) compare(el.dataset.version); };

async function open(project, note) {
  if (S.compare) compareOff();
  const changedNote = project !== S.project || note !== S.note;
  S.project = project;
  S.proj = await api(`/p/${project}`);
  S.rev = S.proj.rev;
  const names = S.proj.notes.map((n) => n.name);
  // a project opens on its assembly, where there is one: the parts put together
  S.note = names.includes(note) ? note : (S.proj.notes.find((n) => n.kind === 'assembly')?.name ?? S.proj.notes.find((n) => n.kind === 'note')?.name ?? names[0] ?? null);
  history.replaceState(null, '', `#${project}${S.note ? '/' + S.note : ''}`);
  $('#project').value = project;
  if (changedNote) { S.sel = nothing(); S.inspect = null; S.tagSel = null; S.saveResult = null; S.hotPart = null; S.hidden = new Set(); explode = 0; sketch.end(); }
  // the room follows the Note: an assembly is worked on in Assembly, a part in Part (or in Sketch, while one is drawn)
  const kind = kindOf(S.note);
  if (changedNote || S.room !== 'sketch') {
    const room = kind === 'assembly' ? 'assembly' : 'part';
    if (room !== S.room || changedNote) S.mode = room === 'assembly' ? 'part' : (S.mode === 'part' ? 'face' : S.mode);
    S.room = room;
  }
  if (kind === 'assembly') S.lastAssembly = S.note; else if (kind === 'note') S.lastPart = S.note;
  document.querySelectorAll('[data-sel]').forEach((b) => b.classList.toggle('on', b.dataset.sel === S.mode));
  roomBar();
  renderSide();
  if (!S.note) { S.data = null; S.parts = []; assemble({}); assemblyBar(); showSelection(); renderPanel(true); return; }
  busy('building…');
  try {
    S.data = await api(`/p/${project}/n/${S.note}`);
    S.rev = (await api(`/p/${project}/rev`)).rev;   // the build itself moved the revision
    if (S.data.report?.built) {
      const stamp = `r=${S.rev}`;
      const [loaded, described] = await Promise.all([loadInto(new THREE.Group(), `${root}/p/${project}/n/${S.note}/model.glb?${stamp}`, true),
        fetch(`${root}/p/${project}/n/${S.note}/faces.json?${stamp}`).then((r) => r.json())]);
      // numbers of faces, lines and points only mean something within one build: a rebuilt part starts unselected
      const same = !changedNote && described.faces.length === S.faces.length && (described.edges ?? []).length === S.edges.length && (described.points ?? []).length === S.points.length;
      if (!same) { S.sel = nothing(); S.inspect = null; }
      S.faces = described.faces; S.parts = described.parts ?? []; S.edges = described.edges ?? []; S.points = described.points ?? [];
      assemble(loaded);
      frame(groups.part, !changedNote);
      spread();
    } else { S.faces = []; S.parts = []; S.edges = []; S.points = []; S.sel = nothing(); assemble({}); showSelection(); }
    assemblyBar();
    S.proj = await api(`/p/${project}`);
    if (S.room !== 'sketch') S.room = kindOf(S.note) === 'assembly' ? 'assembly' : 'part';      // now that it is built, it is known for what it is
    roomBar(); renderSide();
  } catch (e) { S.data = { error: e.message }; }
  busy();
  styleAll(); paint(); showTag(); renderPanel(true);
}

// ---- the panel -----------------------------------------------------------------------------------------------
const AX = ['X', 'Y', 'Z'];
function words(f) {
  if (f.type === 'plane') {
    const i = f.normal.findIndex((v) => Math.abs(v) > 0.9999);
    return i < 0 ? `flat face, slanted (normal ${f.normal.map(r2).join(', ')}), ${r2(f.area)} mm²`
      : `flat face, facing ${f.normal[i] > 0 ? '+' : '−'}${AX[i]}, at ${AX[i].toLowerCase()} = ${r2(f.center[i])}, ${r2(f.area)} mm²`;
  }
  if (f.type === 'cylinder') return `${f.concave ? 'round hole' : 'round boss'}, ⌀ ${r2(2 * f.radius)} mm, axis ${f.axis.map(r2).join(', ')}`;
  return `curved face, ${r2(f.area)} mm², around ${f.center.map(r2).join(', ')}`;
}
function edgeWords(e) {
  if (e.type === 'line') return `straight line, ${r2(e.len)} mm, from ${e.a.map(r2).join(', ')} to ${e.b.map(r2).join(', ')}`;
  if (e.type === 'circle') return `${Math.abs(e.len - 2 * Math.PI * e.r) < 0.01 ? 'circle' : 'arc'}, ⌀ ${r2(2 * e.r)} mm, ${r2(e.len)} mm long, centre ${e.c.map(r2).join(', ')}`;
  return `curve, ${r2(e.len)} mm long`;
}
const row = (k, v) => `<div class="row"><span class="k">${esc(k)}</span><span class="v">${v}</span></div>`;
const fmt = (v) => (typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : Array.isArray(v) ? v.map(fmt).join(', ') : esc(v));

function selectionCard() {
  const n = count();
  const lines = [];
  const named = (p) => (partName(p) ? `<b>${esc(partName(p))}</b>: ` : '');
  for (const i of S.sel.part) if (S.parts[i]) lines.push(`object <b>${esc(S.parts[i].name)}</b>, ${[0, 1, 2].map((k) => r2(S.parts[i].bbox[k + 3] - S.parts[i].bbox[k])).join(' × ')} mm`);
  for (const i of S.sel.face) if (S.faces[i]) lines.push(named(partOfFace(i)) + esc(words(S.faces[i])));
  for (const i of S.sel.edge) if (S.edges[i]) lines.push(named(S.edges[i].p) + esc(edgeWords(S.edges[i])));
  for (const i of S.sel.vertex) if (S.points[i]) lines.push(`${named(S.points[i].p)}point at ${S.points[i].at.map(r2).join(', ')}`);
  const kinds = Object.keys(NAMES).filter((k) => S.sel[k].size).map((k) => `${S.sel[k].size} ${NAMES[k][S.sel[k].size > 1 ? 1 : 0]}`).join(', ');
  const what = S.measuring ? 'point, line or face' : NAMES[S.mode][0];
  const body = n ? `${lines.slice(0, 8).map((l) => `<div class="check">${l}</div>`).join('')}
      ${lines.length > 8 ? `<p class="muted">and ${lines.length - 8} more</p>` : ''}
      <div class="measured">${(S.inspect?.rows ?? []).map(([k, v, big]) => (k ? row(k, big ? `<b class="big">${esc(v)}</b>` : esc(v)) : `<p class="muted">${esc(v)}</p>`)).join('')}</div>
      <div class="line"><input id="tagName" placeholder="name ${n > 1 ? 'them' : 'it'}: base, rod_bore, width…" maxlength="40"><button class="primary" data-act="tag">Tag ${n > 1 ? 'them' : 'it'}</button></div>
      <div class="line"><input id="tagRole" placeholder="what it is for: sits on the plywood" maxlength="200"></div>
      ${S.room === 'part' && theFace()?.type === 'plane' ? '<div class="line"><span class="muted" style="flex:1">Or draw on this face:</span><button data-act="sketchhere">Sketch on it</button></div>' : ''}
      <p class="muted">${n > 1 ? 'Several things under one name: the tag holds as long as every one of them is still there.' : 'A tag is written into the Note and must survive every rebuild.'}
        ${n === 2 && S.inspect?.dim ? ' Two points or two parallel faces also give the tag their distance, which a check can hold.' : ''} Your agent sees this selection.</p>`
    : `<p class="muted">Click a ${what}: your agent can then be told "this ${NAMES[S.mode][0]}". Shift-click adds, Ctrl-click takes away.
        Drag with Shift or Ctrl held (or with Box on) to select with a box: left to right takes what it touches, right to left only what is wholly inside.
        ${S.measuring ? '<br><b>Measuring</b>: click one thing, then another. The shortest distance between them is drawn in the view.' : ''}</p>`;
  return card('selection', n ? `Selected · ${kinds}` : S.measuring ? 'Measure' : `Select · ${NAMES[S.mode][1]}`, body, n ? '<button data-act="clear">Clear</button>' : '');
}

function sketchCards() {
  const sk = sketch.state, tags = Object.entries(S.data?.tags ?? {}).filter(([, t]) => t.kind === 'sketch');
  if (!sk.active) {
    return card('sketch', 'Sketch', `<p class="muted" style="margin-top:0">A drawing on a face of <b>${esc(S.note)}</b>: lines, rectangles and circles, in millimetres.
        It is kept as a tag, and your agent makes the shape of it: "cut the pocket sketch 3 deep", "raise a boss from this circle".</p>
      <p><b>Click a flat face</b> in the view to draw on it.</p>
      ${tags.map(([name, t]) => `<div class="check"><div class="row"><span><b>${esc(name)}</b></span><span class="v muted">${(t.curves ?? []).length} curves</span>
        <button class="x" data-act="editsketch" data-name="${esc(name)}" title="open this sketch">✎</button>
        <button class="x" data-act="untag" data-name="${esc(name)}" title="remove this sketch">×</button></div><div class="why">${esc(t.role ?? '')}</div></div>`).join('')
        || '<p class="muted">No sketches on this part yet.</p>'}`);
  }
  const n = sk.plane.normal, ax = axisOf(n), at = ax ? `${ax[1].toLowerCase()} = ${r3(basis(sk.plane).normal.dot(basis(sk.plane).origin))}` : '';
  return card('sketch', sk.editing ? `Sketch · ${esc(sk.editing)}` : 'New sketch', `
    ${row('on the face', ax ? `facing ${ax}, at ${at}` : `normal ${n.map(r2).join(', ')}`)}
    ${row('u, v', ax ? 'the part\'s own coordinates on this face' : 'from the point of the plane nearest the origin')}
    ${sk.curves.map((c, i) => `<div class="check"><div class="row"><span>${esc(sketch.describe(c))}</span><button class="x" data-act="uncurve" data-i="${i}" title="remove">×</button></div></div>`).join('')
      || '<p class="muted">Nothing drawn yet. Pick Line, Rectangle or Circle above the view and click on the plane.</p>'}
    ${sk.draft ? `<p class="warn">Drawing a ${sk.draft.type === 'rect' ? 'rectangle' : sk.draft.type}: ${sk.draft.type === 'line' ? `${sk.draft.points.length} points; click the first to close, Enter to end` : 'click the second point'}.</p>` : ''}
    <div class="line"><input id="sketchName" placeholder="name it: pocket, slot, boss…" maxlength="40" value="${esc(S.sketchName)}" ${sk.editing ? 'readonly' : ''}></div>
    <div class="line"><input id="sketchRole" placeholder="what to do with it: cut 3 deep, raise 5…" maxlength="200" value="${esc(S.sketchRole)}"></div>
    <div class="line"><span style="flex:1"></span><button data-act="sketchcancel">Cancel</button><button class="primary" data-act="sketchsave" ${sk.curves.length ? '' : 'disabled'}>Save sketch</button></div>
    <p class="muted">Saved as a tag in the Note. It holds as long as this face is still there.</p>`);
}

function renderPanel(force) {
  const panel = $('#panel');
  if (!force && panel.contains(document.activeElement) && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) { S.stale = true; return; }
  S.stale = false;
  const d = S.data;
  if (!d) { panel.innerHTML = '<div class="card"><h2>No Note open</h2><p class="muted">Connect your agent and ask it for a part. It appears here as soon as it is written.</p></div>'; return; }
  if (d.error) { panel.innerHTML = `<div class="card"><h2>${esc(S.note)}</h2><p class="err">${esc(d.error)}</p></div>`; return; }
  const r = d.report, cards = [];
  const pill = !d.is_note ? '<span class="pill muted">module</span>' : !r.built ? '<span class="pill err">does not build</span>'
    : r.green ? '<span class="pill ok">green</span>' : '<span class="pill err">red</span>';
  cards.push(card('note', `<h2>${esc(S.note)}</h2>`, `${r && !r.built ? `<p class="err mono">${esc(r.error)}</p>` : ''}${d.doc ? `<pre class="doc">${esc(d.doc)}</pre>` : '<p class="muted">No description.</p>'}`, pill));
  if (S.room === 'sketch') { panel.innerHTML = cards.join('') + (d.is_note && r.built ? sketchCards() : '<div class="card"><p class="muted">This Note does not build: there is nothing to draw on.</p></div>'); return; }

  if (S.compare) {
    const s = S.compare.summary;
    cards.push(card('compare', `Compare v${S.compare.a} → ${S.compare.b === 'draft' ? 'draft' : 'v' + S.compare.b}`, `
      ${s.same ? `<p class="ok">The same within ${s.tolerance} mm (the printer's tolerance).</p>` : ''}
      ${row('removed, at most', `<span style="color:#e23d2d">${s.removed.max_mm} mm</span>`)}${row('added, at most', `<span style="color:#28a85c">${s.added.max_mm} mm</span>`)}
      ${row('volume', `${s.numbers.volume_cm3[0]} → ${s.numbers.volume_cm3[1]} cm³`)}${row('size', `${fmt(s.numbers.size[0])} → ${fmt(s.numbers.size[1])}`)}
      ${s.tags.map((t) => `<div class="check"><b>${esc(t.tag)}</b><div class="why">${esc(t.change)}</div></div>`).join('') || '<p class="muted">No tagged feature changed.</p>'}
      <p class="muted">Grey is unchanged; colour starts at ${s.tolerance} mm.</p>`));
  }

  if (d.is_note && r.built && S.parts.length > 1 && !S.compare) {
    const known = new Set(S.proj.notes.filter((n) => n.kind !== 'module').map((n) => n.name));
    cards.push(card('assembly', `Assembly · ${S.parts.length} parts`, `
      ${S.parts.map((q, i) => `<div class="check part ${S.sel.part.has(i) ? 'sel' : ''}" data-part="${i}"><div class="row">
        <span><span class="swatch" style="background:${PARTS[i % PARTS.length]}"></span><b class="${S.hidden.has(i) ? 'muted' : ''}">${esc(q.name)}</b></span>
        <span class="v muted">${fmt(q.volume / 1000)} cm³</span>
        ${known.has(q.name) ? `<button class="x" data-act="opennote" data-name="${esc(q.name)}" title="open this part's Note">↗</button>` : ''}
        <button class="x" data-act="solo" data-i="${i}" title="show only this part">◎</button>
        <button class="x" data-act="eye" data-i="${i}" title="${S.hidden.has(i) ? 'show' : 'hide'}">${S.hidden.has(i) ? '○' : '●'}</button></div>
        <div class="why mono">${[0, 1, 2].map((k) => fmt(q.bbox[k + 3] - q.bbox[k])).join(' × ')} mm</div></div>`).join('')}
      <p class="muted">Click a part here or in the view. Explode (above the view) pulls them apart.</p>`, S.hidden.size ? '<button data-act="showall">Show all</button>' : ''));
  }

  if (d.is_note && r.built) {
    const m = r.measure;
    if (!S.compare) cards.push(selectionCard());
    cards.push(card('part', S.room === 'assembly' ? 'Assembly, as a whole' : 'Part', `${row('size', `${fmt(m.size_x)} × ${fmt(m.size_y)} × ${fmt(m.size_z)} mm`)}
      ${row('volume', `${fmt(m.volume_cm3)} cm³`)}${row('surface', `${fmt(m.area_cm2)} cm²`)}${row('z', `${fmt(m.min_z)} … ${fmt(m.max_z)}`)}${row('solids', m.solids)}
      ${Object.entries(d.params).map(([k, v]) => row(k, fmt(v))).join('')}`));

    const targets = S.parts.length > 1 ? [...S.sel.part].map((i) => S.parts[i].name) : [S.note];
    const first = lookOf(S.parts.length > 1 ? ([...S.sel.part][0] ?? 0) : 0);
    cards.push(card('look', 'Look', S.parts.length > 1 && !targets.length
      ? `<p class="muted">Select objects (the Objects selector, or the parts list) to give them a material and a colour.</p>
         ${S.parts.map((q, i) => { const l = lookOf(i); return `<div class="row"><span class="k"><span class="swatch" style="background:${l.color}"></span>${esc(q.name)}</span><span class="v muted">${esc(MATERIALS[l.material].name)}</span></div>`; }).join('')}`
      : `<p class="muted" style="margin-top:0">${S.parts.length > 1 ? `For ${targets.map(esc).join(', ')}` : 'What this part is made of'}${look.style === 'rendered' ? '' : ' (shown in the Rendered style)'}.</p>
         <div class="line"><select id="lookMaterial">${Object.entries(MATERIALS).map(([k, m]) => `<option value="${k}" ${k === first.material ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>
           <input type="color" id="lookColor" value="${esc(first.color)}" title="colour"><button data-act="lookreset" title="the material's own colour">Reset</button></div>
         ${first.material === 'pla' ? '<p class="muted">Printed: 0.2 mm layers on the walls, 0.4 mm lines on tops and bottoms. Zoom in to see them.</p>' : ''}`,
    `<span class="muted">${esc(MATERIALS[first.material].name)}</span>`));

    const tags = Object.entries(d.tags);
    cards.push(card('tags', `Tags · ${tags.length}`, tags.map(([name, t], n) => {
      const res = r.tags[name];
      return `<div class="check tag ${S.tagSel === name ? 'sel' : ''}" data-tag="${esc(name)}"><div class="row"><span><span class="swatch" style="background:${PALETTE[n % PALETTE.length]}"></span><b>${esc(name)}</b>
        ${res?.resolved ? '' : '<span class="err"> not found</span>'}</span><span class="v muted">${esc(t.kind)}</span>
        ${t.kind === 'sketch' ? `<button class="x" data-act="editsketch" data-name="${esc(name)}" title="open this sketch">✎</button>` : ''}<button class="x" data-act="untag" data-name="${esc(name)}" title="remove this tag">×</button></div>
        <div class="why">${esc(t.role ?? '')}${res?.why ? ` · ${esc(res.why)}` : ''}</div>
        <div class="why mono">${Object.entries(res?.measure ?? {}).map(([k, v]) => `${k} ${fmt(v)}`).join(' · ')}</div></div>`;
    }).join('') || '<p class="muted">No tags yet. Select something and name it.</p>'));

    const names = [...Object.keys(m), 'fits_bed', ...Object.entries(r.tags).flatMap(([k, t]) => Object.keys(t.measure).map((x) => `tag.${k}.${x}`))];
    const failing = r.checks.filter((c) => !c.ok).length;
    cards.push(card('checks', `Checks · ${r.checks.length}`, `<p class="muted" style="margin-top:0">Yours: the agent can add one, never change or remove one.</p>
      ${r.checks.map((c) => `<div class="check"><div class="row"><span class="${c.ok ? 'ok' : 'err'}">${c.ok ? '✓' : '✗'} <span class="mono">${esc(c.what)}</span></span>
        <span class="v">${fmt(c.value)} <span class="muted">(${esc(c.expect)})</span></span>${c.by === 'monet' ? '' : `<button class="x" data-act="uncheck" data-id="${esc(c.id)}" title="remove this check">×</button>`}</div>
        <div class="why">${esc(c.why || '')}${c.by === 'agent' ? ' · added by the agent' : ''}${c.note ? ` · ${esc(c.note)}` : ''}</div></div>`).join('')}
      <div class="line"><input id="ckWhat" list="measures" placeholder="what: size_x, tag.bore.width…"><datalist id="measures">${names.map((x) => `<option value="${esc(x)}">`).join('')}</datalist></div>
      <div class="line"><input id="ckMin" placeholder="min" inputmode="decimal"><input id="ckMax" placeholder="max" inputmode="decimal"><input id="ckEq" placeholder="or equals"></div>
      <div class="line"><input id="ckWhy" placeholder="why: the rule in your words"><button data-act="check">Add</button></div>`,
    failing ? `<span class="pill err">${failing} failing</span>` : '<span class="pill ok">all pass</span>'));

    const lc = d.load_check, colour = { green: 'ok', yellow: 'warn', red: 'err', new: 'muted' }[lc.status];
    cards.push(card('load', 'Load check', `
      ${lc.status === 'new' ? '<p class="muted">Nothing saved yet to compare with.</p>' : `<p class="muted">The saved Note, rebuilt just now, compared with what was saved${lc.version ? ` (v${lc.version})` : ''}.</p>`}
      ${(lc.changes ?? []).map((c) => `<div class="why ${c.level === 'red' ? 'err' : 'warn'}">${esc(c.what)}${c.delta != null ? ` ${c.delta > 0 ? '+' : ''}${c.delta}` : ''}${c.why ? ` · ${esc(c.why)}` : ''}</div>`).join('')}
      ${lc.status === 'red' || lc.status === 'yellow' ? (lc.acknowledged ? `<p class="muted">You looked at this on ${new Date(lc.acknowledged).toLocaleString()}.</p>`
        : `<div class="line"><span class="muted" style="flex:1">${lc.status === 'red' ? 'The agent may not edit this Note until you have looked.' : 'Within print tolerance; probably a library update.'}</span><button data-act="ack">I have looked</button></div>`) : ''}`,
    `<span class="pill ${colour}">${esc(lc.status === 'new' ? 'never saved' : lc.status)}</span>`));
  }

  const red = S.saveResult && !S.saveResult.saved ? Object.entries(S.saveResult.red).map(([k, v]) => `<div class="why err"><b>${esc(k)}</b>: ${esc(Array.isArray(v) ? v.join('; ') : v)}</div>`).join('') : '';
  cards.push(card('save', 'Save the project as a version', `
    <div class="line" style="margin-top:0"><input id="saveMsg" placeholder="what changed, and why" value="${esc(S.message)}"><button class="primary" data-act="save">Save</button></div>
    ${S.saveResult?.saved ? `<p class="ok">Saved as v${S.saveResult.version}.</p>` : red ? `<p class="err">Nothing is saved on red.</p>${red}` : ''}
    <p class="muted">Every Note must build and pass its checks. History is your own git folder: your agent commits there after each save.</p>`));

  if (d.is_note && r.built) {
    const v = S.compare && S.compare.b !== 'draft' ? `?v=${S.compare.b}` : '';
    cards.push(card('export', `Export ${v ? 'v' + S.compare.b : 'the draft'}`, `<div class="line" style="margin-top:0">
      ${['3mf', 'stl', 'step', 'glb'].map((f) => `<a href="${root}/p/${S.project}/n/${S.note}/export.${f}${v}" download><button>${f.toUpperCase()}</button></a>`).join('')}</div>`));
  }
  cards.push(card('source', `The Note: ${esc(S.note)}.py`, `<pre class="src mono">${esc(d.source)}</pre>`));
  panel.innerHTML = cards.join('');
}

const act = async (fn) => { try { await fn(); await open(S.project, S.note); } catch (e) { alert(e.message); busy(); } };
$('#panel').addEventListener('focusout', () => { if (S.stale) setTimeout(() => renderPanel(), 50); });
$('#panel').addEventListener('input', (e) => {
  if (e.target.id === 'saveMsg') S.message = e.target.value;
  if (e.target.id === 'sketchName') S.sketchName = e.target.value;
  if (e.target.id === 'sketchRole') S.sketchRole = e.target.value;
});
// material and colour: saved in the project, shown at once
async function setLook(change) {
  const names = S.parts.length > 1 ? [...S.sel.part].map((i) => S.parts[i].name) : [S.note];
  try {
    S.proj.looks = (await api(`/p/${S.project}/looks`, 'PUT', { names, ...change })).looks;
    S.rev = (await api(`/p/${S.project}/rev`)).rev;      // our own change: nothing to load again
    dress(); renderPanel(true);
  } catch (e) { alert(e.message); }
}
$('#panel').addEventListener('change', (e) => {
  if (e.target.id === 'lookMaterial') setLook({ material: e.target.value, color: null });
  if (e.target.id === 'lookColor') setLook({ color: e.target.value });
});
$('#panel').addEventListener('mouseover', (e) => {
  const t = e.target.closest('[data-tag]'), q = e.target.closest('[data-part]');
  const hot = t ? t.dataset.tag : null, hotPart = q ? Number(q.dataset.part) : null;
  if (hot !== S.hot || hotPart !== S.hotPart) { S.hot = hot; S.hotPart = hotPart; paint(); showTag(); }
});
$('#panel').addEventListener('mouseleave', () => { if (S.hot || S.hotPart != null) { S.hot = S.hotPart = null; paint(); showTag(); } });
$('#panel').addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (!b) {
    const f = e.target.closest('[data-fold]');
    if (f) { fold(f.dataset.fold); return; }
    const t = e.target.closest('[data-tag]');     // a click on a tag holds it: it stays lit, through the part, until clicked again
    if (t) { S.tagSel = S.tagSel === t.dataset.tag ? null : t.dataset.tag; paint(); showTag(); renderPanel(true); return; }
    const q = e.target.closest('[data-part]');   // a click on a part's row selects that part, with Shift and Ctrl as in the view
    if (q) select([{ kind: 'part', i: Number(q.dataset.part) }], { add: e.shiftKey, remove: e.ctrlKey || e.metaKey || (!e.shiftKey && S.sel.part.has(Number(q.dataset.part)) && count() === 1) });
    return;
  }
  const a = b.dataset.act;
  if (a === 'clear') { select([], {}); return; }
  if (a === 'lookreset') { setLook({ color: null }); return; }
  if (a === 'sketchhere') { startSketch({ face: theFace() }); return; }
  if (a === 'editsketch') { startSketch({ tag: S.data.tags[b.dataset.name], name: b.dataset.name }); return; }
  if (a === 'uncurve') { sketch.remove(Number(b.dataset.i)); return; }
  if (a === 'sketchcancel') { leaveSketch(); return; }
  if (a === 'sketchsave') {
    const name = S.sketchName.trim(), drawing = sketch.drawing(), face = sketch.state.face;
    act(async () => {
      busy('building…');
      await api(`/p/${S.project}/n/${S.note}/tags`, 'POST', { name, role: S.sketchRole, sketch: drawing, face });
      sketch.end(); S.room = 'part'; S.tagSel = name;
    });
    return;
  }
  // the parts of an assembly: nothing here goes to the server
  if (['eye', 'solo', 'showall'].includes(a)) {
    const i = Number(b.dataset.i);
    if (a === 'showall') S.hidden = new Set();
    else if (a === 'eye') (S.hidden.has(i) ? S.hidden.delete(i) : S.hidden.add(i));
    else S.hidden = new Set(S.parts.map((_, k) => k).filter((k) => k !== i));
    spread(); renderPanel(true);
    return;
  }
  if (a === 'opennote') { open(S.project, b.dataset.name); return; }
  const n = `/p/${S.project}/n/${S.note}`, num = (id) => ($(id).value.trim() === '' ? null : Number($(id).value.replace(',', '.')));
  if (a === 'tag') act(async () => {
    const name = $('#tagName').value.trim();
    busy('building…');
    await api(`${n}/tags`, 'POST', { name, role: $('#tagRole').value, items: selectedItems() });
    S.tagSel = name;      // show what was just named
  });
  if (a === 'untag' && confirm(`Remove the tag "${b.dataset.name}" from the Note? Checks about it will fail.`)) act(() => api(`${n}/tags/${b.dataset.name}`, 'DELETE'));
  if (a === 'uncheck' && confirm(`Remove the check "${b.dataset.id}"?`)) act(() => api(`${n}/checks/${b.dataset.id}`, 'DELETE'));
  if (a === 'check') act(() => {
    const eq = $('#ckEq').value.trim().toLowerCase();
    return api(`${n}/checks`, 'POST', { what: $('#ckWhat').value.trim(), min: num('#ckMin'), max: num('#ckMax'), why: $('#ckWhy').value,
      equals: eq === '' ? null : eq === 'true' ? true : eq === 'false' ? false : Number(eq) });
  });
  if (a === 'ack') act(() => api(`${n}/ack`, 'POST', {}));
  if (a === 'save') act(async () => { busy('building every Note…'); S.saveResult = await api(`/p/${S.project}/save`, 'POST', { message: S.message }); if (S.saveResult.saved) S.message = ''; });
});

// ---- projects, the agent, the start ------------------------------------------------------------------------
$('#project').onchange = (e) => open(e.target.value, null);
$('#newProject').onclick = () => {
  const dlg = $('#connectDialog');
  dlg.innerHTML = `<h2>New project</h2><form method="dialog"><div class="line"><input id="npName" placeholder="name: lowercase, digits, dashes" required pattern="[a-z0-9][a-z0-9_-]*">
    <select id="npTemplate"><option value="">empty</option>${S.state.templates.map((t) => `<option value="${esc(t)}">copy of ${esc(t)}</option>`).join('')}</select></div>
    <div class="line"><span style="flex:1"></span><button value="no">Cancel</button><button class="primary" value="yes">Create</button></div></form>`;
  dlg.onclose = async () => {
    if (dlg.returnValue !== 'yes') return;
    try { const { project } = await api('/projects', 'POST', { name: $('#npName').value.trim(), template: $('#npTemplate').value }); await start(project); } catch (e) { alert(e.message); }
  };
  dlg.showModal();
};
$('#connect').onclick = () => {
  const base = S.state.base, dlg = $('#connectDialog'), local = /\/\/(localhost|127\.0\.0\.1)/.test(base);
  dlg.onclose = null;
  dlg.innerHTML = `<h2>Connect your agent</h2>
    <p class="muted">The thinking happens on your computer, with your own model. This page builds, checks, shows and exports.
    Your workspace link is your key: whoever has it can use this workspace. Keep it; there is no other login.</p>
    <pre>${esc(base)}</pre>
    <h3>1 · Claude Desktop</h3>
    ${local ? `<p>This server runs on your own computer, which Claude's connectors cannot reach. Add it to
      <code>claude_desktop_config.json</code> (Settings → Developer → Edit Config) instead, then restart Claude:</p>
      <pre>{ "mcpServers": { "monet": { "command": "npx", "args": ["-y", "mcp-remote", "${esc(base)}/mcp"] } } }</pre>`
    : `<p>Settings → Connectors → Add custom connector. Name <code>Monet</code>, URL:</p><pre>${esc(base)}/mcp</pre>`}
    <p>Then the skill, so Claude knows how to work here: <a href="/skill.zip">download monet-skill.zip</a> and add it in
      Settings → Capabilities → Skills.</p>
    <h3>Or Claude Code</h3>
    <pre>claude mcp add --transport http monet ${esc(base)}/mcp</pre>
    <h3>Or any LLM that can open web addresses</h3>
    <p>Everything is also plain HTTPS, by GET or POST. Paste this to it:</p>
    <pre>Read ${esc(location.origin)}/api and work in my Monet workspace: ${esc(base)}</pre>
    <h3>2 · A folder of your own, with git</h3>
    <p>Make a folder for the project on your computer and let the agent keep the Notes there, with <code>git init</code>.
      It commits after every successful save, so the history is yours and survives this server.</p>
    <h3>3 · Say what you want</h3>
    <p>"Use Monet. Open the project mg400_rakis and show me the nest." Then point at faces here and describe the change.</p>
    <form method="dialog"><div class="line"><span style="flex:1"></span><button>Close</button></div></form>`;
  dlg.showModal();
};

async function start(project) {
  S.state = await api('/state');
  $('#wsName').textContent = S.state.workspace.name || '';
  $('#project').innerHTML = S.state.projects.map((p) => `<option>${esc(p)}</option>`).join('');
  const [hp, hn] = decodeURIComponent(location.hash.slice(1)).split('/');
  const want = project || (S.state.projects.includes(hp) ? hp : S.state.projects[0]);
  if (want) await open(want, project ? null : hn);
  else renderPanel(true);
}

// follow the agent: when the project moves, look again
setInterval(async () => {
  if (!S.project || document.hidden || !$('#busy').hidden || press) return;
  try { const { rev } = await api(`/p/${S.project}/rev`); if (rev !== S.rev && !S.compare) await open(S.project, S.note); } catch { /* the server is away; try again */ }
}, 2000);
window.addEventListener('hashchange', () => { const [p, n] = decodeURIComponent(location.hash.slice(1)).split('/'); if (p && (p !== S.project || (n && n !== S.note))) open(p, n); });

window.monet = { S, groups, camera, scene, holo, drawn, look, sketch, select, pick, boxPick, goRoom };   // for looking in from the console, and from scripts/shot.mjs
resize();
start().catch((e) => { $('#panel').innerHTML = `<div class="card"><p class="err">${esc(e.message)}</p></div>`; });

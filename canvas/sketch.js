// Sketching: a drawing on a plane of the part, the way a sketch is made in Fusion. The user picks a plane (or a flat
// face), the view turns to look straight at it, and curves are drawn on it in millimetres. The drawing is saved as
// a tag (kind "sketch") in the Note, where the user's agent reads it and makes geometry of it.
//
// The plane and the snapping follow Adam Designer: plane-local u, v in mm; a point snaps first to line up with
// other points (pink guides, within 8 px), then to the grid; Shift lets it go free. Its offset, trim, fillet and
// three-click oval are here too (the geometry of them in sketch2d.js). New here: the plane sits on a face, there
// is a rectangle, and the segment being drawn follows the cursor.
import * as THREE from 'three';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { fillet, flatten, lengthOf, nearest, nearestCorner, offset, ovalThrough, toPath, trim } from './sketch2d.js';

const INK = 0x5fd0ff, PINK = 0xff4fd8, RED = 0xff5c5c, CLOSE_PX = 10, ALIGN_PX = 8;
const r3 = (v) => Math.round(v * 1000) / 1000;
export const DRAWING = ['line', 'rect', 'circle', 'oval'], EDITING = ['offset', 'trim', 'fillet'];

/** The frame of a plane on a face: where u and v point. Its origin is the point of the plane nearest the part's own
 * origin, so on a face square to the axes u and v are the part's own coordinates. */
export function frameOf(normal, centre) {
  const n = new THREE.Vector3(...normal).normalize();
  const x = Math.abs(n.z) > 0.999 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1).cross(n).normalize();
  const origin = n.clone().multiplyScalar(n.dot(new THREE.Vector3(...centre)));
  return { origin: origin.toArray().map(r3), normal: n.toArray().map(r3), x: x.toArray().map(r3) };
}

/** The same, as vectors to work with: origin, x, y (= normal × x), normal. */
export function basis(plane) {
  const origin = new THREE.Vector3(...plane.origin), normal = new THREE.Vector3(...plane.normal).normalize(), x = new THREE.Vector3(...plane.x).normalize();
  return { origin, normal, x, y: normal.clone().cross(x).normalize() };
}

/** A curve of a sketch as points in the world: [[x, y, z], ...], closed ones ending where they began. */
export function outline(curve, b) {
  return flatten(curve).map(([u, v]) => b.origin.clone().addScaledVector(b.x, u).addScaledVector(b.y, v).toArray());
}

/** Thick lines through runs of points, drawn over everything. */
export function strokes(runs, colour, width = 2.5, opacity = 1) {
  const pos = [];
  for (const run of runs) for (let i = 0; i + 1 < run.length; i++) pos.push(...run[i], ...run[i + 1]);
  const l = new LineSegments2(new LineSegmentsGeometry().setPositions(pos.length ? pos : [0, 0, 0, 0, 0, 0]),
    new LineMaterial({ color: colour, linewidth: width, depthTest: false, transparent: true, opacity, toneMapped: false }));
  l.visible = pos.length > 0;
  l.renderOrder = 9; l.frustumCulled = false;
  return l;
}

// Adam Designer's alignment snap (model/snap.ts): x and y each take the coordinate of the nearest candidate within tol
function alignSnap(p, candidates, tol) {
  let bx = null, by = null, dx = tol, dy = tol;
  for (const c of candidates) {
    const ex = Math.abs(c[0] - p[0]), ey = Math.abs(c[1] - p[1]);
    if (ex <= dx) { dx = ex; bx = c; }
    if (ey <= dy) { dy = ey; by = c; }
  }
  return { point: [bx ? bx[0] : p[0], by ? by[1] : p[1]], guides: [bx && { axis: 'v', from: bx }, by && { axis: 'h', from: by }].filter(Boolean) };
}

/** A curve in words. */
export function describe(c) {
  if (c.type === 'rect') return `rectangle ${r3(c.size[0])} × ${r3(c.size[1])} mm at ${c.at.map(r3).join(', ')}`;
  if (c.type === 'circle') return `circle ⌀ ${r3(2 * c.r)} mm, centre ${c.center.map(r3).join(', ')}`;
  if (c.type === 'ellipse') return `oval ${r3(2 * c.rx)} × ${r3(2 * c.ry)} mm${c.rotation ? `, turned ${r3(c.rotation)}°` : ''}, centre ${c.center.map(r3).join(', ')}`;
  const arcs = c.points.filter((p) => p[2]).length;
  if (c.points.length === 2) return `${arcs ? 'arc' : 'line'}, ${r3(lengthOf(c))} mm, from ${c.points[0].slice(0, 2).map(r3).join(', ')} to ${c.points[1].slice(0, 2).map(r3).join(', ')}`;
  return `${c.closed ? 'closed outline' : 'open line'} of ${c.points.length} points${arcs ? `, ${arcs} of them rounded` : ''}, ${r3(lengthOf(c))} mm round`;
}

// the points a curve offers to line up with
const marks = (c) => (c.type === 'rect' ? [c.at, [c.at[0] + c.size[0], c.at[1] + c.size[1]]] : c.type === 'circle' || c.type === 'ellipse' ? [c.center] : c.points.map((p) => [p[0], p[1]]));

/**
 * The sketcher of one view. `host` gives it the view: {scene, camera, controls, canvas, view, corners() → the part's
 * corner points [[x, y, z]], changed() → called when the drawing changes}.
 */
export function createSketcher(host) {
  const { scene, camera, controls, canvas, view } = host;
  const group = new THREE.Group();
  scene.add(group);
  const tip = document.createElement('div');
  tip.id = 'sketchTip';
  tip.hidden = true;
  view.appendChild(tip);
  const sk = { active: false, plane: null, planeName: null, face: null, on: null, editing: null, curves: [], history: [], tool: 'line', value: 2,
    draft: null, cursor: null, bare: null, guides: [], grid: 1, snap: true, message: '' };
  let b = null, candidates = [], before = null, extent = 100;

  const mmPerPx = () => (camera.top - camera.bottom) / camera.zoom / view.clientHeight;
  const world = (u, v) => b.origin.clone().addScaledVector(b.x, u).addScaledVector(b.y, v);
  const toPlane = (p) => { const d = p.clone().sub(b.origin); return [d.dot(b.x), d.dot(b.y)]; };

  function onPlane(e) {     // where the cursor is on the plane, as it is
    const r = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(b.normal, b.origin), new THREE.Vector3());
    return hit ? toPlane(hit) : null;
  }

  function snapped(p, e) {  // and where a point placed there lands
    sk.guides = [];
    if (e.shiftKey || !sk.snap) return p.map((v) => Math.round(v * 10) / 10);
    const a = alignSnap(p, [...candidates, ...sk.curves.flatMap(marks), ...(sk.draft?.points ?? []), [0, 0]], ALIGN_PX * mmPerPx());
    sk.guides = a.guides;
    const q = a.point;
    if (!a.guides.some((g) => g.axis === 'v')) q[0] = Math.round(q[0] / sk.grid) * sk.grid;
    if (!a.guides.some((g) => g.axis === 'h')) q[1] = Math.round(q[1] / sk.grid) * sk.grid;
    return q.map(r3);
  }

  // what an editing tool would do where the cursor is: {curves} to become, {show} to preview, {hot} to mark, {error}
  function intent() {
    const p = sk.bare;
    if (!p || !sk.curves.length) return null;
    const reach = (px) => px * mmPerPx();
    if (sk.tool === 'trim') {
      const hit = nearest(sk.curves, p);
      return hit && hit.d <= reach(10) ? { curves: trim(sk.curves, hit), hot: sk.curves[hit.curve], at: hit.point } : null;
    }
    if (sk.tool === 'fillet') {
      const corner = nearestCorner(sk.curves, p);
      if (!corner || corner.d > reach(14)) return null;
      const done = fillet(sk.curves, corner, sk.value);
      return done.error ? { error: done.error, at: corner.point } : { curves: done.curves, show: done.curves[corner.curve], at: corner.point };
    }
    if (sk.tool === 'offset') {
      const hit = nearest(sk.curves, p);
      if (!hit || hit.d > reach(60) || hit.d < 1e-9) return null;
      const copy = offset(sk.curves[hit.curve], sk.value, p);
      return copy ? { curves: [...sk.curves, copy], show: copy } : { error: 'nothing is left of it that far in' };
    }
    return null;
  }

  function draw() {
    for (const o of [...group.children]) { o.geometry?.dispose(); o.material?.dispose(); }
    group.clear();
    if (!sk.active) { tip.hidden = true; return; }
    // the plane: a faint sheet with a 10 mm grid, and where its zero is
    const half = Math.ceil((extent * 0.75 + 20) / 10) * 10, size = half * 2;
    const turn = new THREE.Matrix4().makeBasis(b.x, b.y, b.normal).setPosition(b.origin);
    const grid = new THREE.GridHelper(size, size / 10, 0x4a5578, 0x303a55);
    grid.rotation.x = Math.PI / 2;
    for (const m of [].concat(grid.material)) { m.transparent = true; m.opacity = 0.7; m.depthTest = false; m.toneMapped = false; }
    const sheet = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ color: 0x5fd0ff, transparent: true, opacity: 0.05, depthTest: false, side: THREE.DoubleSide, toneMapped: false }));
    const local = new THREE.Group();
    local.add(sheet, grid);
    local.applyMatrix4(turn);
    local.renderOrder = 7;
    group.add(local);
    const w = (p) => world(p[0], p[1]).toArray();
    const arm = Math.min(half, 12);
    group.add(strokes([[w([0, 0]), w([arm, 0])]], 0xff6b6b, 2), strokes([[w([0, 0]), w([0, arm])]], 0x6bdc8a, 2));
    // what is drawn, what is being drawn, and what the cursor lines up with
    group.add(strokes(sk.curves.map((c) => outline(c, b)), INK, 3));
    const c = sk.cursor, d = sk.draft, dots = [...(d?.points ?? []), ...sk.guides.map((g) => g.from)];
    if (d && c) {
      const first = d.points[0];
      const live = d.type === 'line' ? { type: 'polyline', points: [...d.points, c] }
        : d.type === 'rect' ? { type: 'rect', at: [Math.min(first[0], c[0]), Math.min(first[1], c[1])], size: [Math.abs(c[0] - first[0]), Math.abs(c[1] - first[1])] }
          : d.type === 'circle' ? { type: 'circle', center: first, r: Math.hypot(c[0] - first[0], c[1] - first[1]) }
            : d.points.length === 1 ? { type: 'polyline', points: [first, c] } : (ovalThrough(first, d.points[1], c) ?? { type: 'polyline', points: [first, d.points[1]] });
      if (live.type !== 'rect' || (live.size[0] > 0 && live.size[1] > 0)) group.add(strokes([outline(live, b)], 0xffffff, 2, 0.9));
    }
    if (DRAWING.includes(sk.tool) && c) dots.push(c);
    const todo = EDITING.includes(sk.tool) ? intent() : null;
    if (todo?.hot) group.add(strokes([outline(todo.hot, b)], RED, 3, 0.9));
    if (todo?.show) group.add(strokes([outline(todo.show, b)], 0xffffff, 2.5, 0.95));
    if (todo?.at) dots.push(todo.at);
    const far = half * 2;
    group.add(strokes(sk.guides.map((g) => (g.axis === 'v' ? [w([g.from[0], -far]), w([g.from[0], far])] : [w([-far, g.from[1]]), w([far, g.from[1]])])), PINK, 1.2, 0.8));
    if (dots.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(dots.flatMap(w), 3));
      const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: todo?.error ? RED : 0xffffff, size: 8, sizeAttenuation: false, depthTest: false, transparent: true, toneMapped: false }));
      pts.renderOrder = 10; pts.frustumCulled = false;
      group.add(pts);
    }
    for (const o of group.children) if (o.material?.resolution) o.material.resolution.set(view.clientWidth, view.clientHeight);
    return todo;
  }

  function say(e, todo) {   // beside the cursor: where it is, the size of what is being drawn, or what the tool will do
    const c = sk.cursor, d = sk.draft;
    let text = null;
    if (EDITING.includes(sk.tool)) {
      text = todo?.error ?? (sk.tool === 'trim' ? (todo ? 'trim' : null) : todo ? `${sk.tool === 'fillet' ? 'r ' : ''}${r3(sk.value)} mm` : null);
    } else if (c) {
      const last = d?.points[d.points.length - 1];
      text = !d ? `${r3(c[0])}, ${r3(c[1])}`
        : d.type === 'line' ? `${r3(Math.hypot(c[0] - last[0], c[1] - last[1]))} mm`
          : d.type === 'rect' ? `${r3(Math.abs(c[0] - last[0]))} × ${r3(Math.abs(c[1] - last[1]))} mm`
            : d.type === 'circle' ? `⌀ ${r3(2 * Math.hypot(c[0] - last[0], c[1] - last[1]))} mm`
              : d.points.length === 1 ? `${r3(Math.hypot(c[0] - last[0], c[1] - last[1]))} mm long` : (() => { const o = ovalThrough(d.points[0], d.points[1], c); return o ? `${r3(2 * o.rx)} × ${r3(2 * o.ry)} mm` : ''; })();
    }
    if (!text) { tip.hidden = true; return; }
    const r = view.getBoundingClientRect();
    tip.textContent = text;
    tip.classList.toggle('err', !!todo?.error);
    tip.style.transform = `translate(${e.clientX - r.left + 14}px, ${e.clientY - r.top + 14}px)`;
    tip.hidden = false;
  }

  function become(curves) {     // the drawing changes: what it was is kept, to go back to
    sk.history.push(JSON.stringify(sk.curves));
    if (sk.history.length > 100) sk.history.shift();
    sk.curves = curves;
    sk.draft = null; sk.message = '';
    draw(); host.changed();
  }

  function press(e) {
    sk.bare = onPlane(e);
    if (!sk.bare) return;
    if (EDITING.includes(sk.tool)) {
      const todo = intent();
      if (todo?.curves) become(todo.curves);
      else if (todo?.error) { sk.message = todo.error; host.changed(); }
      return;
    }
    const p = snapped(sk.bare, e), d = sk.draft;
    if (!d) { sk.draft = { type: sk.tool === 'oval' ? 'oval' : sk.tool, points: [p] }; sk.message = ''; draw(); host.changed(); return; }
    const first = d.points[0];
    if (d.type === 'rect') {
      const size = [r3(Math.abs(p[0] - first[0])), r3(Math.abs(p[1] - first[1]))];
      if (size[0] > 0 && size[1] > 0) become([...sk.curves, { type: 'rect', at: [Math.min(p[0], first[0]), Math.min(p[1], first[1])].map(r3), size }]);
      return;
    }
    if (d.type === 'circle') {
      const r = r3(Math.hypot(p[0] - first[0], p[1] - first[1]));
      if (r > 0) become([...sk.curves, { type: 'circle', center: first, r }]);
      return;
    }
    if (d.type === 'oval') {      // two clicks: the ends of one axis; the third: how far the other reaches
      if (d.points.length === 1) { if (Math.hypot(p[0] - first[0], p[1] - first[1]) > 0) d.points.push(p); draw(); host.changed(); return; }
      const oval = ovalThrough(first, d.points[1], p);
      if (oval) become([...sk.curves, oval]);
      return;
    }
    // a line: a click on its first point closes it; a click on its last point ends it open
    const px = (q) => Math.hypot(p[0] - q[0], p[1] - q[1]) / mmPerPx();
    if (d.points.length >= 3 && px(first) <= CLOSE_PX) return become([...sk.curves, { type: 'polyline', points: d.points, closed: true }]);
    if (d.points.length >= 2 && px(d.points[d.points.length - 1]) <= 2) return become([...sk.curves, { type: 'polyline', points: d.points, closed: false }]);
    d.points.push(p);
    draw(); host.changed();
  }

  const api = {
    state: sk,
    describe,
    /** Start drawing: on a plane (one of the part's, with its name), on a face {normal, center} directly, or on the
     * plane of a sketch there already is (tag, name). */
    begin({ face = null, tag = null, name = null, plane = null, planeName = null, on = null }) {
      sk.plane = tag ? tag.plane : plane ?? frameOf(face.normal, face.center);
      sk.curves = tag ? JSON.parse(JSON.stringify(tag.curves ?? [])) : [];
      sk.on = tag?.on ?? on ?? null; sk.face = face; sk.editing = name; sk.role = tag?.role ?? '';
      sk.planeName = tag?.plane_name ?? planeName ?? null;
      sk.draft = null; sk.cursor = null; sk.bare = null; sk.guides = []; sk.history = []; sk.message = ''; sk.active = true;
      b = basis(sk.plane);
      candidates = host.corners().map((p) => toPlane(new THREE.Vector3(...p)));
      // look straight at the plane, with v up the page; remember where the view was
      before = { position: camera.position.clone(), up: camera.up.clone(), target: controls.target.clone(), zoom: camera.zoom };
      const box = new THREE.Box3();
      for (const p of host.corners()) box.expandByPoint(new THREE.Vector3(...p));
      const middle = box.isEmpty() ? b.origin.clone() : box.getCenter(new THREE.Vector3());
      extent = box.isEmpty() ? 100 : box.getSize(new THREE.Vector3()).length();
      const onIt = middle.clone().addScaledVector(b.normal, -b.normal.dot(middle.clone().sub(b.origin)));
      camera.up.copy(b.y);
      camera.position.copy(onIt).addScaledVector(b.normal, extent * 8 + 100);
      controls.target.copy(onIt);
      camera.zoom = Math.max(0.2, ((camera.top - camera.bottom) / (extent * 1.15)));
      camera.updateProjectionMatrix();
      controls.enableRotate = false;
      controls.update();
      draw(); host.changed();
    },
    /** Stop drawing and put the view back. */
    end() {
      if (!sk.active) return;
      sk.active = false; sk.draft = null; sk.cursor = null; sk.bare = null;
      controls.enableRotate = true;
      if (before) {
        camera.up.copy(before.up); camera.position.copy(before.position); controls.target.copy(before.target); camera.zoom = before.zoom;
        camera.updateProjectionMatrix(); controls.update();
      }
      draw(); host.changed();
    },
    setTool(tool) { sk.tool = tool; sk.draft = null; sk.message = ''; draw(); host.changed(); },
    setValue(v) { if (Number.isFinite(v) && v > 0) { sk.value = v; draw(); } },
    remove(i) { become(sk.curves.filter((_, k) => k !== i)); },
    /** Back to how the drawing was before the last change. */
    undo() {
      if (sk.draft) { sk.draft = null; draw(); host.changed(); return true; }
      if (!sk.history.length) return false;
      sk.curves = JSON.parse(sk.history.pop());
      sk.message = '';
      draw(); host.changed();
      return true;
    },
    /** What the drawing is, to be saved in the tag. */
    drawing() { return { plane: sk.plane, curves: sk.curves, ...(sk.on ? { on: sk.on } : {}), ...(sk.planeName ? { plane_name: sk.planeName } : {}) }; },
    // the pointer, while a sketch is being drawn: a click places a point; right-drag and the wheel still move the page
    down(e) { if (e.button === 0) { e.stopPropagation(); press(e); } },
    move(e) {
      sk.bare = onPlane(e);
      sk.cursor = sk.bare && DRAWING.includes(sk.tool) ? snapped(sk.bare, e) : null;
      if (!DRAWING.includes(sk.tool)) sk.guides = [];
      say(e, draw());
    },
    leave() { sk.cursor = null; sk.bare = null; tip.hidden = true; draw(); },
    key(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') return api.undo();
      if (e.key === 'Escape') { if (sk.draft) { sk.draft = null; draw(); host.changed(); return true; } return false; }
      if (e.key === 'Enter' && sk.draft?.type === 'line' && sk.draft.points.length >= 2) { become([...sk.curves, { type: 'polyline', points: sk.draft.points, closed: false }]); return true; }
      if (e.key === 'Backspace' && sk.draft?.points.length > 1) { sk.draft.points.pop(); draw(); host.changed(); return true; }
      return false;
    },
    resize() { for (const o of group.children) if (o.material?.resolution) o.material.resolution.set(view.clientWidth, view.clientHeight); },
  };
  return api;
}

export { toPath };

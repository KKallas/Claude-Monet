// Sketching: a drawing on a face of the part, the way a sketch is made in Fusion. The user picks a flat face, the
// view turns to look straight at it, and lines, rectangles and circles are drawn on that plane in millimetres.
// The drawing is saved as a tag (kind "sketch") in the Note, where the user's agent reads it and makes geometry of it.
//
// The plane and the snapping follow Adam Designer: plane-local u, v in mm; a point snaps first to line up with
// other points (pink guides, within 8 px), then to the grid; Shift lets it go free. New here: the plane sits on a
// face, there is a rectangle, and the segment being drawn follows the cursor.
import * as THREE from 'three';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

const INK = 0x5fd0ff, PINK = 0xff4fd8, CLOSE_PX = 10, ALIGN_PX = 8;
const r3 = (v) => Math.round(v * 1000) / 1000;

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
  const at = (u, v) => b.origin.clone().addScaledVector(b.x, u).addScaledVector(b.y, v).toArray();
  if (curve.type === 'rect') {
    const [u, v] = curve.at, [w, h] = curve.size;
    return [at(u, v), at(u + w, v), at(u + w, v + h), at(u, v + h), at(u, v)];
  }
  if (curve.type === 'circle') return Array.from({ length: 73 }, (_, i) => at(curve.center[0] + curve.r * Math.cos(i * Math.PI / 36), curve.center[1] + curve.r * Math.sin(i * Math.PI / 36)));
  const pts = (curve.points ?? []).map(([u, v]) => at(u, v));
  return curve.closed && pts.length > 2 ? [...pts, pts[0]] : pts;
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

const describe = (c) => (c.type === 'rect' ? `rectangle ${r3(c.size[0])} × ${r3(c.size[1])} mm at ${c.at.map(r3).join(', ')}`
  : c.type === 'circle' ? `circle ⌀ ${r3(2 * c.r)} mm, centre ${c.center.map(r3).join(', ')}`
    : `${c.closed ? 'closed outline' : 'open line'} of ${c.points.length} points`);

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
  const sk = { active: false, plane: null, face: null, on: null, editing: null, curves: [], tool: 'line', draft: null, cursor: null, guides: [], grid: 1, snap: true };
  let b = null, candidates = [], before = null, extent = 100;

  const mmPerPx = () => (camera.top - camera.bottom) / camera.zoom / view.clientHeight;
  const world = (u, v) => b.origin.clone().addScaledVector(b.x, u).addScaledVector(b.y, v);
  const toPlane = (p) => { const d = p.clone().sub(b.origin); return [d.dot(b.x), d.dot(b.y)]; };

  function under(e) {   // where the cursor is on the plane, snapped
    const r = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(b.normal, b.origin), new THREE.Vector3());
    if (!hit) return null;
    let p = toPlane(hit);
    sk.guides = [];
    if (e.shiftKey || !sk.snap) return p.map((v) => Math.round(v * 10) / 10);
    const own = sk.curves.flatMap((c) => (c.type === 'rect' ? [c.at, [c.at[0] + c.size[0], c.at[1] + c.size[1]]] : c.type === 'circle' ? [c.center] : c.points));
    const a = alignSnap(p, [...candidates, ...own, ...(sk.draft?.points ?? []), [0, 0]], ALIGN_PX * mmPerPx());
    sk.guides = a.guides;
    p = a.point;
    if (!a.guides.some((g) => g.axis === 'v')) p[0] = Math.round(p[0] / sk.grid) * sk.grid;
    if (!a.guides.some((g) => g.axis === 'h')) p[1] = Math.round(p[1] / sk.grid) * sk.grid;
    return p.map(r3);
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
    const c = sk.cursor, d = sk.draft;
    if (d && c) {
      const live = d.type === 'line' ? { type: 'polyline', points: [...d.points, c] }
        : d.type === 'rect' ? { type: 'rect', at: [Math.min(d.points[0][0], c[0]), Math.min(d.points[0][1], c[1])], size: [Math.abs(c[0] - d.points[0][0]), Math.abs(c[1] - d.points[0][1])] }
          : { type: 'circle', center: d.points[0], r: Math.hypot(c[0] - d.points[0][0], c[1] - d.points[0][1]) };
      group.add(strokes([outline(live, b)], 0xffffff, 2, 0.9));
    }
    const far = half * 2;
    group.add(strokes(sk.guides.map((g) => (g.axis === 'v' ? [w([g.from[0], -far]), w([g.from[0], far])] : [w([-far, g.from[1]]), w([far, g.from[1]])])), PINK, 1.2, 0.8));
    const dots = [...(d?.points ?? []), ...(c ? [c] : []), ...sk.guides.map((g) => g.from)].flatMap(w);
    if (dots.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(dots, 3));
      const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 8, sizeAttenuation: false, depthTest: false, transparent: true, toneMapped: false }));
      pts.renderOrder = 10; pts.frustumCulled = false;
      group.add(pts);
    }
    for (const o of group.children) if (o.material?.resolution) o.material.resolution.set(view.clientWidth, view.clientHeight);
  }

  function say(e) {   // beside the cursor: where it is, and the size of what is being drawn
    const c = sk.cursor, d = sk.draft;
    if (!c) { tip.hidden = true; return; }
    const last = d?.points[d.points.length - 1];
    const text = !d ? `${r3(c[0])}, ${r3(c[1])}`
      : d.type === 'line' ? `${r3(Math.hypot(c[0] - last[0], c[1] - last[1]))} mm`
        : d.type === 'rect' ? `${r3(Math.abs(c[0] - last[0]))} × ${r3(Math.abs(c[1] - last[1]))} mm`
          : `⌀ ${r3(2 * Math.hypot(c[0] - last[0], c[1] - last[1]))} mm`;
    const r = view.getBoundingClientRect();
    tip.textContent = text;
    tip.style.transform = `translate(${e.clientX - r.left + 14}px, ${e.clientY - r.top + 14}px)`;
    tip.hidden = false;
  }

  function finish(curve) {
    sk.draft = null;
    if (curve) sk.curves.push(curve);
    draw(); host.changed();
  }

  function press(e) {
    const p = under(e);
    if (!p) return;
    const d = sk.draft;
    if (!d) { sk.draft = { type: sk.tool, points: [p] }; draw(); host.changed(); return; }
    const first = d.points[0];
    if (d.type === 'rect') {
      const size = [r3(Math.abs(p[0] - first[0])), r3(Math.abs(p[1] - first[1]))];
      return finish(size[0] > 0 && size[1] > 0 ? { type: 'rect', at: [Math.min(p[0], first[0]), Math.min(p[1], first[1])].map(r3), size } : null);
    }
    if (d.type === 'circle') {
      const r = r3(Math.hypot(p[0] - first[0], p[1] - first[1]));
      return finish(r > 0 ? { type: 'circle', center: first, r } : null);
    }
    // a line: a click on its first point closes it; a click on its last point ends it open
    const px = (q) => Math.hypot(p[0] - q[0], p[1] - q[1]) / mmPerPx();
    if (d.points.length >= 3 && px(first) <= CLOSE_PX) return finish({ type: 'polyline', points: d.points, closed: true });
    if (d.points.length >= 2 && px(d.points[d.points.length - 1]) <= 2) return finish({ type: 'polyline', points: d.points, closed: false });
    d.points.push(p);
    draw(); host.changed();
  }

  const api = {
    state: sk,
    describe,
    /** Start drawing: on a face {normal, center, bbox} (a new sketch), or on the plane of a sketch there already is. */
    begin({ face = null, tag = null, name = null }) {
      sk.plane = tag ? tag.plane : frameOf(face.normal, face.center);
      sk.curves = tag ? JSON.parse(JSON.stringify(tag.curves ?? [])) : [];
      sk.on = tag?.on ?? null; sk.face = face; sk.editing = name; sk.role = tag?.role ?? '';
      sk.draft = null; sk.cursor = null; sk.guides = []; sk.active = true;
      b = basis(sk.plane);
      candidates = host.corners().map((p) => toPlane(new THREE.Vector3(...p)));
      // look straight at the plane, with v up the page; remember where the view was
      before = { position: camera.position.clone(), up: camera.up.clone(), target: controls.target.clone(), zoom: camera.zoom };
      const box = new THREE.Box3();
      for (const p of host.corners()) box.expandByPoint(new THREE.Vector3(...p));
      const middle = box.isEmpty() ? b.origin.clone() : box.getCenter(new THREE.Vector3());
      extent = box.isEmpty() ? 100 : box.getSize(new THREE.Vector3()).length();
      const onPlane = middle.clone().addScaledVector(b.normal, -b.normal.dot(middle.clone().sub(b.origin)));
      camera.up.copy(b.y);
      camera.position.copy(onPlane).addScaledVector(b.normal, extent * 8 + 100);
      controls.target.copy(onPlane);
      camera.zoom = Math.max(0.2, ((camera.top - camera.bottom) / (extent * 1.15)));
      camera.updateProjectionMatrix();
      controls.enableRotate = false;
      controls.update();
      draw(); host.changed();
    },
    /** Stop drawing and put the view back. */
    end() {
      if (!sk.active) return;
      sk.active = false; sk.draft = null; sk.cursor = null;
      controls.enableRotate = true;
      if (before) {
        camera.up.copy(before.up); camera.position.copy(before.position); controls.target.copy(before.target); camera.zoom = before.zoom;
        camera.updateProjectionMatrix(); controls.update();
      }
      draw(); host.changed();
    },
    setTool(tool) { sk.tool = tool; sk.draft = null; draw(); host.changed(); },
    remove(i) { sk.curves.splice(i, 1); draw(); host.changed(); },
    /** What the drawing is, to be saved in the tag. */
    drawing() { return { plane: sk.plane, curves: sk.curves, ...(sk.on ? { on: sk.on } : {}) }; },
    // the pointer, while a sketch is being drawn: a click places a point; right-drag and the wheel still move the page
    down(e) { if (e.button === 0) { e.stopPropagation(); press(e); } },
    move(e) { sk.cursor = under(e); draw(); say(e); },
    leave() { sk.cursor = null; tip.hidden = true; draw(); },
    key(e) {
      if (e.key === 'Escape') { if (sk.draft) { sk.draft = null; draw(); host.changed(); return true; } return false; }
      if (e.key === 'Enter' && sk.draft?.type === 'line' && sk.draft.points.length >= 2) { finish({ type: 'polyline', points: sk.draft.points, closed: false }); return true; }
      if (e.key === 'Backspace' && sk.draft?.type === 'line' && sk.draft.points.length > 1) { sk.draft.points.pop(); draw(); host.changed(); return true; }
      return false;
    },
    resize() { for (const o of group.children) if (o.material?.resolution) o.material.resolution.set(view.clientWidth, view.clientHeight); },
  };
  return api;
}

// The canvas: see the part, point at it, own the checks. The agent works through the other door (MCP);
// this page follows along by asking the project for its revision every two seconds.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

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

// what is on screen
const S = { state: null, project: null, proj: null, note: null, data: null, faces: [], parts: [], part: null, hotPart: null, hidden: new Set(), face: null, hot: null, rev: null, compare: null, message: '', saveResult: null };

// ---- the 3D view -------------------------------------------------------------------------------------
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);   // millimetres, Z up, as in the Notes
const view = $('#view'), canvas = $('#gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.localClippingEnabled = true;
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 10000);
scene.add(camera);
scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(0.5, 0.8, 1);
camera.add(sun);
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

const material = () => new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0, roughness: 0.8, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h, false);
  const half = radius * 1.2, aspect = w / Math.max(1, h);
  Object.assign(camera, { left: -half * aspect, right: half * aspect, top: half, bottom: -half, near: 0.01, far: radius * 40 });
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(view);

const LOOK = { iso: [1, -1, 0.8], top: [0, -0.0001, 1], front: [0, -1, 0], right: [1, 0, 0] };
function look(name) {
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
  if (!keepCamera) look('iso');
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
  shared = { colour: g.attributes.color, index: g.index.array };
  const parts = S.parts.length ? S.parts : [{ tris: [0, g.index.count / 3], edges: [0, lines ? lines.geometry.attributes.position.count / 2 : 0] }];
  parts.forEach((part, i) => {
    const pg = new THREE.BufferGeometry();
    for (const k of ['position', 'normal', 'color']) pg.setAttribute(k, g.attributes[k]);
    pg.setIndex(g.index);
    pg.setDrawRange(part.tris[0] * 3, part.tris[1] * 3);
    if (part.bbox) {
      pg.boundingBox = new THREE.Box3(new THREE.Vector3(...part.bbox.slice(0, 3)), new THREE.Vector3(...part.bbox.slice(3)));
      pg.boundingSphere = pg.boundingBox.getBoundingSphere(new THREE.Sphere());
    }
    const one = new THREE.Group(), m = new THREE.Mesh(pg, material());
    m.userData.part = one.userData.part = i;
    one.add(m);
    if (lines && part.edges[1]) {
      const lg = new THREE.BufferGeometry();
      lg.setAttribute('position', lines.geometry.attributes.position);
      lg.setDrawRange(part.edges[0] * 2, part.edges[1] * 2);
      if (part.bbox) { lg.boundingBox = pg.boundingBox; lg.boundingSphere = pg.boundingSphere; }
      const l = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x10131b }));
      l.userData.edges = true;
      one.add(l);
    }
    groups.part.add(one);
    meshes.push(m);
  });
}

// pull the parts away from the middle of the assembly, each along its own direction
function spread() {
  for (const one of groups.part.children) {
    const b = S.parts[one.userData.part]?.bbox;
    if (b) one.position.set((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2).sub(home).multiplyScalar(explode);
    one.visible = !S.hidden.has(one.userData.part);
  }
}

function styleAll() {
  for (const [key, g] of Object.entries(groups)) {
    g.traverse((o) => {
      if (o.userData.edges) { o.visible = edgesOn; o.material.clippingPlanes = sectionOn && key === 'part' ? [cut] : []; return; }
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

// colour the faces: tagged ones on hover, the one that is pointed at
function paint() {
  if (!shared) return;
  const colour = shared.colour, index = shared.index;
  for (let i = 0; i < colour.count; i++) BASE.toArray(colour.array, i * 3);
  const range = (start, count, c) => { for (let k = start * 3; k < (start + count) * 3; k++) c.toArray(colour.array, index[k] * 3); };
  const fill = (ids, c) => { for (const id of ids) { const f = S.faces[id]; if (f) range(f.tris[0], f.tris[1], c); } };
  if (S.parts.length > 1) {
    S.parts.forEach((part, i) => {
      const lit = i === S.part || i === S.hotPart;
      if (partColours || lit) range(part.tris[0], part.tris[1], new THREE.Color(PARTS[i % PARTS.length]).lerp(new THREE.Color('#ffffff'), lit ? 0.45 : 0));
    });
  }
  const tags = Object.keys(S.data?.tags ?? {});
  tags.forEach((name, n) => { if (S.hot === name || S.hot === '*') fill(S.data.tag_faces?.[name] ?? [], new THREE.Color(PALETTE[n % PALETTE.length])); });
  if (S.face) fill([S.face.i], PICK);
  colour.needsUpdate = true;
}

function faceOfTriangle(t) {
  let lo = 0, hi = S.faces.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (S.faces[mid].tris[0] <= t) lo = mid; else hi = mid - 1; }
  return S.faces[lo];
}

// a click (not a drag) points at a face
let down = null;
canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !meshes.length || S.compare) return;
  const r = canvas.getBoundingClientRect();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(meshes.filter((m) => m.parent.visible), false).find((h) => !sectionOn || cut.distanceToPoint(h.point) >= 0);
  S.face = hit ? faceOfTriangle(hit.faceIndex) : null;
  S.part = hit && S.parts.length > 1 ? hit.object.userData.part : null;
  // where on the part, not where on the screen: an exploded part has been moved
  S.point = hit ? hit.point.clone().sub(hit.object.parent.position).toArray().map((v) => Math.round(v * 100) / 100) : null;
  paint(); renderPanel(true);
  const tags = Object.entries(S.data?.tag_faces ?? {}).filter(([, ids]) => S.face && ids.includes(S.face.i)).map(([k]) => k);
  api(`/p/${S.project}/selection`, 'POST', S.face ? { note: S.note, face: S.face, point: S.point, tags, part: S.parts[S.part]?.name ?? null } : {}).catch(() => {});
});

(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

// ---- toolbar ---------------------------------------------------------------------------------------------
document.querySelectorAll('[data-cam]').forEach((b) => { b.onclick = () => look(b.dataset.cam); });
$('#edges').onclick = (e) => { edgesOn = !edgesOn; e.target.classList.toggle('on', edgesOn); styleAll(); };
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
  for (const id of ['#asmSep', '#partColours', '#explodeLabel', '#explode']) $(id).hidden = !on;
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
    S.face = null;
    assemblyBar();
    $('#compare').hidden = false;
    $('#compareLabel').textContent = `v${a} → ${b === 'draft' ? 'draft' : 'v' + b}`;
    frame(groups.b, true);
    setMode('added');
  } catch (e) { alert(e.message); }
  busy();
  renderPanel(true);
}
function setMode(mode) {
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
document.querySelectorAll('[data-mode]').forEach((b) => { b.onclick = () => setMode(b.dataset.mode); });
$('#mix').oninput = (e) => { S.compare.mix = Number(e.target.value); setSection(); styleAll(); };
$('#compareOff').onclick = compareOff;

// ---- loading -----------------------------------------------------------------------------------------------
function busy(text) { $('#busy').hidden = !text; $('#busy').textContent = text || ''; }
const state = (n) => (n.kind === 'module' ? '' : n.state === 'error' ? 'red' : n.state === 'unbuilt' ? '' : n.changed ? 'yellow' : 'green');
const order = { assembly: 0, note: 1, module: 2 };

function renderSide() {
  const sorted = [...S.proj.notes].sort((a, b) => order[a.kind] - order[b.kind] || a.name.localeCompare(b.name));
  $('#notes').innerHTML = sorted.map((n) => `<div class="item ${n.name === S.note ? 'sel' : ''}" data-note="${esc(n.name)}" title="${n.kind === 'module' ? 'a helper module, imported by Notes' : n.kind === 'assembly' ? 'an assembly: Notes put together' : n.state === 'error' ? 'does not build' : n.changed ? 'changed since the last save' : 'saved'}">
    <span class="dot ${state(n)}"></span>${esc(n.name)}${n.kind === 'note' ? '' : ` <small>${n.kind}</small>`}</div>`).join('') || '<div class="item muted">no Notes yet: ask your agent for a part</div>';
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
  if (changedNote) { S.face = null; S.saveResult = null; S.part = S.hotPart = null; S.hidden = new Set(); explode = 0; }
  renderSide();
  if (!S.note) { S.data = null; S.parts = []; assemble({}); assemblyBar(); renderPanel(true); return; }
  busy('building…');
  try {
    S.data = await api(`/p/${project}/n/${S.note}`);
    S.rev = (await api(`/p/${project}/rev`)).rev;   // the build itself moved the revision
    if (S.data.report?.built) {
      const stamp = `r=${S.rev}`;
      const [loaded, described] = await Promise.all([loadInto(new THREE.Group(), `${root}/p/${project}/n/${S.note}/model.glb?${stamp}`, true),
        fetch(`${root}/p/${project}/n/${S.note}/faces.json?${stamp}`).then((r) => r.json())]);
      S.faces = described.faces; S.parts = described.parts ?? [];
      if (S.part != null && !S.parts[S.part]) S.part = null;
      assemble(loaded);
      if (S.face) S.face = S.faces.find((f) => f.i === S.face.i && f.type === S.face.type) ?? null;
      frame(groups.part, !changedNote);
      spread();
    } else { S.faces = []; S.parts = []; assemble({}); }
    assemblyBar();
    S.proj = await api(`/p/${project}`);
    renderSide();
  } catch (e) { S.data = { error: e.message }; }
  busy();
  styleAll(); paint(); renderPanel(true);
}

// ---- the panel -----------------------------------------------------------------------------------------------
const AX = ['X', 'Y', 'Z'];
function words(f) {
  const n = (v) => Math.round(v * 100) / 100;
  if (f.type === 'plane') {
    const i = f.normal.findIndex((v) => Math.abs(v) > 0.9999);
    return i < 0 ? `flat face, slanted (normal ${f.normal.map(n).join(', ')}), ${n(f.area)} mm²`
      : `flat face, facing ${f.normal[i] > 0 ? '+' : '−'}${AX[i]}, at ${AX[i].toLowerCase()} = ${n(f.center[i])}, ${n(f.area)} mm²`;
  }
  if (f.type === 'cylinder') return `${f.concave ? 'round hole' : 'round boss'}, ⌀ ${n(2 * f.radius)} mm, axis ${f.axis.map(n).join(', ')}`;
  return `curved face, ${n(f.area)} mm², around ${f.center.map(n).join(', ')}`;
}
const row = (k, v) => `<div class="row"><span class="k">${esc(k)}</span><span class="v">${v}</span></div>`;
const fmt = (v) => (typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : Array.isArray(v) ? v.map(fmt).join(', ') : esc(v));

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
  cards.push(`<div class="card"><div class="row"><h2>${esc(S.note)}</h2><span class="v">${pill}</span></div>
    ${r && !r.built ? `<p class="err mono">${esc(r.error)}</p>` : ''}${d.doc ? `<pre class="doc">${esc(d.doc)}</pre>` : ''}</div>`);

  if (S.compare) {
    const s = S.compare.summary;
    cards.push(`<div class="card"><p class="head">Compare v${S.compare.a} → ${S.compare.b === 'draft' ? 'draft' : 'v' + S.compare.b}</p>
      ${s.same ? `<p class="ok">The same within ${s.tolerance} mm (the printer's tolerance).</p>` : ''}
      ${row('removed, at most', `<span style="color:#e23d2d">${s.removed.max_mm} mm</span>`)}${row('added, at most', `<span style="color:#28a85c">${s.added.max_mm} mm</span>`)}
      ${row('volume', `${s.numbers.volume_cm3[0]} → ${s.numbers.volume_cm3[1]} cm³`)}${row('size', `${fmt(s.numbers.size[0])} → ${fmt(s.numbers.size[1])}`)}
      ${s.tags.map((t) => `<div class="check"><b>${esc(t.tag)}</b><div class="why">${esc(t.change)}</div></div>`).join('') || '<p class="muted">No tagged feature changed.</p>'}
      <p class="muted">Grey is unchanged; colour starts at ${s.tolerance} mm.</p></div>`);
  }

  if (d.is_note && r.built && S.parts.length > 1 && !S.compare) {
    const known = new Set(S.proj.notes.filter((n) => n.kind !== 'module').map((n) => n.name));
    cards.push(`<div class="card"><div class="row"><p class="head" style="margin:0">Assembly · ${S.parts.length} parts</p>
      <span class="v">${S.hidden.size ? '<button data-act="showall">Show all</button>' : ''}</span></div>
      ${S.parts.map((q, i) => `<div class="check part ${i === S.part ? 'sel' : ''}" data-part="${i}"><div class="row">
        <span><span class="swatch" style="background:${PARTS[i % PARTS.length]}"></span><b class="${S.hidden.has(i) ? 'muted' : ''}">${esc(q.name)}</b></span>
        <span class="v muted">${fmt(q.volume / 1000)} cm³</span>
        ${known.has(q.name) ? `<button class="x" data-act="opennote" data-name="${esc(q.name)}" title="open this part's Note">↗</button>` : ''}
        <button class="x" data-act="solo" data-i="${i}" title="show only this part">◎</button>
        <button class="x" data-act="eye" data-i="${i}" title="${S.hidden.has(i) ? 'show' : 'hide'}">${S.hidden.has(i) ? '○' : '●'}</button></div>
        <div class="why mono">${[0, 1, 2].map((k) => fmt(q.bbox[k + 3] - q.bbox[k])).join(' × ')} mm</div></div>`).join('')}
      <p class="muted">Click a part here or in the view. Explode (above the view) pulls them apart.</p></div>`);
  }

  if (d.is_note && r.built) {
    const m = r.measure;
    cards.push(`<div class="card"><p class="head">Part</p>${row('size', `${fmt(m.size_x)} × ${fmt(m.size_y)} × ${fmt(m.size_z)} mm`)}
      ${row('volume', `${fmt(m.volume_cm3)} cm³`)}${row('surface', `${fmt(m.area_cm2)} cm²`)}${row('z', `${fmt(m.min_z)} … ${fmt(m.max_z)}`)}${row('solids', m.solids)}
      ${Object.entries(d.params).map(([k, v]) => row(k, fmt(v))).join('')}</div>`);

    cards.push(`<div class="card"><p class="head">Pointing at</p>${S.face ? `<p>${S.parts[S.part] ? `<b>${esc(S.parts[S.part].name)}</b>: ` : ''}${esc(words(S.face))}</p>
      <div class="line"><input id="tagName" placeholder="name it: base, rod_bore…" maxlength="40"><button class="primary" data-act="tag">Tag it</button></div>
      <div class="line"><input id="tagRole" placeholder="what it is for: sits on the plywood" maxlength="200"></div>
      <p class="muted">Your agent sees what you point at. A tag is written into the Note and must survive every rebuild.</p>`
      : '<p class="muted">Click a face. Your agent can then be told "this face", and you can give it a name.</p>'}</div>`);

    const tags = Object.entries(d.tags);
    cards.push(`<div class="card"><p class="head">Tags</p>${tags.map(([name, t], n) => {
      const res = r.tags[name];
      return `<div class="check tag" data-tag="${esc(name)}"><div class="row"><span><span class="swatch" style="background:${PALETTE[n % PALETTE.length]}"></span><b>${esc(name)}</b>
        ${res?.resolved ? '' : '<span class="err"> not found</span>'}</span><span class="v muted">${esc(t.kind)}</span><button class="x" data-act="untag" data-name="${esc(name)}" title="remove this tag">×</button></div>
        <div class="why">${esc(t.role ?? '')}${res?.why ? ` · ${esc(res.why)}` : ''}</div>
        <div class="why mono">${Object.entries(res?.measure ?? {}).map(([k, v]) => `${k} ${fmt(v)}`).join(' · ')}</div></div>`;
    }).join('') || '<p class="muted">No tags yet. Click a face and name it.</p>'}</div>`);

    const names = [...Object.keys(m), 'fits_bed', ...Object.entries(r.tags).flatMap(([k, t]) => Object.keys(t.measure).map((x) => `tag.${k}.${x}`))];
    cards.push(`<div class="card"><p class="head">Checks · yours: the agent can add one, never change or remove one</p>
      ${r.checks.map((c) => `<div class="check"><div class="row"><span class="${c.ok ? 'ok' : 'err'}">${c.ok ? '✓' : '✗'} <span class="mono">${esc(c.what)}</span></span>
        <span class="v">${fmt(c.value)} <span class="muted">(${esc(c.expect)})</span></span>${c.by === 'monet' ? '' : `<button class="x" data-act="uncheck" data-id="${esc(c.id)}" title="remove this check">×</button>`}</div>
        <div class="why">${esc(c.why || '')}${c.by === 'agent' ? ' · added by the agent' : ''}${c.note ? ` · ${esc(c.note)}` : ''}</div></div>`).join('')}
      <div class="line"><input id="ckWhat" list="measures" placeholder="what: size_x, tag.bore.width…"><datalist id="measures">${names.map((x) => `<option value="${esc(x)}">`).join('')}</datalist></div>
      <div class="line"><input id="ckMin" placeholder="min" inputmode="decimal"><input id="ckMax" placeholder="max" inputmode="decimal"><input id="ckEq" placeholder="or equals"></div>
      <div class="line"><input id="ckWhy" placeholder="why: the rule in your words"><button data-act="check">Add</button></div></div>`);

    const lc = d.load_check, colour = { green: 'ok', yellow: 'warn', red: 'err', new: 'muted' }[lc.status];
    cards.push(`<div class="card"><div class="row"><p class="head" style="margin:0">Load check</p><span class="v"><span class="pill ${colour}">${esc(lc.status === 'new' ? 'never saved' : lc.status)}</span></span></div>
      ${lc.status === 'new' ? '' : `<p class="muted">The saved Note, rebuilt just now, compared with what was saved${lc.version ? ` (v${lc.version})` : ''}.</p>`}
      ${(lc.changes ?? []).map((c) => `<div class="why ${c.level === 'red' ? 'err' : 'warn'}">${esc(c.what)}${c.delta != null ? ` ${c.delta > 0 ? '+' : ''}${c.delta}` : ''}${c.why ? ` · ${esc(c.why)}` : ''}</div>`).join('')}
      ${lc.status === 'red' || lc.status === 'yellow' ? (lc.acknowledged ? `<p class="muted">You looked at this on ${new Date(lc.acknowledged).toLocaleString()}.</p>`
        : `<div class="line"><span class="muted" style="flex:1">${lc.status === 'red' ? 'The agent may not edit this Note until you have looked.' : 'Within print tolerance; probably a library update.'}</span><button data-act="ack">I have looked</button></div>`) : ''}</div>`);
  }

  const red = S.saveResult && !S.saveResult.saved ? Object.entries(S.saveResult.red).map(([k, v]) => `<div class="why err"><b>${esc(k)}</b>: ${esc(Array.isArray(v) ? v.join('; ') : v)}</div>`).join('') : '';
  cards.push(`<div class="card"><p class="head">Save the project as a version</p>
    <div class="line" style="margin-top:0"><input id="saveMsg" placeholder="what changed, and why" value="${esc(S.message)}"><button class="primary" data-act="save">Save</button></div>
    ${S.saveResult?.saved ? `<p class="ok">Saved as v${S.saveResult.version}.</p>` : red ? `<p class="err">Nothing is saved on red.</p>${red}` : ''}
    <p class="muted">Every Note must build and pass its checks. History is your own git folder: your agent commits there after each save.</p></div>`);

  if (d.is_note && r.built) {
    const v = S.compare && S.compare.b !== 'draft' ? `?v=${S.compare.b}` : '';
    cards.push(`<div class="card"><p class="head">Export ${v ? 'v' + S.compare.b : 'the draft'}</p><div class="line" style="margin-top:0">
      ${['3mf', 'stl', 'step', 'glb'].map((f) => `<a href="${root}/p/${S.project}/n/${S.note}/export.${f}${v}" download><button>${f.toUpperCase()}</button></a>`).join('')}</div></div>`);
  }
  cards.push(`<div class="card"><details><summary>The Note: ${esc(S.note)}.py</summary><pre class="src mono">${esc(d.source)}</pre></details></div>`);
  panel.innerHTML = cards.join('');
}

const act = async (fn) => { try { await fn(); await open(S.project, S.note); } catch (e) { alert(e.message); busy(); } };
$('#panel').addEventListener('focusout', () => { if (S.stale) setTimeout(() => renderPanel(), 50); });
$('#panel').addEventListener('input', (e) => { if (e.target.id === 'saveMsg') S.message = e.target.value; });
$('#panel').addEventListener('mouseover', (e) => {
  const t = e.target.closest('[data-tag]'), q = e.target.closest('[data-part]');
  const hot = t ? t.dataset.tag : null, hotPart = q ? Number(q.dataset.part) : null;
  if (hot !== S.hot || hotPart !== S.hotPart) { S.hot = hot; S.hotPart = hotPart; paint(); }
});
$('#panel').addEventListener('mouseleave', () => { if (S.hot || S.hotPart != null) { S.hot = S.hotPart = null; paint(); } });
$('#panel').addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (!b) {   // a click on a part's row points at that part
    const q = e.target.closest('[data-part]');
    if (q) { S.part = Number(q.dataset.part) === S.part ? null : Number(q.dataset.part); paint(); renderPanel(true); }
    return;
  }
  // the parts of an assembly: nothing here goes to the server
  if (['eye', 'solo', 'showall'].includes(b.dataset.act)) {
    const i = Number(b.dataset.i);
    if (b.dataset.act === 'showall') S.hidden = new Set();
    else if (b.dataset.act === 'eye') (S.hidden.has(i) ? S.hidden.delete(i) : S.hidden.add(i));
    else S.hidden = new Set(S.parts.map((_, k) => k).filter((k) => k !== i));
    spread(); renderPanel(true);
    return;
  }
  if (b.dataset.act === 'opennote') { open(S.project, b.dataset.name); return; }
  const n = `/p/${S.project}/n/${S.note}`, num = (id) => ($(id).value.trim() === '' ? null : Number($(id).value.replace(',', '.')));
  const a = b.dataset.act;
  if (a === 'tag') act(async () => { busy('building…'); await api(`${n}/tags`, 'POST', { name: $('#tagName').value.trim(), role: $('#tagRole').value, face: S.face }); });
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
  if (!S.project || document.hidden || !$('#busy').hidden) return;
  try { const { rev } = await api(`/p/${S.project}/rev`); if (rev !== S.rev && !S.compare) await open(S.project, S.note); } catch { /* the server is away; try again */ }
}, 2000);
window.addEventListener('hashchange', () => { const [p, n] = decodeURIComponent(location.hash.slice(1)).split('/'); if (p && (p !== S.project || (n && n !== S.note))) open(p, n); });

window.monet = { S, groups, camera, scene };   // for looking in from the console, and from scripts/shot.mjs
resize();
start().catch((e) => { $('#panel').innerHTML = `<div class="card"><p class="err">${esc(e.message)}</p></div>`; });

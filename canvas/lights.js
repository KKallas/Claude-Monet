// The lights of a Note (LIGHTS, checked by monet/lights.py and handed over in the report), drawn as a client should
// see them: where the light lands (a three.js spot light with shadows; a projector puts a picture there), the beam in
// the air (searchlights and lasers in smoke: a bundle of rays, each a soft ribbon added onto the picture, bright at the
// source and fading, slow smoke drifting through, specks of dust), a part that glows with it, a streak where you look
// into a source, and bloom. Every ray ends where it first meets a part, so a part in the way leaves a dark shaft.
// The room's own light and the haze in the air are levels too: dim the room and the beams carry the picture.
// This knows nothing of the server: the page gives it the parts and the levels (canvas.js, the timeline).
import * as THREE from 'three';
import { MeshBVH, acceleratedRaycast } from 'three-mesh-bvh';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { createPixels } from './pixels.js';

export const SCENE_LEVELS = { room: 0.12, haze: 0.6 };      // the room dimmed, smoke in the air: where lights show
const CD = 1e6 * 4e-4;      // candela to three.js: millimetres (inverse square in mm), and an exposure that keeps a room readable
// rays to a beam: few, each ribbon wide enough to meet the next (every one is smoke drawn over the others)
const GRID = { spot: 11, projector: 16 }, FAN = 72, CAP = 800;

const v = () => new THREE.Vector3();
const tmp = { a: v(), b: v(), c: v(), m: new THREE.Matrix4(), n: new THREE.Matrix3(), q: new THREE.Quaternion() };

// ---- the projector's test picture: colour bars, a grid, a circle; the beam's rays take their colour from it
function testPicture(aspect) {
  const W = 512, H = Math.round(W / aspect), c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  const bars = ['#c0c0c0', '#c0c000', '#00c0c0', '#00c000', '#c000c0', '#c00000', '#0000c0'];
  bars.forEach((b, i) => { g.fillStyle = b; g.fillRect((i * W) / 7, 0, W / 7 + 1, H * 0.62); });
  const grad = g.createLinearGradient(0, 0, W, 0);
  grad.addColorStop(0, '#000'); grad.addColorStop(1, '#fff');
  g.fillStyle = grad; g.fillRect(0, H * 0.62, W, H * 0.13);
  g.fillStyle = '#101418'; g.fillRect(0, H * 0.75, W, H * 0.25);
  g.strokeStyle = 'rgba(255,255,255,.85)'; g.lineWidth = 2;
  for (let x = 0; x <= W; x += W / 8) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 0; y <= H; y += H / 6) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  g.lineWidth = 4; g.beginPath(); g.arc(W / 2, H / 2, H * 0.42, 0, Math.PI * 2); g.stroke();
  g.fillStyle = '#fff'; g.font = `bold ${Math.round(H * 0.11)}px sans-serif`; g.textAlign = 'center'; g.fillText('MONET', W / 2, H * 0.9);
  return { canvas: c, data: g.getImageData(0, 0, W, H).data, W, H };
}
/** The picture put into the square a spot light projects: black round it, as wide and tall as the beam is. */
function spotMap(pic, fx, fy) {
  const S = 512, c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, S, S);
  const w = S * fx, h = S * fy;
  g.drawImage(pic.canvas, (S - w) / 2, (S - h) / 2, w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
/** Part names as MATERIALS writes them: * and ? within each alternative, | between them (monet/materials.py). */
export function nameMatcher(pattern) {
  const alts = String(pattern).split('|').map((a) => a.trim()).filter(Boolean)
    .map((a) => new RegExp(`^${a.replace(/[.+^${}()[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`));
  return (name) => alts.some((r) => r.test(name));
}
const sample = (pic, u, w) => {      // the picture's colour at (u, w) in 0…1, w from the top
  const x = Math.min(pic.W - 1, Math.max(0, Math.round(u * (pic.W - 1)))), y = Math.min(pic.H - 1, Math.max(0, Math.round(w * (pic.H - 1))));
  const i = (y * pic.W + x) * 4;
  return [pic.data[i] / 255, pic.data[i + 1] / 255, pic.data[i + 2] / 255];
};

// ---- the streak of a source seen head on: a round core and a long thin line across, as an anamorphic lens draws it
function streakTexture() {
  const c = document.createElement('canvas');
  c.width = 512; c.height = 64;
  const g = c.getContext('2d');
  const line = g.createLinearGradient(0, 0, 512, 0);
  line.addColorStop(0, 'rgba(255,255,255,0)'); line.addColorStop(0.5, 'rgba(255,255,255,0.9)'); line.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = line; g.fillRect(0, 30, 512, 4);
  g.globalAlpha = 0.35; g.fillRect(0, 27, 512, 10);
  g.globalAlpha = 1;
  const core = g.createRadialGradient(256, 32, 0, 256, 32, 32);
  core.addColorStop(0, 'rgba(255,255,255,1)'); core.addColorStop(0.25, 'rgba(255,255,255,.6)'); core.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = core; g.fillRect(224, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ---- the beam: ribbons along the rays, facing the eye, added onto the picture
const NOISE = /* glsl */`
  float h3(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
  float n3(vec3 x) {
    vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(h3(i), h3(i + vec3(1,0,0)), f.x), mix(h3(i + vec3(0,1,0)), h3(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(h3(i + vec3(0,0,1)), h3(i + vec3(1,0,1)), f.x), mix(h3(i + vec3(0,1,1)), h3(i + vec3(1,1,1)), f.x), f.y), f.z);
  }
  float smoke(vec3 p, float t) {
    vec3 q = p * 0.0045 + vec3(0.0, t * 0.035, t * 0.06);
    return 0.62 * n3(q) + 0.38 * n3(q * 2.7 + 7.1);
  }`;
function beamMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uLevel: { value: 1 }, uHaze: { value: 0.6 }, uTime: { value: 0 }, uFade: { value: 1500 }, uGain: { value: 1 }, uCore: { value: 0 } },
    vertexShader: /* glsl */`
      attribute vec2 corner;
      attribute vec3 iStart; attribute vec3 iEnd; attribute vec3 iColor; attribute float iWeight; attribute vec2 iWidth;
      varying float vSide; varying float vDist; varying vec3 vWorld; varying vec3 vColor; varying float vWeight; varying float vS;
      void main() {
        vec3 a = (modelViewMatrix * vec4(iStart, 1.0)).xyz, b = (modelViewMatrix * vec4(iEnd, 1.0)).xyz;
        vec3 p = mix(a, b, corner.x);
        vec2 d = b.xy - a.xy; float l = length(d);
        vec2 n = l > 1e-4 ? vec2(-d.y, d.x) / l : vec2(1.0, 0.0);
        float len = distance(iStart, iEnd);
        p.xy += n * corner.y * 0.5 * (iWidth.x + iWidth.y * len * corner.x);
        vSide = corner.y; vS = corner.x; vDist = len * corner.x; vWorld = mix(iStart, iEnd, corner.x);
        vColor = iColor; vWeight = iWeight;
        gl_Position = projectionMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: /* glsl */`
      uniform float uLevel, uHaze, uTime, uFade, uGain, uCore;
      varying float vSide; varying float vDist; varying vec3 vWorld; varying vec3 vColor; varying float vWeight; varying float vS;
      ${NOISE}
      void main() {
        float across = 1.0 - vSide * vSide;
        float body = mix(across * across, pow(across, 10.0) * 2.2 + across * across * 0.35, uCore);
        float along = exp(-vDist / uFade) * smoothstep(0.0, 0.04, vS);
        float s = mix(0.35, 1.25, smoke(vWorld, uTime));
        float a = vWeight * uLevel * uHaze * body * along * mix(s, 1.0, uCore * 0.6) * uGain;
        gl_FragColor = vec4(vColor * a, 1.0);
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  });
}
function beamMesh() {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('corner', new THREE.Float32BufferAttribute([0, -1, 1, -1, 1, 1, 0, 1], 2));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  for (const [k, n] of [['iStart', 3], ['iEnd', 3], ['iColor', 3], ['iWeight', 1], ['iWidth', 2]])
    g.setAttribute(k, new THREE.InstancedBufferAttribute(new Float32Array(CAP * n), n).setUsage(THREE.DynamicDrawUsage));
  g.instanceCount = 0;
  const m = new THREE.Mesh(g, beamMaterial());
  m.frustumCulled = false;
  m.renderOrder = 5;
  return m;
}
// specks of dust in the beam: points on the rays, twinkling
function dustPoints(count) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3).setUsage(THREE.DynamicDrawUsage));
  const seed = new Float32Array(count);
  for (let i = 0; i < count; i++) seed[i] = Math.random();
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  g.setAttribute('glow', new THREE.BufferAttribute(new Float32Array(count), 1).setUsage(THREE.DynamicDrawUsage));
  const m = new THREE.ShaderMaterial({
    uniforms: { uLevel: { value: 1 }, uHaze: { value: 0.6 }, uTime: { value: 0 }, uColor: { value: new THREE.Color() }, uPx: { value: 1 } },
    vertexShader: /* glsl */`
      attribute float seed; attribute float glow; uniform float uTime, uPx; varying float vA;
      void main() {
        vec3 p = position + vec3(sin(uTime * 0.31 + seed * 40.0), cos(uTime * 0.27 + seed * 23.0), sin(uTime * 0.19 + seed * 11.0)) * 6.0;
        vA = glow * (0.35 + 0.65 * pow(0.5 + 0.5 * sin(uTime * (0.6 + seed) + seed * 60.0), 3.0));
        gl_PointSize = (1.2 + 1.8 * fract(seed * 7.13)) * uPx;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: /* glsl */`
      uniform float uLevel, uHaze; uniform vec3 uColor; varying float vA;
      void main() { vec2 c = gl_PointCoord - 0.5; float r = 1.0 - smoothstep(0.1, 0.5, length(c)); gl_FragColor = vec4(uColor * r * vA * uLevel * (0.4 + uHaze), 1.0); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  });
  const p = new THREE.Points(g, m);
  p.frustumCulled = false;
  p.renderOrder = 6;
  return p;
}

/** The directions of a light's rays in its own frame (x across, y up, z along the aim), each with a weight, a colour
 *  and how wide its ribbon spreads per mm. */
function raysOf(L, pic) {
  const out = [];
  if (L.kind === 'spot') {
    const t = Math.tan(THREE.MathUtils.degToRad(L.angle / 2)), n = GRID.spot, col = new THREE.Color(L.color);
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
      const x = (i / (n - 1)) * 2 - 1, y = (j / (n - 1)) * 2 - 1, r = Math.hypot(x, y);
      if (r > 1.0001) continue;
      const w = 1 - THREE.MathUtils.smoothstep(r, 1 - Math.max(0.05, L.soft), 1.0001);
      out.push({ d: [x * t, y * t, 1], w: 0.35 + 0.65 * w, c: col.toArray(), spread: (2.4 * t) / n });
    }
  } else if (L.kind === 'projector') {
    const hw = 0.5 / L.throw, hh = hw / L.aspect, off = L.offset * 2 * hh, nx = GRID.projector, ny = Math.max(6, Math.round(nx / L.aspect));
    for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
      const u = (i + 0.5) / nx, w = (j + 0.5) / ny;      // across the picture, and down it from the top
      const c = sample(pic, u, w);
      out.push({ d: [(u * 2 - 1) * hw, off + (1 - w * 2) * hh, 1], w: 0.25 + 0.75 * Math.max(...c), c, spread: (2.6 * hw) / nx });
    }
  } else if (L.kind === 'laser') {
    const col = new THREE.Color(L.color).toArray(), n = L.fan ? FAN : 1, half = THREE.MathUtils.degToRad((L.fan || 0) / 2);
    const step = n === 1 ? 0 : (2 * half) / (n - 1);
    for (let i = 0; i < n; i++) {      // a fan: a sheet, its rays' halos running into each other, its cores faint
      const a = n === 1 ? 0 : -half + step * i;
      out.push({ d: [Math.tan(a), 0, 1], w: n === 1 ? 1 : 0.3, c: col, spread: 0.0006, laser: true, halo: n === 1 ? 0.004 : 1.8 * Math.tan(step), haloW: n === 1 ? 0.18 : 0.1 });
    }
  }
  return out;
}

/**
 * The lights of the view. hooks: parts() → [{name, object (the part's group, posed), mesh, keepout, hidden}],
 * camera() the camera in use. Returns {set(lights), levels, enable(on), on, moved(), update(time), render(), resize()}.
 */
export function createLights({ renderer, scene, look, hooks }) {
  const root = new THREE.Group();
  root.visible = false;
  scene.add(root);
  const streak = streakTexture();
  let lights = [], rigs = [], on = false, dirty = true, blockers = [], stage = null, composer = null, bloom = null, pass = null, full = false, parts = null;
  const levels = { room: SCENE_LEVELS.room, haze: SCENE_LEVELS.haze };
  const caster = new THREE.Raycaster();
  caster.firstHitOnly = true;
  const pix = createPixels();      // a pixels light: every pixel its own colour, lit from its LEDs (canvas/pixels.js)
  let described = null;      // the build's faces.json: where its pixels and LEDs are
  let toned = false;      // the tone mapping changed for the pixels (restyle)

  // what a ray can meet: every part shown but the keep-outs, each with a tree of its own triangles, moved with it
  function makeBlockers() {
    for (const b of blockers) b.geometry.boundsTree = null;
    blockers = [];
    for (const p of hooks.parts()) {
      if (p.keepout || !p.mesh) continue;
      const src = p.mesh.geometry, r = src.drawRange, index = src.index.array.slice(r.start, r.start + r.count);
      if (!index.length) continue;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', src.attributes.position);
      g.setIndex(new THREE.BufferAttribute(index, 1));
      g.boundsTree = new MeshBVH(g);
      const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
      m.raycast = acceleratedRaycast;
      m.matrixAutoUpdate = false;
      m.userData = { name: p.name, part: p };
      blockers.push(m);
    }
  }
  const seen = (b) => !b.userData.part.hidden;

  function rigOf(L) {
    const rig = { L, beam: null, dust: null, light: null, target: new THREE.Object3D(), flare: null, rays: [], pic: null, glow: null };
    root.add(rig.target);
    if (L.kind === 'projector') rig.pic = testPicture(L.aspect);
    if (['spot', 'projector', 'laser'].includes(L.kind)) {
      rig.rays = raysOf(L, rig.pic);
      rig.beam = beamMesh();
      rig.beam.material.uniforms.uCore.value = L.kind === 'laser' ? 1 : 0;
      rig.beam.material.uniforms.uFade.value = L.kind === 'laser' ? L.reach * 2 : Math.max(300, L.reach * 0.55);
      rig.beam.material.uniforms.uGain.value = L.kind === 'laser' ? 1.6 : L.kind === 'projector' ? 0.12 : 0.16;
      rig.dust = dustPoints(L.kind === 'laser' ? 160 : 420);
      rig.dust.material.uniforms.uColor.value.set(L.color);
      root.add(rig.beam, rig.dust);
      if (L.kind === 'laser') {      // where it lands: a hot dot, a line where a fan cuts a surface
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(rig.rays.length * 3), 3).setUsage(THREE.DynamicDrawUsage));
        rig.marks = new THREE.Points(g, new THREE.PointsMaterial({ color: new THREE.Color(L.color).lerp(new THREE.Color(0xffffff), 0.45), size: 5,
          sizeAttenuation: false, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
        rig.marks.frustumCulled = false;
        rig.marks.renderOrder = 7;
        root.add(rig.marks);
      }
    }
    if (L.kind === 'spot' || L.kind === 'projector') {
      const s = new THREE.SpotLight(L.color, 0, 0, 0.5, 0, 2);
      s.castShadow = true;
      s.shadow.mapSize.setScalar(L.kind === 'projector' ? 1024 : 512);
      s.shadow.bias = -0.0004;
      s.shadow.camera.near = 2;
      s.shadow.camera.far = L.reach * 1.2;      // its shadows and its picture reach as far as it does (three.js stops at 500 mm)
      s.target = rig.target;
      if (L.kind === 'spot') { s.angle = THREE.MathUtils.degToRad(L.angle / 2); s.penumbra = Math.min(1, L.soft + 0.05); }
      else {
        const hw = 0.5 / L.throw, hh = hw / L.aspect, t = Math.hypot(hw, hh) * 1.02;
        s.angle = Math.atan(t); s.penumbra = 0;
        s.map = spotMap(rig.pic, hw / t, hh / t);
      }
      rig.light = s;
      root.add(s);
    } else if (L.kind === 'point' || (L.kind === 'glow' && L.at)) {
      rig.light = new THREE.PointLight(L.color, 0, 0, 2);
      root.add(rig.light);
    }
    if (L.kind !== 'glow' && L.kind !== 'pixels') {
      rig.flare = new THREE.Sprite(new THREE.SpriteMaterial({ map: streak, color: new THREE.Color(L.color), blending: THREE.AdditiveBlending,
        depthTest: false, depthWrite: false, transparent: true, toneMapped: false, sizeAttenuation: false }));
      rig.flare.renderOrder = 9;
      root.add(rig.flare);
    }
    return rig;
  }

  function set(list) {
    for (const r of rigs) {
      r.light?.map?.dispose(); r.light?.shadow.map?.dispose();
      r.beam?.geometry.dispose(); r.beam?.material.dispose(); r.marks?.geometry.dispose(); r.marks?.material.dispose(); r.dust?.geometry.dispose(); r.dust?.material.dispose(); r.flare?.material.dispose();
    }
    root.clear();
    lights = list ?? [];
    rigs = lights.map(rigOf);
    for (const L of lights) if (levels[L.name] == null) levels[L.name] = 1;
    blockers = [];
    dirty = true;
    pix.set(lights, described, hooks.parts());
    restyle();
  }

  // the floor under the assembly and a wall before its projector: something for the light to land on
  function makeStage() {
    if (stage) { stage.traverse((o) => o.geometry?.dispose()); root.parent?.remove(stage); }
    stage = new THREE.Group();
    const box = new THREE.Box3();
    for (const p of hooks.parts()) if (!p.keepout && p.mesh?.geometry.boundingBox) box.union(p.mesh.geometry.boundingBox);
    if (box.isEmpty()) return;
    const c = box.getCenter(v()), size = box.getSize(v()), span = Math.max(size.x, size.y, size.z);
    const mat = new THREE.MeshStandardMaterial({ color: 0x6c7078, roughness: 0.92, metalness: 0, envMapIntensity: 0.25 });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(span * 14, span * 14), mat);
    floor.position.set(c.x, c.y, box.min.z - Math.min(1600, Math.max(600, span * 1.6)));      // a lamp over a table, roughly
    floor.receiveShadow = true;
    stage.add(floor);
    const proj = lights.find((L) => L.kind === 'projector') ?? lights.find((L) => L.aim && Math.abs(L.aim[2]) < 0.8);
    if (proj) {
      const d = new THREE.Vector3(proj.aim[0], proj.aim[1], 0).normalize();
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(span * 14, span * 8), mat);
      wall.position.copy(c).addScaledVector(d, Math.min(3000, Math.max(1200, span * 2.5)));      // a living room's wall
      wall.position.z = floor.position.z + span * 4;
      wall.lookAt(c.x, c.y, wall.position.z);
      wall.receiveShadow = true;
      stage.add(wall);
    }
    for (const m of stage.children) {
      m.updateMatrixWorld(true);
      m.geometry.boundsTree = new MeshBVH(m.geometry);
      m.raycast = acceleratedRaycast;
    }
    scene.add(stage);
    stage.visible = on;
  }

  function restyle() {
    renderer.shadowMap.enabled = on;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;      // drawn again only when something moved (update), not every frame
    renderer.shadowMap.needsUpdate = true;
    parts = null;
    for (const p of hooks.parts()) {
      if (!p.mesh) continue;
      p.mesh.castShadow = on && !p.keepout; p.mesh.receiveShadow = on && !p.keepout;
      p.object.traverse((o) => { if (o.isMesh && o.material?.isMaterial) o.material.needsUpdate = true; });
      if (p.keepout) p.object.visible = !on && !p.hidden;      // the beam is drawn now: its keep-out would be drawn twice
    }
    if (!on) for (const p of hooks.parts()) if (p.mesh?.material?.emissive) p.mesh.material.emissive.setRGB(0, 0, 0);
    if (on && pix.active) for (const p of hooks.parts()) pix.patch(p.mesh?.material);      // its materials are new after a restyle
    pix.show(on);
    // lit pixels keep their hue: AgX (the rendered look's) washes a saturated blue out to slate; Khronos Neutral does not
    const want = on && pix.active && renderer.toneMapping === THREE.AgXToneMapping;
    if (want) { renderer.toneMapping = THREE.NeutralToneMapping; toned = true; }
    else if (toned && !(on && pix.active)) { if (renderer.toneMapping === THREE.NeutralToneMapping) renderer.toneMapping = THREE.AgXToneMapping; toned = false; }
    look.dim?.(on ? levels.room : 1);
    scene.background = on ? new THREE.Color(0x020306).lerp(new THREE.Color(0x1a1f2a), levels.room) : null;
  }

  function enable(next) {
    on = !!next;
    root.visible = on;
    if (on && !blockers.length) makeBlockers();
    if (on) makeStage(); else if (stage) stage.visible = false;
    dirty = true;
    restyle();
  }

  // where each light is now, on its part as the joints have put it
  function placeRig(rig, parts) {
    const L = rig.L, owner = L.on ? parts.get(L.on) : null;
    const m = owner ? owner.object.matrixWorld : tmp.m.identity();
    rig.pos = (rig.pos ?? v()).set(...(L.at ?? [0, 0, 0])).applyMatrix4(m);
    if (L.aim) {
      tmp.n.setFromMatrix4(m);
      rig.aim = (rig.aim ?? v()).set(...L.aim).applyMatrix3(tmp.n).normalize();
      const up = L.kind === 'projector' ? L.up : L.across ?? [0, 0, 1];
      rig.up = (rig.up ?? v()).set(...up).applyMatrix3(tmp.n);
      rig.up.addScaledVector(rig.aim, -rig.up.dot(rig.aim));
      if (rig.up.lengthSq() < 1e-6) rig.up.set(0, 1, 0).addScaledVector(rig.aim, -rig.aim.y);
      rig.up.normalize();
      rig.right = (rig.right ?? v()).crossVectors(rig.aim, rig.up).normalize();
      if (L.kind === 'laser' && L.across) { rig.right.copy(rig.up); rig.up.crossVectors(rig.right, rig.aim).normalize(); }
    }
  }

  // the rays from where the light is now, each to where it first meets a part, or as far as the light reaches
  function cast(rig) {
    const L = rig.L, g = rig.beam.geometry, A = g.attributes, own = L.on, list = blockers.filter((b) => b.userData.name !== own && seen(b));
    if (stage) list.push(...stage.children);
    let k = 0, dk = 0;
    const dust = rig.dust.geometry.attributes, nd = dust.position.count;
    const hits = [];
    rig.nmarks = 0;
    for (const r of rig.rays) {
      if (k >= CAP) break;
      const d = tmp.a.copy(rig.right).multiplyScalar(r.d[0]).addScaledVector(rig.up, r.d[1]).addScaledVector(rig.aim, r.d[2]).normalize();
      caster.set(tmp.b.copy(rig.pos).addScaledVector(d, 0.6), d);
      caster.far = L.reach;
      const hit = caster.intersectObjects(list, false)[0];
      const len = hit ? hit.distance + 0.6 : L.reach;
      const end = tmp.c.copy(rig.pos).addScaledVector(d, len);
      A.iStart.setXYZ(k, rig.pos.x, rig.pos.y, rig.pos.z);
      A.iEnd.setXYZ(k, end.x, end.y, end.z);
      A.iColor.setXYZ(k, ...r.c);
      A.iWeight.setX(k, r.w);
      A.iWidth.setXY(k, r.laser ? 1.6 : 3, r.spread);
      hits.push([rig.pos.clone(), end.clone(), r.w]);
      if (rig.marks && hit) { rig.marks.geometry.attributes.position.setXYZ(rig.nmarks, end.x, end.y, end.z); rig.nmarks++; }
      k++;
      if (r.laser && k < CAP) {      // a laser: a wide faint halo round its hot core
        A.iStart.setXYZ(k, rig.pos.x, rig.pos.y, rig.pos.z); A.iEnd.setXYZ(k, end.x, end.y, end.z);
        A.iColor.setXYZ(k, ...r.c); A.iWeight.setX(k, r.haloW); A.iWidth.setXY(k, 14, r.halo);
        k++;
      }
    }
    g.instanceCount = k;
    for (const key of ['iStart', 'iEnd', 'iColor', 'iWeight', 'iWidth']) A[key].needsUpdate = true;
    for (let i = 0; i < nd && hits.length; i++) {      // the dust: on the rays, more of it near the source
      const [a, b, w] = hits[(i * 7919) % hits.length], t = Math.pow(dust.seed.array[i], 1.6);
      dust.position.setXYZ(i, a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t);
      dust.glow.setX(i, w * Math.exp(-t * a.distanceTo(b) / Math.max(200, L.reach * 0.6)));
      dk++;
    }
    dust.position.needsUpdate = dust.glow.needsUpdate = true;
    rig.dust.geometry.setDrawRange(0, dk);
    if (rig.marks) { rig.marks.geometry.attributes.position.needsUpdate = true; rig.marks.geometry.setDrawRange(0, rig.nmarks); }
  }

  // a source seen: how much it looks at you, and nothing in between
  function flare(rig, cam) {
    const s = rig.flare, level = levels[rig.L.name] ?? 1;
    const to = cam.isPerspectiveCamera ? tmp.a.copy(cam.position).sub(rig.pos) : tmp.a.set(0, 0, 1).applyQuaternion(cam.quaternion).multiplyScalar(1e5);
    const dist = to.length();
    to.normalize();
    let face = rig.aim ? Math.max(0, rig.aim.dot(to)) : 1;
    if (rig.L.kind === 'spot') face = Math.pow(face, 3 + 60 / Math.max(2, rig.L.angle));
    else if (rig.L.kind === 'projector') face = Math.pow(face, 6);
    else if (rig.L.kind === 'laser') face = Math.pow(face, 40);
    let clear = face > 0.01;
    if (clear) {
      caster.set(tmp.b.copy(rig.pos).addScaledVector(to, 1.5), to);
      caster.far = Math.min(dist, 1e5);
      clear = !caster.intersectObjects(blockers.filter((b) => b.userData.name !== rig.L.on && seen(b)), false).length;
    }
    const k = clear ? level * (0.25 + face) : 0;
    s.visible = k > 0.01;
    s.position.copy(rig.pos);
    s.scale.set(0.9 * k, 0.11 * k, 1);
    s.material.opacity = Math.min(1, k);
  }

  function update(time, camera = null) {      // camera: the one the picture is drawn from (a video's own), else the view's
    if (!on) return;
    if (dirty || !parts) { const list = hooks.parts(); parts = Object.assign(new Map(list.map((p) => [p.name, p])), { list }); }
    const cam = camera ?? hooks.camera(), list = parts.list;
    if (dirty) renderer.shadowMap.needsUpdate = true;
    for (const b of blockers) { b.matrixWorld.copy(b.userData.part.object.matrixWorld); }
    look.dim?.(levels.room);
    const px = renderer.getPixelRatio();
    for (const rig of rigs) {
      const L = rig.L, level = levels[L.name] ?? 1;
      placeRig(rig, parts);
      if (rig.light) {
        rig.light.position.copy(rig.pos);
        if (rig.aim) {
          const at = tmp.a.copy(rig.aim);
          if (L.kind === 'projector') {      // aimed at the picture's middle, its top along the projector's up
            const hh = 0.5 / L.throw / L.aspect;
            at.addScaledVector(rig.up, L.offset * 2 * hh).normalize();
            rig.light.shadow.camera.up.copy(rig.up);
          }
          rig.light.position.addScaledVector(at, 1);
          rig.target.position.copy(rig.pos).addScaledVector(at, 1000);
          rig.target.updateMatrixWorld();
        }
        const cd = L.candela ?? (L.lumens ?? 800) / (4 * Math.PI);
        rig.light.intensity = cd * CD * level;
        rig.light.visible = level > 0.001;
      }
      if (rig.beam) {
        if (dirty) cast(rig);
        const u = rig.beam.material.uniforms, du = rig.dust.material.uniforms;
        u.uLevel.value = du.uLevel.value = level;
        u.uHaze.value = du.uHaze.value = levels.haze;
        u.uTime.value = du.uTime.value = time;
        du.uPx.value = px;
        rig.beam.visible = rig.dust.visible = level > 0.001 && levels.haze > 0.001;
        if (rig.marks) { rig.marks.visible = level > 0.001; rig.marks.material.opacity = Math.min(1, level * 1.5); }
      }
      if (L.glow && L.kind !== 'pixels') {      // the parts that glow with it (pixels: below, each its own)
        const strength = level * Math.min(2, 0.2 + (L.lumens ?? 1000) / 1500);      // a whole skin glowing: gently, or bloom eats it
        if (rig.glowList !== list) {      // the meshes that glow, found once for these parts
          const m = nameMatcher(L.glow), out = [];
          for (const p of list) if (m(p.name)) p.object.traverse((o) => { if (o.isMesh && !o.userData.cap) out.push(o); });
          rig.glowing = out; rig.glowList = list; rig.glowColor = new THREE.Color(L.color);
        }
        for (const o of rig.glowing) if (o.material?.emissive) { o.material.emissive.copy(rig.glowColor); o.material.emissiveIntensity = strength; }
      }
      if (rig.flare) flare(rig, cam);
    }
    if (pix.active) pix.update((name) => levels[name] ?? 1, hooks.pattern);
    dirty = false;
    if (scene.background) scene.background.setRGB(0.008, 0.012, 0.022).lerp(new THREE.Color(0x1a1f2a), levels.room);
  }

  // the picture: bloom over the bright parts when the lights are on
  function render(camera) {
    if (!on) { renderer.render(scene, camera); return; }
    if (!composer) {
      composer = new EffectComposer(renderer);
      pass = new RenderPass(scene, camera);
      const size = renderer.getSize(v());
      bloom = new UnrealBloomPass(new THREE.Vector2(size.x, size.y), 0.85, 0.55, 0.82);
      composer.addPass(pass); composer.addPass(bloom); composer.addPass(new OutputPass());
      resize();
    }
    pass.camera = camera;
    // pixels are many small sources: a gentler, wider bloom over them than over a beam (the room's haze round the lamp)
    if (pix.active) { bloom.strength = 0.24; bloom.radius = 0.45; bloom.threshold = 0.32; } else { bloom.strength = 0.85; bloom.radius = 0.55; bloom.threshold = 0.82; }
    composer.render();
  }
  function resize() {
    if (!composer) return;
    const size = renderer.getSize(v());
    composer.setPixelRatio(full ? renderer.getPixelRatio() : Math.min(1, renderer.getPixelRatio()));      // bloom and smoke: a light picture while working
    composer.setSize(size.x, size.y);
  }

  return {
    set, enable, update, render, resize, levels,
    get on() { return on; },
    get lights() { return lights; },
    /** The parts moved or were shown, hidden or built again: the rays are cast again. */
    moved() { dirty = true; },
    /** Full quality (the screen's own pixels: for Record), or the lighter picture to work in. */
    quality(best) { full = !!best; resize(); },
    restyled() { parts = null; renderer.shadowMap.needsUpdate = true; },
    rebuilt() { blockers = []; parts = null; if (on) { makeBlockers(); makeStage(); } dirty = true; restyle(); },
    /** What the rays meet, for a test: the parts they can meet, and each light's rays and how long they are. */
    probe() {
      return { blockers: blockers.length, stage: stage?.children.length ?? 0, rigs: rigs.map((r) => {
        const A = r.beam?.geometry.attributes, n = r.beam?.geometry.instanceCount ?? 0, lens = [];
        for (let i = 0; i < n; i++) lens.push(Math.round(Math.hypot(A.iEnd.getX(i) - A.iStart.getX(i), A.iEnd.getY(i) - A.iStart.getY(i), A.iEnd.getZ(i) - A.iStart.getZ(i))));
        return { name: r.L.name, rays: n, at: r.pos?.toArray().map(Math.round), shortest: Math.min(...lens), longest: Math.max(...lens) };
      }) };
    },
    /** The build's faces.json (its pixels, faces and LEDs): before set(), when a build is opened. */
    described(geo) { described = geo; },
    get pixels() { return pix; },
    level(name, value) { levels[name] = Math.max(0, Math.min(1, value)); if (name === 'room') restyle(); },
    /** Levels for one picture (a video's frame, then back): set without what restyle() does to every material; the
     *  room's light and the background follow. */
    lightly(values) {
      for (const [k, v] of Object.entries(values)) if (k in levels || lights.some((L) => L.name === k)) levels[k] = Math.max(0, Math.min(1, v));
      look.dim?.(on ? levels.room : 1);
    },
  };
}

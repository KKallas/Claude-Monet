// The navigation cube, after Adam Designer's: a small labelled cube in the top right corner of the view, turned as the
// view is. Its faces, edges and corners are places to look from: a click turns the view to look from there.
import * as THREE from 'three';

function labelTexture(text) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#212738';
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = '#3a4368';
  ctx.lineWidth = 3;
  ctx.strokeRect(1.5, 1.5, 125, 125);
  ctx.fillStyle = '#d4d4d4';
  ctx.font = '700 22px Rajdhani, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 64, 66);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/**
 * The cube of one view. Returns {size, rightInset, rect(width), contains(width, x, y), zoneAt(width, x, y), hover(zone),
 * draw(renderer, camera, target, width, height)}: x and y are CSS pixels in the view, a zone is {dir} (from the part
 * towards the eye). `rightInset` is how far the right rail pushes the cube in from the edge.
 */
export function createNavCube() {
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  // built Y up, as BoxGeometry lays out its faces and their labels, then turned so that Top is +Z and Front is -Y
  const cube = new THREE.Group();
  cube.rotation.x = Math.PI / 2;
  scene.add(cube);
  // BoxGeometry's faces in order: +X, -X, +Y, -Y, +Z, -Z
  const faces = ['RIGHT', 'LEFT', 'TOP', 'BOTTOM', 'FRONT', 'BACK'].map((t) => new THREE.MeshBasicMaterial({ map: labelTexture(t), toneMapped: false }));
  cube.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), faces));
  const axes = new THREE.AxesHelper(0.9);      // X red, Y green, Z blue, from the front left bottom corner
  axes.position.set(-0.7, -0.7, -0.7);
  axes.material.toneMapped = false;
  scene.add(axes);

  // a click zone over every face, edge and corner, lit while the pointer is on it
  const zones = [];
  for (const sx of [-1, 0, 1]) for (const sy of [-1, 0, 1]) for (const sz of [-1, 0, 1]) {
    if (!sx && !sy && !sz) continue;
    const size = (s) => (s === 0 ? 0.62 : 0.24);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(size(sx), size(sy), size(sz)),
      new THREE.MeshBasicMaterial({ color: 0xd4832f, transparent: true, opacity: 0, depthTest: false, toneMapped: false }));
    mesh.position.set(sx * 0.5, sy * 0.5, sz * 0.5);
    mesh.renderOrder = 1;
    cube.add(mesh);
    zones.push({ mesh, dir: new THREE.Vector3(sx, sy, sz).normalize().applyEuler(cube.rotation) });
  }
  const ray = new THREE.Raycaster();
  let lit = null;

  const nav = {
    size: 110,
    margin: 10,
    top: 10,
    rightInset: 0,
    rect(width) { return { x: width - nav.size - nav.margin - nav.rightInset, y: nav.top, w: nav.size, h: nav.size }; },
    contains(width, x, y) { const r = nav.rect(width); return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; },
    zoneAt(width, x, y) {
      if (!nav.contains(width, x, y)) return null;
      const r = nav.rect(width);
      ray.setFromCamera(new THREE.Vector2(((x - r.x) / r.w) * 2 - 1, -((y - r.y) / r.h) * 2 + 1), camera);
      const hit = ray.intersectObjects(zones.map((z) => z.mesh), false)[0];
      return hit ? zones.find((z) => z.mesh === hit.object) : null;
    },
    hover(zone) {
      if (zone === lit) return;
      if (lit) lit.mesh.material.opacity = 0;
      lit = zone;
      if (lit) lit.mesh.material.opacity = 0.55;
    },
    /** Drawn over the frame just rendered, in its own corner, looking from where the view's camera looks. */
    draw(renderer, main, target, width, height) {
      const dir = main.position.clone().sub(target);
      if (dir.lengthSq() < 1e-9) dir.set(0, 0, 1);
      camera.position.copy(dir.normalize().multiplyScalar(3.6));
      camera.up.copy(main.up);
      camera.lookAt(0, 0, 0);
      const r = nav.rect(width), y = height - r.y - r.h;
      renderer.autoClear = false;
      renderer.clearDepth();
      renderer.setViewport(r.x, y, r.w, r.h);
      renderer.setScissor(r.x, y, r.w, r.h);
      renderer.setScissorTest(true);
      renderer.render(scene, camera);
      renderer.setScissorTest(false);
      renderer.setViewport(0, 0, width, height);
      renderer.autoClear = true;
    },
  };
  return nav;
}

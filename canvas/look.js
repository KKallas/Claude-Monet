// The look: how the part is drawn. Three styles (rendered, shaded, hidden line) and three materials.
//
// The rendered style is Adam Designer's world brought over: its room environment (RoomEnvironment through PMREM,
// sigma 0.04), AgX tone mapping at exposure 1, one white sun of strength 2 at azimuth 55 / elevation 47, and its
// physical materials (its "Brushed aluminium" and "White PVC" values). There it runs on WebGPU with node materials
// and a post chain; here the same recipe is set on plain three.js materials, so there are no screen-space
// reflections. Monet is Z up where Adam is Y up: the environment and the sun are turned to match.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const MATERIALS = {
  pla: { name: 'PLA, printed', color: '#c9ced8' },
  pom: { name: 'POM (acetal)', color: '#f2f2f0' },
  aluminium: { name: 'Aluminium', color: '#c0c3c8' },
};
export const STYLES = { rendered: 'Rendered', shaded: 'Shaded', hidden: 'Hidden line' };
const PAPER = '#161b27';          // hidden line: the faces take the colour of the page, only lines remain
const LAYER = 0.2, LINE = 0.4;    // mm: a 0.4 mm nozzle lays lines 0.4 wide in layers 0.2 tall

// A printed part, as a perfect 0.4 mm nozzle would leave it: on the walls every layer is a rounded bead, on tops
// and bottoms the lines lie side by side on the diagonal. Done to the normal only, in the part's own frame (Z is up
// off the bed). Finer than a pixel it fades out, as it does to the eye, instead of shimmering.
function printed(material) {
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uLayer = { value: LAYER };
    shader.uniforms.uLine = { value: LINE };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vPrintAt;\nvarying vec3 vPrintNormal;\nvarying vec3 vPrintUp;\nvarying vec3 vPrintAcross;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vPrintAt = position;
        vPrintNormal = normal;
        vPrintUp = normalMatrix * vec3(0.0, 0.0, 1.0);
        vPrintAcross = normalMatrix * vec3(0.70710678, 0.70710678, 0.0);`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vPrintAt;\nvarying vec3 vPrintNormal;\nvarying vec3 vPrintUp;\nvarying vec3 vPrintAcross;\nuniform float uLayer;\nuniform float uLine;')
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        {
          float wall = 1.0 - abs(normalize(vPrintNormal).z);                     // 1 on a wall, 0 on a top or a bottom
          float seenLayers = 1.0 - smoothstep(0.3, 0.9, fwidth(vPrintAt.z) / uLayer);
          float across = dot(vPrintAt.xy, vec2(0.70710678));
          float seenLines = 1.0 - smoothstep(0.3, 0.9, fwidth(across) / uLine);
          vec3 bead = vPrintUp * sin(6.2831853 * vPrintAt.z / uLayer) * wall * seenLayers * 0.6
                    + vPrintAcross * sin(6.2831853 * across / uLine) * (1.0 - wall) * seenLines * 0.4;
          normal = normalize(normal + bead);
        }`);
  };
  material.customProgramCacheKey = () => 'monet-printed';
  return material;
}

/**
 * The look of one view. `lights` are the plain lights of the shaded style: {hemi, head}.
 * Returns {style, set(style), material(spec), edge(), base()}: spec is {material, color}.
 */
export function createLook(renderer, scene, lights) {
  const room = new THREE.PMREMGenerator(renderer);
  const environment = room.fromScene(new RoomEnvironment(), 0.04).texture;
  room.dispose();
  const sun = new THREE.DirectionalLight(0xffffff, 2);
  const az = 55 * Math.PI / 180, el = 47 * Math.PI / 180;
  sun.position.set(Math.sin(az) * Math.cos(el), -Math.cos(az) * Math.cos(el), Math.sin(el)).multiplyScalar(20000);
  scene.add(sun);
  let style = 'rendered';

  const look = {
    get style() { return style; },
    set(next) {
      style = STYLES[next] ? next : 'rendered';
      const rendered = style === 'rendered';
      scene.environment = rendered ? environment : null;
      scene.environmentIntensity = 1;
      scene.environmentRotation.set(Math.PI / 2, 0, 0);      // the room's ceiling to +Z
      sun.visible = rendered;
      lights.hemi.visible = lights.head.visible = style === 'shaded';
      renderer.toneMapping = rendered ? THREE.AgXToneMapping : THREE.NoToneMapping;
      renderer.toneMappingExposure = 1;
      scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });      // tone mapping is compiled in
    },
    /** The material of a part's faces. Vertex colours stay on in every style: they carry what is selected. */
    material(spec = {}) {
      const common = { vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 };
      if (style === 'hidden') return new THREE.MeshBasicMaterial({ ...common, toneMapped: false });
      if (style === 'shaded') return new THREE.MeshStandardMaterial({ ...common, metalness: 0, roughness: 0.8 });
      const kind = MATERIALS[spec.material] ? spec.material : 'pla';
      const color = new THREE.Color(spec.color || MATERIALS[kind].color);
      if (kind === 'aluminium') return new THREE.MeshPhysicalMaterial({ ...common, color, metalness: 1, roughness: 0.35 });
      if (kind === 'pom') return new THREE.MeshPhysicalMaterial({ ...common, color, metalness: 0, roughness: 0.42, clearcoat: 0.2, clearcoatRoughness: 0.35 });
      return printed(new THREE.MeshPhysicalMaterial({ ...common, color, metalness: 0, roughness: 0.5 }));
    },
    /** The colour and strength of the part's edges in this style. */
    edge() {
      return style === 'hidden' ? { color: 0xdfe4f0, opacity: 1 } : style === 'rendered' ? { color: 0x0b0d13, opacity: 0.5 } : { color: 0x10131b, opacity: 1 };
    },
    /** What an unselected face is painted: nothing over a material, the page under hidden lines, grey when shaded. */
    base() {
      return new THREE.Color(style === 'rendered' ? '#ffffff' : style === 'hidden' ? PAPER : '#b9c2d6');
    },
  };
  look.set(style);
  return look;
}

// The mark: a black hole after Interstellar's Gargantua, drawn live on every <canvas class="hole">. Each pixel is a
// ray of light followed back from the eye and bent by the hole as light is (the photon orbit equation of a
// Schwarzschild hole, horizon radius 1); where it crosses the disk it picks up the disk's glow, where it falls in it
// goes black. So the far side of the disk shows over and under the shadow, as in the film. The disk turns, the inner
// rings faster (Kepler). A plain script: the pages load it with defer.
(() => {
  const VERT = 'attribute vec2 p; void main() { gl_Position = vec4(p, 0., 1.); }';
  const FRAG = `precision highp float;
uniform vec2 res; uniform float t;
const float PI = 3.14159265, IN = 2.6, OUT = 8.0;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p, float n) {      // value noise, wrapped every n along x so the disk has no seam
  vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  float a = hash(vec2(mod(i.x, n), i.y)), b = hash(vec2(mod(i.x + 1., n), i.y));
  float c = hash(vec2(mod(i.x, n), i.y + 1.)), d = hash(vec2(mod(i.x + 1., n), i.y + 1.));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
vec4 disk(vec3 q, vec3 dir) {
  float r = length(q.xz);
  if (r < IN || r > OUT) return vec4(0.);
  float a = atan(q.z, q.x) / (2. * PI) + .5;
  float spin = t * .9 * pow(r, -1.5) * 6.;       // turns per second, faster inside
  float s = 0., amp = .5, n = 14.;
  for (int o = 0; o < 4; o++) { s += amp * noise(vec2((a + spin) * n, r * 2.2 * n / 14.), n); n *= 2.; amp *= .5; }
  float edge = smoothstep(IN, IN + .4, r) * (1. - smoothstep(OUT - 4., OUT, r));
  vec3 v = normalize(vec3(-q.z, 0., q.x)) * sqrt(.5 / r);       // the gas moves round at Kepler's speed
  float g = 1. / (1. + dot(v, dir));                            // brighter on the side coming at us, a little
  float hot = pow(IN / r, 1.6) * edge * (.35 + 1.1 * s * s) * g * g;
  vec3 col = mix(vec3(1., .42, .1), vec3(1., .93, .78), clamp(hot * 1.4, 0., 1.));
  return vec4(col * hot * 3.2, clamp(hot * 1.6, 0., 1.));
}
void main() {
  vec2 uv = (gl_FragCoord.xy - .5 * res) / res.y;
  vec3 eye = vec3(0., 1.15, -17.), ahead = normalize(-eye);
  vec3 side = normalize(cross(vec3(0., 1., 0.), ahead)), up = cross(ahead, side);
  float roll = -.08; vec2 u = mat2(cos(roll), -sin(roll), sin(roll), cos(roll)) * uv;
  vec3 p = eye, v = normalize(ahead + .6 * (u.x * side + u.y * up));
  float h2 = dot(cross(p, v), cross(p, v));
  vec3 col = vec3(0.); float alpha = 0.;
  for (int i = 0; i < 220; i++) {
    float r2 = dot(p, p), r = sqrt(r2);
    if (r < 1.) { alpha = 1.; break; }                  // into the horizon: what is behind stays dark
    if (r > 40. || alpha > .99) break;
    float dt = .06 * r;
    v += -1.5 * h2 * p / (r2 * r2 * r) * dt;
    vec3 next = p + v * dt;
    if (p.y * next.y < 0.) {                            // through the plane of the disk
      vec3 q = mix(p, next, p.y / (p.y - next.y));
      vec4 d = disk(q, normalize(v));
      col += (1. - alpha) * d.rgb; alpha += (1. - alpha) * d.a;
    }
    p = next;
  }
  col = 1. - exp(-col * 1.4);
  float fade = smoothstep(0., .18, .5 * res.x / res.y - abs(uv.x));      // the disk thins out before the frame does
  col *= fade; alpha *= fade;
  gl_FragColor = vec4(col, max(alpha, max(col.r, max(col.g, col.b))));
}`;
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function start(canvas) {
    const gl = canvas.getContext('webgl', { premultipliedAlpha: true, antialias: false });
    if (!gl) return;
    const shader = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn('hole:', gl.getProgramInfoLog(prog)); return; }
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const at = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(at);
    gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
    const res = gl.getUniformLocation(prog, 'res'), time = gl.getUniformLocation(prog, 't');
    const t0 = performance.now();
    function frame(now) {
      const dpr = Math.min(devicePixelRatio || 1, 2), w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.uniform2f(res, w, h);
      gl.uniform1f(time, still ? 7 : (now - t0) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!still) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  for (const canvas of document.querySelectorAll('canvas.hole')) start(canvas);
})();

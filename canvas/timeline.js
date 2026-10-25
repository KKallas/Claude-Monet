// The timeline of Motion, along the bottom of the view: keyframes of the joints over frames, played, paused, stopped and
// scrubbed. As low as it goes it is the transport and one line with every key on it; dragged taller, every joint has a
// line of its own, a string with its keys on it. Frames are whole; between two keys a joint moves evenly, before the
// first and after the last it holds. The keys are kept in the project (the page's save hook); the joints are posed
// through the page's hooks, so this knows nothing of three.js or the server.
export const EMPTY = () => ({ fps: 30, length: 120, tracks: {} });

/** A track's value at frame `f` (a fraction while playing): straight between its keys, held outside them. */
export function valueAt(keys, f) {
  if (!keys?.length) return undefined;
  if (f <= keys[0][0]) return keys[0][1];
  const end = keys[keys.length - 1];
  if (f >= end[0]) return end[1];
  let i = 1;
  while (keys[i][0] < f) i++;
  const [f0, v0] = keys[i - 1], [f1, v1] = keys[i];
  return f1 === f0 ? v1 : v0 + (v1 - v0) * (f - f0) / (f1 - f0);
}
/** Every keyed joint's value at frame `f`. */
export const poseAt = (anim, f) => Object.fromEntries(Object.entries(anim.tracks).filter(([, k]) => k.length).map(([j, k]) => [j, valueAt(k, f)]));
/** A key set: one to a frame, in order. */
export const setKey = (keys = [], f, v) => [...keys.filter(([g]) => g !== f), [f, v]].sort((a, b) => a[0] - b[0]);
/** The frames that have a key on any joint, in order. */
export const keyFrames = (tracks) => [...new Set(Object.values(tracks).flat().map(([f]) => f))].sort((a, b) => a - b);

// a key is told by "joint:frame"; the line of all keys is the joint "*", and its key stands for every key at that frame
const idOf = (j, f) => `${j}:${f}`;
const split = (id) => { const i = id.lastIndexOf(':'); return [id.slice(0, i), Number(id.slice(i + 1))]; };
/** Every key the ids name, the "*" ones standing for every key at their frame. */
export function expand(tracks, ids) {
  const out = new Set();
  for (const id of ids) {
    const [j, f] = split(id);
    if (j !== '*') out.add(id);
    else for (const [k, keys] of Object.entries(tracks)) if (keys.some(([g]) => g === f)) out.add(idOf(k, f));
  }
  return out;
}
/** Keys moved by `d` frames, as far as they can go within 0…length: one landing on another key takes its place. */
export function moveKeys(tracks, ids, d, length) {
  const fs = [...ids].map((id) => split(id)[1]);
  if (!fs.length) return { tracks, ids };
  d = Math.max(-Math.min(...fs), Math.min(length - Math.max(...fs), d));
  const out = {}, moved = new Set();
  for (const [j, keys] of Object.entries(tracks)) {
    const going = keys.filter(([f]) => ids.has(idOf(j, f))).map(([f, v]) => [f + d, v]);
    const landed = new Set(going.map(([f]) => f));
    out[j] = [...keys.filter(([f]) => !ids.has(idOf(j, f)) && !landed.has(f)), ...going].sort((a, b) => a[0] - b[0]);
    for (const [f] of going) moved.add(idOf(j, f));
  }
  return { tracks: out, ids: moved };
}
export function deleteKeys(tracks, ids) {
  const out = {};
  for (const [j, keys] of Object.entries(tracks)) { const left = keys.filter(([f]) => !ids.has(idOf(j, f))); if (left.length) out[j] = left; }
  return out;
}
/** Frames between the numbers on the ruler: the fewest that leave `px` pixels between two. */
export function tickStep(length, width, px = 52) {
  for (let s = 1; ; s *= 10) for (const m of [1, 2, 5]) if ((s * m * width) / Math.max(1, length) >= px) return s * m;
}

const ROW = 22, LOW = 84;      // a joint's line; the timeline as low as it goes: the bar, the ruler and the line of all keys
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v) => String(Math.round(v * 100) / 100);
const KIND = { revolute: '⟳', slider: '⇄' };
const PLAY = '▶︎', PAUSE = '❚❚';

/**
 * The timeline in `root`. hooks: pose() the joints' values now, setPose(values) put them there, save(anim, key) keep
 * it, height(px) as it is sized or hidden. The joints that can be keyed come with show().
 */
export function createTimeline(root, hooks) {
  let anim = EMPTY(), key = null, from = null, frame = 0, playing = false, raf = 0, last = 0, saving = 0, sel = new Set(), joints = [];
  let auto = false, loop = true, h = LOW;
  try { auto = localStorage.getItem('monet.tl.auto') === '1'; h = Math.max(LOW, Number(localStorage.getItem('monet.tl.h')) || LOW); } catch { /* no storage */ }
  root.innerHTML = `<div class="tl-grip" title="drag up: a line for every joint; down: one line of all keys"></div>
    <div class="tl-bar">
      <button data-tl="first" title="to the first frame (Home)">⇤</button><button data-tl="prev" title="to the keyframe before">◂◆</button>
      <button data-tl="play" class="tl-play" title="play, pause (Space)">${PLAY}</button><button data-tl="stop" title="stop: back to the first frame">■</button>
      <button data-tl="next" title="to the keyframe after">◆▸</button><button data-tl="last" title="to the last frame (End)">⇥</button>
      <span class="tl-sep"></span>
      <span class="tl-lbl">frame</span><input class="num" data-tlf="frame" inputmode="numeric" title="the frame shown (← → step it, Shift by ten)">
      <span class="tl-lbl">/</span><input class="num" data-tlf="length" inputmode="numeric" title="how many frames it runs">
      <span class="tl-sec mono"></span>
      <input class="num" data-tlf="fps" inputmode="numeric" title="frames a second"><span class="tl-lbl">fps</span>
      <span class="tl-sep"></span>
      <button data-tl="key" title="a keyframe for every joint, where it is now, at this frame (K)">◆ Key</button>
      <button data-tl="auto" class="tl-auto" title="auto key: a joint moved by hand is keyed at this frame">● Auto</button>
      <button data-tl="del" title="delete the selected keyframes (Delete)">✕</button>
      <button data-tl="loop" title="round and round, or once">⟲</button>
      <span class="tl-sp"></span><span class="tl-tip"></span>
    </div>
    <div class="tl-body"></div>`;
  const $ = (s) => root.querySelector(s), body = $('.tl-body');

  // the frame under x on a lane's track `b`, measured when the press began
  const frameOf = (b, x) => Math.max(0, Math.min(anim.length, Math.round(((x - b.left) / b.width) * anim.length)));
  const at = (f) => `${(f / anim.length) * 100}%`;

  function draw() {
    const all = keyFrames(anim.tracks), now = Math.round(frame), shown = expand(anim.tracks, sel);
    const diamond = (j, f, v) => `<i class="tl-d ${shown.has(idOf(j, f)) || (j === '*' && sel.has(idOf(j, f))) ? 'sel' : ''} ${f === now ? 'now' : ''}" data-id="${esc(idOf(j, f))}"
      style="left:${at(f)}" title="frame ${f}${v == null ? '' : `: ${num(v)}`}"></i>`;
    const width = body.clientWidth - 140, step = tickStep(anim.length, Math.max(100, width));
    const ticks = [];
    for (let f = 0; f <= anim.length; f += step) ticks.push(`<span class="tl-tick ${anim.length - f < step / 2 ? 'end' : ''}" style="left:${at(f)}">${f}</span>`);
    for (let f = 0, s = step / (step % 5 ? 2 : 5); s >= 1 && f <= anim.length; f += s) if (f % step) ticks.push(`<i class="tl-sub" style="left:${at(f)}"></i>`);
    const strings = joints.map((j, i) => {
      const keys = anim.tracks[j.name] ?? [];
      return `<div class="tl-row tl-joint ${keys.length ? 'on' : ''} ${j.locked ? 'locked' : ''} ${i >= 3 ? 'wound' : ''}" style="--s:${(1 + Math.min(i, 5) * 0.4).toFixed(1)}px">
        <div class="tl-name"><span class="tl-k">${KIND[j.kind] ?? '·'}</span><b title="${esc(j.name)}">${esc(j.name)}</b><span class="tl-v" data-tlv="${esc(j.name)}"></span>
          <button class="tl-one" data-one="${esc(j.name)}" title="key ${esc(j.name)} at this frame, where it is now" ${j.locked ? 'disabled' : ''}>◆</button></div>
        <div class="tl-lane" data-lane="${esc(j.name)}"><div class="tl-track"><i class="tl-string"></i>${keys.map(([f, v]) => diamond(j.name, f, v)).join('')}</div></div></div>`;
    }).join('');
    body.innerHTML = `<div class="tl-row tl-ruler"><div class="tl-name"></div><div class="tl-lane" data-lane="ruler"><div class="tl-track">${ticks.join('')}<span class="tl-flag"></span></div></div></div>
      <div class="tl-row tl-all"><div class="tl-name"><b>keys</b><span class="tl-v">${all.length ? `${Object.values(anim.tracks).flat().length} on ${Object.keys(anim.tracks).length}` : 'none yet'}</span></div>
        <div class="tl-lane" data-lane="*"><div class="tl-track"><i class="tl-string"></i>${all.map((f) => diamond('*', f)).join('')}</div></div></div>
      ${strings || '<div class="tl-row"><div class="tl-name muted">no joints</div></div>'}`;
    $('.tl-tip').textContent = h <= LOW + 4 && joints.length ? 'drag the top edge up: a line for every joint' : '';
    paint();
  }
  // what moves with the frame: the playhead, the numbers, the keys under it, the joints' values
  function paint() {
    const now = Math.round(frame);
    root.style.setProperty('--f', String(frame / anim.length));
    const flag = $('.tl-flag');
    if (flag) flag.textContent = now;
    const fi = $('[data-tlf="frame"]');
    if (document.activeElement !== fi) fi.value = now;
    for (const [k, v] of [['length', anim.length], ['fps', anim.fps]]) { const el = $(`[data-tlf="${k}"]`); if (document.activeElement !== el) el.value = v; }
    $('.tl-sec').textContent = `${(frame / anim.fps).toFixed(2)} s`;
    $('.tl-play').textContent = playing ? PAUSE : PLAY;
    $('.tl-play').classList.toggle('on', playing);
    $('[data-tl="auto"]').classList.toggle('on', auto);
    $('[data-tl="loop"]').classList.toggle('on', loop);
    $('[data-tl="del"]').disabled = !sel.size;
    root.classList.toggle('playing', playing);
    body.querySelectorAll('.tl-d').forEach((d) => d.classList.toggle('now', split(d.dataset.id)[1] === now));
    values();
  }
  function values() {
    const p = hooks.pose(), unit = Object.fromEntries(joints.map((j) => [j.name, j.unit]));
    body.querySelectorAll('[data-tlv]').forEach((el) => { el.textContent = `${num(p[el.dataset.tlv] ?? 0)}${unit[el.dataset.tlv] ?? ''}`; });
  }

  function go(f) {
    frame = Math.max(0, Math.min(anim.length, f));
    if (Object.keys(anim.tracks).length) hooks.setPose(poseAt(anim, frame));
    paint();
  }
  function tick(t) {
    frame += ((t - last) / 1000) * anim.fps;
    last = t;
    if (frame >= anim.length) { if (loop) frame %= anim.length; else { frame = anim.length; playing = false; } }
    go(frame);
    if (playing) raf = requestAnimationFrame(tick);
  }
  function play() {
    if (playing) return;
    if (frame >= anim.length) frame = 0;
    playing = true; last = performance.now();
    raf = requestAnimationFrame(tick);
    paint();
  }
  function pause() {
    if (!playing) return;
    playing = false; cancelAnimationFrame(raf);
    frame = Math.round(frame);
    go(frame);
  }
  const stop = () => { pause(); go(0); };

  function changed(next) {
    anim = { ...anim, tracks: next };
    clearTimeout(saving);
    const k = key, a = structuredClone(anim);
    saving = setTimeout(() => { saving = 0; hooks.save(a, k); }, 350);
    draw();
  }
  function keyAll(names) {
    const p = hooks.pose(), f = Math.round(frame), next = { ...anim.tracks };
    for (const n of names) next[n] = setKey(next[n], f, p[n] ?? 0);
    frame = f;
    changed(next);
  }
  const free = () => joints.filter((j) => !j.locked).map((j) => j.name);
  function remove() { if (!sel.size) return; const next = deleteKeys(anim.tracks, expand(anim.tracks, sel)); sel = new Set(); changed(next); }
  function jump(dir) {
    const all = keyFrames(anim.tracks), now = Math.round(frame);
    const to = dir < 0 ? all.filter((f) => f < now).pop() : all.find((f) => f > now);
    if (to != null) { pause(); go(to); }
  }

  // the bar
  root.querySelector('.tl-bar').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tl]');
    if (!b) return;
    b.blur();      // so Space plays, not presses the button again
    const a = b.dataset.tl;
    if (a === 'play') { if (playing) pause(); else play(); }
    if (a === 'stop') stop();
    if (a === 'first') { pause(); go(0); }
    if (a === 'last') { pause(); go(anim.length); }
    if (a === 'prev' || a === 'next') jump(a === 'prev' ? -1 : 1);
    if (a === 'key') { pause(); keyAll(free()); }
    if (a === 'del') remove();
    if (a === 'auto') { auto = !auto; try { localStorage.setItem('monet.tl.auto', auto ? '1' : '0'); } catch { /* not kept */ } paint(); }
    if (a === 'loop') { loop = !loop; paint(); }
  });
  root.querySelector('.tl-bar').addEventListener('change', (e) => {
    const k = e.target.dataset.tlf, v = Math.round(Number(e.target.value));
    if (!k) return;
    if (!Number.isFinite(v)) { paint(); return; }
    if (k === 'frame') { pause(); go(v); }
    if (k === 'length') {      // never shorter than its last key
      anim.length = Math.max(1, keyFrames(anim.tracks).pop() ?? 1, Math.min(100000, v));
      frame = Math.min(frame, anim.length);
      changed(anim.tracks);
    }
    if (k === 'fps') { anim.fps = Math.max(1, Math.min(120, v)); changed(anim.tracks); }
    e.target.blur();
  });

  // the lines: a press on a key takes it (Shift: adds it) and drags it along; anywhere else it scrubs. A double-click
  // on a joint's line keys that joint there. The lines are drawn again as keys move, so the pointer is held by the
  // body, which stays, and the lane is measured once, when it is pressed
  body.addEventListener('click', (e) => { const b = e.target.closest('[data-one]'); if (b) { pause(); keyAll([b.dataset.one]); } });
  body.addEventListener('pointerdown', (e) => {
    const lane = e.target.closest('.tl-lane');
    if (e.button !== 0 || !lane) return;
    e.preventDefault();
    pause();
    const track = lane.querySelector('.tl-track').getBoundingClientRect(), d = e.target.closest('.tl-d');
    body.setPointerCapture(e.pointerId);
    let move, up = null;
    if (d) {
      const id = d.dataset.id;
      if (e.shiftKey) { if (sel.has(id)) sel.delete(id); else sel.add(id); } else if (!sel.has(id)) sel = new Set([id]);
      const ids = expand(anim.tracks, sel), tracks0 = anim.tracks, f0 = frameOf(track, e.clientX);
      let moved = false;
      draw();
      move = (m) => {
        const df = frameOf(track, m.clientX) - f0;
        if (!df && !moved) return;
        moved = true;
        const r = moveKeys(tracks0, ids, df, anim.length);
        anim = { ...anim, tracks: r.tracks };
        sel = r.ids;
        draw();
      };
      up = () => { if (moved) changed(anim.tracks); else go(split(id)[1]); };
    } else {
      if (!e.shiftKey && sel.size) { sel = new Set(); draw(); }
      go(frameOf(track, e.clientX));
      move = (m) => go(frameOf(track, m.clientX));
    }
    body.onpointermove = move;
    body.onpointerup = () => up?.();
    body.addEventListener('lostpointercapture', () => { body.onpointermove = body.onpointerup = null; }, { once: true });
  });
  body.addEventListener('dblclick', (e) => {
    const lane = e.target.closest('.tl-lane'), j = lane?.dataset.lane;
    if (!j || e.target.closest('.tl-d') || !joints.some((x) => x.name === j && !x.locked)) return;
    keyAll([j]);
  });

  // the top edge: drag it up for a line per joint
  $('.tl-grip').addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const y0 = e.clientY, h0 = h, g = e.currentTarget;
    g.setPointerCapture(e.pointerId);
    document.body.classList.add('row-resizing');
    g.onpointermove = (m) => size(h0 + y0 - m.clientY);
    g.onpointerup = g.onpointercancel = () => {
      g.onpointermove = g.onpointerup = g.onpointercancel = null;
      document.body.classList.remove('row-resizing');
      try { localStorage.setItem('monet.tl.h', String(h)); } catch { /* not kept */ }
    };
  });
  $('.tl-grip').addEventListener('dblclick', () => size(h > LOW + 4 ? LOW : LOW + 26 + ROW * Math.max(1, joints.length)));
  function size(next) {
    const most = Math.max(LOW, (root.parentElement?.clientHeight ?? 600) - 140);
    h = Math.round(Math.max(LOW, Math.min(most, next)));
    root.style.height = `${h}px`;
    hooks.height(root.hidden ? 0 : h);
    $('.tl-tip').textContent = h <= LOW + 4 && joints.length ? 'drag the top edge up: a line for every joint' : '';
  }

  window.addEventListener('keydown', (e) => {
    if (root.hidden || /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName ?? '') || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key, f = Math.round(frame), by = e.shiftKey ? 10 : 1;
    const act = { ' ': () => (playing ? pause() : play()), Delete: remove, Backspace: remove, Home: () => { pause(); go(0); }, End: () => { pause(); go(anim.length); },
      ArrowLeft: () => { pause(); go(f - by); }, ArrowRight: () => { pause(); go(f + by); }, k: () => keyAll(free()), K: () => keyAll(free()),
      Escape: () => { if (sel.size) { sel = new Set(); draw(); } } }[k];
    if (act) { e.preventDefault(); act(); }
  });
  new ResizeObserver(() => { if (!root.hidden) draw(); }).observe(body);

  return {
    get playing() { return playing; },
    get frame() { return frame; },
    get anim() { return anim; },
    pause, play, stop, go,
    /** Shown or not; `k` names what it animates, `a` is the kept animation, `js` the joints. */
    show(on, k, a, js) {
      root.hidden = !on;
      hooks.height(on ? h : 0);
      if (!on) { pause(); return; }
      root.style.height = `${h}px`;
      if (k !== key) {      // another assembly: from its start
        if (saving) { clearTimeout(saving); hooks.save(structuredClone(anim), key); saving = 0; }
        pause(); key = k; frame = 0; sel = new Set(); from = null;
      }
      // what was kept is taken when it is new, unless a change of ours is still on its way
      if (a !== from && !saving) { from = a; anim = a ? structuredClone({ ...EMPTY(), ...a }) : EMPTY(); frame = Math.min(frame, anim.length); }
      joints = js;
      draw();
    },
    /** Joints moved by hand: playing stops, and with auto key on they are keyed here. */
    touched(names) {
      if (root.hidden) return;
      if (playing) pause();
      if (auto) keyAll(names.filter((n) => joints.some((j) => j.name === n && !j.locked)));
      else values();
    },
    values,
  };
}

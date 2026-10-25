// The sliders, made into a number and an icon. The number is typed into (arrows step it); a click on the icon opens a
// sheet under it: a slider of the page's own on top, and under it what to set it to at once: its default, the last
// value set in the same field on any object (any joint of a kind, say), and 0, 25, 50, 75 and 100 % of the way along.
// The <input type=range> stays, hidden, as the one value: the page reads it, sets it and listens to it as before, and
// the dial follows. Its data- says how it is shown: icon, label, scale (100 shows a 0…1 as a percentage), unit, key
// (what "the same field" is; else its id or name) and default (else its value attribute).
export const PRESETS = [0, 25, 50, 75, 100];

/** `v` kept within min…max and put on the step, without the float's tail. */
export function snap(v, min, max, step) {
  const s = step > 0 ? step : (max - min) / 100;
  const n = Math.min(max, Math.max(min, min + Math.round((v - min) / s) * s));
  return Number(n.toFixed(decimals(s) + 2));
}
/** The value `p` per cent of the way from min to max. */
export const along = (p, min, max, step) => snap(min + (max - min) * p / 100, min, max, step);
export const decimals = (x) => { const t = String(x); return t.includes('e-') ? Number(t.split('e-')[1]) : (t.split('.')[1] ?? '').length; };

const LAST = 'monet.dials';
const lastOf = (key) => { try { return JSON.parse(localStorage.getItem(LAST) || '{}')[key]; } catch { return undefined; } };
function remember(key, v) {
  try { const all = JSON.parse(localStorage.getItem(LAST) || '{}'); all[key] = v; localStorage.setItem(LAST, JSON.stringify(all)); } catch { /* not remembered */ }
}

const VALUE = globalThis.HTMLInputElement && Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
const limits = (r) => ({ min: Number(r.min || 0), max: Number(r.max || 100), step: Number(r.step) || 1 });
// shown to as many places as one step needs: a step of 0.667 % shows whole per cents
const shown = (r, v) => { const k = Number(r.dataset.scale || 1); return Number((v * k).toFixed(Math.max(0, Math.ceil(-Math.log10(limits(r).step * k) - 1e-9)))); };
const keyOf = (r) => r.dataset.key || r.id || r.name;

/** Every range under `root` not yet made a dial. A number field right after one (input.num) is taken as its own. */
export function dials(root = document) {
  root.querySelectorAll('input[type=range]:not([data-dialled])').forEach(dial);
}

function dial(r) {
  r.dataset.dialled = '';
  const wrap = document.createElement('span');
  wrap.className = 'dial';
  r.before(wrap);
  const theirs = r.nextElementSibling?.matches('input.num') ? r.nextElementSibling : null;
  const ico = Object.assign(document.createElement('button'), { type: 'button', className: 'dial-ico', textContent: r.dataset.icon || '◈',
    title: `${r.title || r.dataset.label || 'set it'}: click for a slider and presets` });
  const num = theirs ?? Object.assign(document.createElement('input'), { className: 'num dial-num', inputMode: 'decimal', title: r.title });
  wrap.append(ico, r, num);
  if (!theirs && r.dataset.unit) wrap.append(Object.assign(document.createElement('span'), { className: 'dial-unit', textContent: r.dataset.unit }));

  const show = () => {
    const { min, max } = limits(r), v = Number(VALUE.get.call(r));
    wrap.style.setProperty('--p', `${max > min ? (100 * (v - min)) / (max - min) : 0}%`);
    if (!theirs && document.activeElement !== num) num.value = shown(r, v);
    if (open?.r === r) paintSheet();
  };
  // the page sets r.value as it always did: the number follows
  Object.defineProperty(r, 'value', { configurable: true, get: () => VALUE.get.call(r), set: (v) => { VALUE.set.call(r, v); show(); } });
  r.addEventListener('input', show);
  const mirror = () => { wrap.hidden = r.hidden; if (!theirs) num.disabled = r.disabled; ico.disabled = r.disabled; };
  new MutationObserver(mirror).observe(r, { attributes: true, attributeFilter: ['hidden', 'disabled'] });
  mirror();

  if (!theirs) {
    num.addEventListener('change', () => {
      const t = Number(num.value.replace(',', '.').replace('%', '')) / Number(r.dataset.scale || 1);
      if (Number.isFinite(t)) set(r, t, true); else show();
    });
    num.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      set(r, Number(r.value) + (e.key === 'ArrowUp' ? 1 : -1) * limits(r).step * (e.shiftKey ? 10 : 1), true);
    });
    num.addEventListener('blur', show);
  } else num.addEventListener('change', () => setTimeout(() => remember(keyOf(r), Number(r.value))));      // the page sets it; then it is the last
  ico.addEventListener('click', (e) => { e.stopPropagation(); if (open?.r === r) close(); else sheet(r, ico); });
  show();
}

/** Set a dial's range as if a hand did it: the page hears input, and change when it is let go. */
function set(r, v, done) {
  const { min, max, step } = limits(r), next = snap(v, min, max, step);
  if (next !== Number(r.value)) { r.value = next; r.dispatchEvent(new Event('input', { bubbles: true })); }
  if (done) { remember(keyOf(r), next); r.dispatchEvent(new Event('change', { bubbles: true })); }
}

// ---- the sheet: one at a time, under the icon that opened it -------------------------------------------------------
let open = null;      // { r, ico, el, find }
const TICKS = Array.from({ length: 21 }, (_, i) => `<i style="left:${i * 5}%" class="${i % 5 ? '' : 'big'}"></i>`).join('');

function sheet(r, ico) {
  close();
  const el = document.body.appendChild(Object.assign(document.createElement('div'), { className: 'dial-pop', tabIndex: -1 }));
  el.innerHTML = `<div class="dial-head"><span class="dial-name"></span><span class="dial-read"></span></div>
    <div class="dial-track" title="drag, or click where it should be"><div class="dial-ticks">${TICKS}</div><i class="dial-fill"></i><i class="dial-knob"></i></div>
    <div class="dial-ends"><span></span><span></span></div>
    <div class="dial-presets"><button data-p="default">Default</button><button data-p="last">Last</button>
      ${PRESETS.map((p) => `<button data-p="${p}">${p}</button>`).join('')}</div>`;
  // the panel is drawn again now and then: the range is looked up again by its id or name
  const find = r.id ? `#${CSS.escape(r.id)}` : r.name ? `input[type=range][name="${CSS.escape(r.name)}"]` : null;
  open = { r, ico, el, find };
  ico.classList.add('on');
  place();
  paintSheet();
  el.focus({ preventScroll: true });

  const track = el.querySelector('.dial-track');
  const toValue = (x) => { const b = track.getBoundingClientRect(), { min, max } = limits(live()); return min + (max - min) * Math.min(1, Math.max(0, (x - b.left) / b.width)); };
  track.onpointerdown = (e) => {
    if (e.button !== 0 || live().disabled) return;
    track.setPointerCapture(e.pointerId); el.classList.add('dragging');
    set(live(), toValue(e.clientX));
    track.onpointermove = (m) => set(live(), toValue(m.clientX));
    track.onpointerup = track.onpointercancel = () => { track.onpointermove = track.onpointerup = track.onpointercancel = null; el.classList.remove('dragging'); set(live(), Number(live().value), true); };
  };
  el.querySelector('.dial-presets').onclick = (e) => {
    const b = e.target.closest('[data-p]'), v = b && presetValue(live(), b.dataset.p);
    if (v != null && !live().disabled) { set(live(), v, true); paintSheet(); }
  };
  el.onkeydown = (e) => {
    const x = live(), { min, max, step } = limits(x), k = e.shiftKey ? 10 : 1;
    const to = { ArrowRight: Number(x.value) + step * k, ArrowUp: Number(x.value) + step * k, ArrowLeft: Number(x.value) - step * k, ArrowDown: Number(x.value) - step * k, Home: min, End: max }[e.key];
    if (to != null) { e.preventDefault(); set(x, to, true); }
    if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); close(); ico.focus({ preventScroll: true }); }
  };
}

const live = () => (open.r.isConnected || !open.find ? open.r : (open.r = document.querySelector(open.find) ?? open.r));
function presetValue(r, p) {
  const { min, max, step } = limits(r);
  if (p === 'default') return snap(Number(r.dataset.default ?? r.defaultValue), min, max, step);
  if (p === 'last') { const v = lastOf(keyOf(r)); return Number.isFinite(v) ? snap(v, min, max, step) : null; }
  return along(Number(p), min, max, step);
}

function paintSheet() {
  if (!open) return;
  const r = live(), el = open.el, { min, max } = limits(r), v = Number(r.value), unit = r.dataset.unit ?? '';
  const words = (x) => `${shown(r, x)}${unit ? `<small>${unit}</small>` : ''}`;
  el.style.setProperty('--p', `${max > min ? (100 * (v - min)) / (max - min) : 0}%`);
  el.querySelector('.dial-name').textContent = r.dataset.label || r.title || '';
  el.querySelector('.dial-read').innerHTML = words(v);
  const [lo, hi] = el.querySelectorAll('.dial-ends span');
  lo.innerHTML = words(min); hi.innerHTML = words(max);
  el.querySelectorAll('[data-p]').forEach((b) => {
    const x = presetValue(r, b.dataset.p);
    b.disabled = x == null || r.disabled;
    b.classList.toggle('on', x != null && Math.abs(x - v) < 1e-9);
    b.title = x == null ? 'nothing set in this field yet' : `${b.dataset.p === 'default' ? 'its default' : b.dataset.p === 'last' ? 'the last value set here, on any object' : `${b.dataset.p} % of the way`}: ${shown(r, x)}${unit}`;
  });
}

function place() {
  const b = open.ico.getBoundingClientRect(), el = open.el, w = el.offsetWidth, h = el.offsetHeight;
  const left = Math.max(8, Math.min(innerWidth - w - 8, b.left - 6));
  const top = b.bottom + 6 + h <= innerHeight - 8 ? b.bottom + 6 : Math.max(8, b.top - 6 - h);
  Object.assign(el.style, { left: `${left}px`, top: `${top}px` });
}

export function close() {
  if (!open) return;
  open.el.remove(); open.ico.classList.remove('on');
  open = null;
}
if (globalThis.document) {      // (node imports this for its tests)
  addEventListener('pointerdown', (e) => { if (open && !open.el.contains(e.target) && !open.ico.contains(e.target)) close(); }, true);
  addEventListener('scroll', () => { if (open?.ico.isConnected) place(); }, true);
  addEventListener('resize', close);
}

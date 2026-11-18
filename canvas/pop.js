// A sheet that floats beside what opened it, as a dial's does (dial.js), for what most never change: a joint's every
// property, its range typed in. It takes no room in the panel until asked for, and the panel drawn again under it
// leaves it be. `sticky`: it stays while the view and the panel are clicked (a face picked for an axis) until it is
// saved or cancelled; else a click elsewhere closes it. Escape always does.
let open = null;      // { el, key, onclose }

/** Open a sheet under `anchor` (or over it, where there is no room under): its element, to fill and listen to. */
export function pop(anchor, html, { key = '', sticky = false, onclose = null, wide = false } = {}) {
  close();
  const el = document.body.appendChild(Object.assign(document.createElement('div'), { className: `dial-pop edit-pop${wide ? ' wide' : ''}`, tabIndex: -1 }));
  el.innerHTML = html;
  open = { el, key, sticky, onclose, at: anchor.getBoundingClientRect() };
  place();
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  (el.querySelector('input:not([readonly]), select') ?? el).focus({ preventScroll: true });
  return el;
}

/** Draw the open sheet's insides again (a choice changed what it shows), where it is. */
export function refill(html) {
  if (!open) return;
  const focused = open.el.contains(document.activeElement) ? document.activeElement.dataset.edit : null;
  open.el.innerHTML = html;
  place();
  if (focused) open.el.querySelector(`[data-edit="${focused}"]`)?.focus({ preventScroll: true });
}

export const opened = (key) => (open && (key == null || open.key === key) ? open.el : null);

function place() {
  const b = open.at, el = open.el, w = el.offsetWidth, h = el.offsetHeight;
  const left = Math.max(8, Math.min(innerWidth - w - 8, b.right - w));
  // under what opened it, else over it; and on the screen whatever: what opened it may be scrolled away
  const top = Math.max(8, Math.min(innerHeight - h - 8, b.bottom + 6 + h <= innerHeight - 8 ? b.bottom + 6 : b.top - 6 - h));
  Object.assign(el.style, { left: `${left}px`, top: `${top}px` });
}

export function close() {
  if (!open) return;
  const { el, onclose } = open;
  open = null;
  el.remove();
  onclose?.();
}

if (globalThis.document) {
  addEventListener('pointerdown', (e) => {
    if (!open || open.el.contains(e.target) || e.target.closest?.('.ask, dialog')) return;
    if (!open.sticky) close();      // sticky: it waits for Save, Cancel or Escape (a face may be picked in the view)
  }, true);
  addEventListener('resize', () => { if (open) place(); });
}

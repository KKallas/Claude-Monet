// The width of the two rails, after Adam Designer (its src/designer/ui/rails.ts): one width both share, and the width
// is the mode, as in Blender's toolbar. Dragged wider than TEXT_MIN the labels show; let go narrower and the rails snap
// back to icons only. A double-click on a grip flips between icons and the last width the labels had.
export const ICON_W = 36;      // one 30 px button and its padding
export const TEXT_MIN = 110;
export const TEXT_MAX = 320;
const FIRST_W = 116;           // what Monet had before the rails could be sized: labels showing

/** Where the grip settles when let go: the labels from the threshold up, icons under it. */
export const settle = (w) => (w >= TEXT_MIN ? Math.min(w, TEXT_MAX) : ICON_W);

/** Size the rails in `rails` (the elements), keeping the width in this browser; `onChange` runs as it changes. */
export function railWidth(rails, onChange) {
  const KEY = 'monet.rail.width';
  let w = FIRST_W, live = null;
  try { const kept = Number(localStorage.getItem(KEY)); if (kept > 0) w = settle(kept); } catch { /* no storage */ }
  let lastText = w >= TEXT_MIN ? w : FIRST_W;
  const now = () => live ?? w;
  const apply = () => {
    const mode = now() >= TEXT_MIN ? 'text' : 'icon';
    for (const r of rails) {
      r.style.width = `${now()}px`;
      r.classList.toggle('text', mode === 'text'); r.classList.toggle('icon', mode === 'icon');
    }
    onChange?.();
  };
  const set = (next) => {
    live = null; w = settle(next);
    if (w >= TEXT_MIN) lastText = w;
    try { localStorage.setItem(KEY, String(w)); } catch { /* not remembered */ }
    apply();
  };
  // the grip on each rail's inner edge: the drag runs on window, so it holds even off the rail
  for (const rail of rails) {
    const left = rail.classList.contains('left');
    const grip = rail.appendChild(Object.assign(document.createElement('div'), { className: 'rail-grip',
      title: 'drag to widen the toolbars (labels appear); double-click for icons only' }));
    grip.ondblclick = () => set(now() >= TEXT_MIN ? ICON_W : lastText);
    grip.onpointerdown = (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      const x0 = e.clientX, from = now();
      document.body.classList.add('col-resizing'); grip.classList.add('dragging');
      const move = (m) => { live = Math.max(ICON_W, Math.min(TEXT_MAX, Math.round(from + (left ? m.clientX - x0 : x0 - m.clientX)))); apply(); };
      const up = () => {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up);
        document.body.classList.remove('col-resizing'); grip.classList.remove('dragging');
        set(now());
      };
      window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
    };
  }
  apply();
}

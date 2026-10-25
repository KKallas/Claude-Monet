// A side pane's inner edge, after Adam Designer (its src/designer/ui/side-edge.ts): drag it to size the pane; drag it in
// past the narrowest the pane can be, or click its ‹ › tab, and the pane closes, leaving a knob on the window's edge. A
// click on the knob, or a drag outward, opens it again; a double-click goes back to the usual width. The edge does not
// size the pane itself: it sets --side-left-w / --side-right-w and side-left-closed / side-right-closed on the container,
// and the stylesheet does the rest. Kept per side in this browser.
const MIN_W = 180, CLOSE_AT = 100, KEEP_VIEW = 240;      // the view keeps this much however wide a pane is dragged

const ICON = (side) => `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill-rule="evenodd" d="M1.5 2.5h13v11h-13zM2.5 3.5v9h11v-9z"/>
  <path d="${side === 'left' ? 'M2.5 3.5h4v9h-4z' : 'M9.5 3.5h4v9h-4z'}"/></svg>`;

export function sideEdge(container, side, label) {
  const KEY = `monet.side.${side}`;
  let kept = {};
  try { kept = JSON.parse(localStorage.getItem(KEY) || '{}') ?? {}; } catch { /* no storage */ }
  const edge = container.appendChild(Object.assign(document.createElement('div'), { className: `side-edge ${side}` }));
  edge.innerHTML = `<button class="side-tab" type="button" title="close ${label} to the edge of the window">${side === 'left' ? '‹' : '›'}</button>
    <span class="side-icon">${ICON(side)}</span>`;
  const tab = edge.querySelector('.side-tab');

  const apply = () => {
    if (kept.w) container.style.setProperty(`--side-${side}-w`, `${kept.w}px`);
    else container.style.removeProperty(`--side-${side}-w`);
    container.classList.toggle(`side-${side}-closed`, !!kept.closed);
    edge.classList.toggle('closed', !!kept.closed);
    edge.title = kept.closed ? `show ${label}: click, or drag outward to a width`
      : `drag to size ${label}; drag it in all the way to close it, double-click for its usual width`;
  };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(kept)); } catch { /* kept for this page only */ } apply(); };
  // how wide the pane is now: from the edge to the container's side
  const paneWidth = () => {
    const c = container.getBoundingClientRect(), e = edge.getBoundingClientRect();
    return Math.round(side === 'left' ? e.left - c.left : c.right - e.right);
  };

  tab.addEventListener('pointerdown', (e) => e.stopPropagation());
  tab.addEventListener('click', (e) => { e.stopPropagation(); kept.closed = true; save(); });
  edge.addEventListener('dblclick', () => { if (kept.closed) return; delete kept.w; save(); });
  edge.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const x0 = e.clientX, wasClosed = !!kept.closed, w0 = wasClosed ? 0 : paneWidth(), keptW = kept.w;
    const maxW = Math.max(MIN_W, container.getBoundingClientRect().width - KEEP_VIEW);
    let moved = false;
    edge.setPointerCapture(e.pointerId);
    edge.classList.add('dragging'); document.body.classList.add('side-resizing');
    const move = (m) => {
      const dx = m.clientX - x0;
      if (!moved && Math.abs(dx) < 3) return;
      moved = true;
      const want = side === 'left' ? w0 + dx : w0 - dx;
      // it holds at the narrowest a pane gets, and further in it closes, shown while the hand is still down;
      // closed by a drag, it opens again at the width it had before
      kept.closed = want < CLOSE_AT;
      if (kept.closed) { if (keptW) kept.w = keptW; else delete kept.w; } else kept.w = Math.round(Math.min(maxW, Math.max(MIN_W, want)));
      apply();
    };
    const up = () => {
      edge.removeEventListener('pointermove', move); edge.removeEventListener('pointerup', up); edge.removeEventListener('pointercancel', up);
      edge.classList.remove('dragging'); document.body.classList.remove('side-resizing');
      if (!moved) { if (wasClosed) { kept.closed = false; save(); } return; }      // a click on the knob opens it
      save();
    };
    edge.addEventListener('pointermove', move); edge.addEventListener('pointerup', up); edge.addEventListener('pointercancel', up);
  });
  apply();
  return edge;
}

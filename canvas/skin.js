// The skin of the page: the plain one, or 2077 (cyber.css). Loaded in the head as a plain script, so the skin is on
// before the first paint. ?skin=cyber or ?skin=plain in the address sets it; the #skin button in the header flips it;
// either way it is remembered in this browser.
(() => {
  const root = document.documentElement;
  const FONTS = 'https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Share+Tech+Mono&display=swap';
  let skin = 'plain';
  try { skin = localStorage.getItem('monet.skin') || 'plain'; } catch { /* no storage */ }
  const asked = new URLSearchParams(location.search).get('skin');
  if (asked) skin = asked;

  function set(next) {
    skin = next === 'cyber' ? 'cyber' : 'plain';
    if (skin === 'cyber') {
      root.dataset.skin = 'cyber';
      if (!document.getElementById('cyberFonts')) document.head.append(Object.assign(document.createElement('link'), { id: 'cyberFonts', rel: 'stylesheet', href: FONTS }));
    } else delete root.dataset.skin;
    try { localStorage.setItem('monet.skin', skin); } catch { /* not remembered */ }
    const button = document.getElementById('skin');
    if (button) button.textContent = skin === 'cyber' ? 'Plain' : '2077';
  }
  set(skin);
  document.addEventListener('DOMContentLoaded', () => {
    set(skin);
    document.getElementById('skin')?.addEventListener('click', () => set(skin === 'cyber' ? 'plain' : 'cyber'));
  });
})();

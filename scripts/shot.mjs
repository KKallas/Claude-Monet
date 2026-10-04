#!/usr/bin/env node
// A screenshot of a page of the running server from a headless Chrome: for checking the canvas without a
// person at the screen (after adam-designer's scripts/shot.mjs).
//   node scripts/shot.mjs http://localhost:8000/w/<id>#project/note out.png [width height] [--wait ms] [--click 'css'] [--mouse 'css x,y [shift|ctrl|meta|alt]'] [--drag 'css x1,y1 x2,y2 [shift|ctrl|meta|alt]'] [--eval 'js']…
// --click is the element's own click(); --mouse is a real press and release at (x,y) inside the element; --drag a
// real press at (x1,y1), a few moves and a release at (x2,y2): a box select. Both take modifier keys. --eval's value
// is printed. Steps run in the order given, a moment apart.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const steps = [];
for (let i = 0; i < args.length;) {
  if (/^--(click|eval|mouse|drag|wait)$/.test(args[i])) steps.push({ kind: args[i].slice(2), text: args.splice(i, 2)[1] });
  else i++;
}
const [url, out = 'shot.png', width = '1500', height = '900'] = args;
if (!url) { console.error('usage: shot.mjs <url> [out.png] [width height] [steps]'); process.exit(2); }
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), 'monet-shot-'));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `--window-size=${width},${height}`,
  '--hide-scrollbars', '--enable-unsafe-swiftshader', 'about:blank'], { stdio: 'ignore' });
const stop = () => { chrome.kill('SIGKILL'); try { rmSync(profile, { recursive: true, force: true }); } catch { /* still held */ } };
const timer = setTimeout(() => { console.error('timed out'); stop(); process.exit(1); }, 120000);

let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === 'page'); } catch { /* not up yet */ }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let id = 0;
const pending = new Map(), problems = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result ?? d.error); pending.delete(d.id); }
  if (d.method === 'Runtime.exceptionThrown') problems.push(d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text);
  if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') problems.push(d.params.args.map((a) => a.value ?? a.description).join(' '));
  if (d.method === 'Network.loadingFailed') problems.push(`load failed: ${d.params.errorText}`);
};
const send = (method, params = {}) => new Promise((r) => { pending.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result?.value;

await send('Network.enable');
await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride', { width: Number(width), height: Number(height), deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url });
await sleep(4000);
for (const step of steps) {
  if (step.kind === 'wait') { await sleep(Number(step.text)); continue; }
  if (step.kind === 'click') {
    const ok = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(step.text)}); if (!e) return false; e.click(); return true; })()`);
    if (!ok) console.error(`nothing matches ${step.text}`);
  } else if (step.kind === 'mouse' || step.kind === 'drag') {
    const [sel, ...rest] = step.text.split(/\s+/);
    const points = rest.filter((w) => /^[\d.]+,[\d.]+$/.test(w)).map((w) => w.split(',').map(Number));
    const modifiers = rest.reduce((m, k) => m | ({ alt: 1, ctrl: 2, meta: 4, shift: 8 }[k] ?? 0), 0);
    const at = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; })()`);
    if (!at) { console.error(`nothing matches ${sel}`); continue; }
    const [x1, y1] = points[0] ?? [at.w / 2, at.h / 2], [x2, y2] = points[1] ?? [x1, y1];
    const ev = (type, x, y) => send('Input.dispatchMouseEvent', { type, x: at.x + x, y: at.y + y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1, modifiers });
    await ev('mouseMoved', x1, y1);
    await ev('mousePressed', x1, y1);
    if (points[1]) for (let i = 1; i <= 4; i++) { await ev('mouseMoved', x1 + ((x2 - x1) * i) / 4, y1 + ((y2 - y1) * i) / 4); await sleep(30); }
    await ev('mouseReleased', x2, y2);
  } else console.log(`  eval → ${JSON.stringify(await evaluate(`(async () => { ${step.text} })()`))}`);
  await sleep(1200);
}
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(out, Buffer.from(shot.data, 'base64'));
console.log(`${out} · ${await evaluate('location.href')}`);
for (const p of problems) console.log(`  console: ${String(p).slice(0, 300)}`);
clearTimeout(timer);
ws.close();
stop();

#!/usr/bin/env node
/**
 * Render a full-body VRM patient animation to an RGBA PNG sequence.
 *
 *   node tools/vrm/render_rehab.mjs \
 *     --vrm assets/avatar/me.vrm --track build/wall-climb/pose-track.json \
 *     --out build/wall-climb/patient --fps 15 --w 1280 --h 720
 *
 * The track is a list of keyframes `{ t, pose }`; poses are interpolated with
 * smoothstep. Numeric leaves and `dir`/`fore` vectors interpolate; strings and
 * missing sides switch at the midpoint.
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
}
const vrmPath = path.resolve(args.vrm || 'assets/avatar/me.vrm');
const trackPath = path.resolve(args.track);
const outDir = path.resolve(args.out);
const fps = Number(args.fps || 15);
const width = Number(args.w || 1280);
const height = Number(args.h || 720);
const k = Number(args.k || 0.00448);
const floorPx = Number(args.floor || 612);
const wallPx = Number(args.wall || 596);
const seconds = args.seconds ? Number(args.seconds) : null;
const scale = Number(args.scale || 1);
const zWall = Number(args.zwall || 0.30);

const root = process.cwd();
const track = JSON.parse(fs.readFileSync(trackPath, 'utf8'));
const total = seconds ?? track[track.length - 1].t;
const frames = Math.ceil(total * fps);

function loadPlaywright() {
  for (const candidate of [
    path.join(process.cwd(), 'modules/linkZagShow/node_modules/playwright'),
    'playwright',
  ]) {
    try { return require(candidate); } catch (_) {}
  }
  throw new Error('Playwright not found');
}

const mime = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html',
  '.vrm': 'application/octet-stream', '.glb': 'model/gltf-binary', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\//, '');
  const file = path.join(root, rel);
  if (!file.startsWith(root) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;

const smooth = (t) => { t = Math.min(1, Math.max(0, t)); return t * t * (3 - 2 * t); };

function lerpValue(a, b, e) {
  if (Array.isArray(a) && Array.isArray(b)) return a.map((v, i) => v + (b[i] - v) * e);
  if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * e;
  return e < 0.5 ? a : b;
}

function lerpPose(a, b, e) {
  const out = {};
  for (const key of new Set([...Object.keys(a || {}), ...Object.keys(b || {})])) {
    const av = a ? a[key] : undefined;
    const bv = b ? b[key] : undefined;
    if (av === undefined) { if (e >= 0.5) out[key] = bv; continue; }
    if (bv === undefined) { if (e < 0.5) out[key] = av; continue; }
    if (av && bv && typeof av === 'object' && !Array.isArray(av)) {
      out[key] = lerpPose(av, bv, e);
    } else {
      out[key] = lerpValue(av, bv, e);
    }
  }
  return out;
}

function poseAt(t) {
  if (t <= track[0].t) return track[0].pose;
  for (let i = 1; i < track.length; i++) {
    if (t <= track[i].t) {
      const a = track[i - 1], b = track[i];
      const span = Math.max(1e-6, b.t - a.t);
      return lerpPose(a.pose, b.pose, smooth((t - a.t) / span));
    }
  }
  return track[track.length - 1].pose;
}

fs.mkdirSync(outDir, { recursive: true });

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ args: ['--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: Math.round(width * scale), height: Math.round(height * scale) } });
page.on('pageerror', (e) => console.error('pageerror', e.message));
const relModel = '/' + path.relative(root, vrmPath).split(path.sep).join('/');
const q = new URLSearchParams({
  model: `http://127.0.0.1:${port}${relModel}`,
  w: String(Math.round(width * scale)),
  h: String(Math.round(height * scale)),
  k: String(k / scale),
  floor: String(floorPx * scale),
  wall: String(wallPx * scale),
  zwall: String(zWall),
});
await page.goto(`http://127.0.0.1:${port}/tools/vrm/rehab.html?${q}`);
await page.waitForFunction(() => window.__ready === true || window.__error, null, { timeout: 60000 });
const err = await page.evaluate(() => window.__error || '');
if (err) throw new Error(err);
if (args.info === '1') console.error(JSON.stringify(await page.evaluate(() => window.__info)));
console.error(`patient: ${frames} frames at ${fps} fps, ${width}x${height} -> ${outDir}`);

let seed = 20261108;
const rand = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
let nextBlink = 2.2 + rand() * 2.5;
let blinkStart = -1;

for (let i = 0; i < frames; i++) {
  const t = i / fps;
  const pose = poseAt(t);
  // breathing: slow, small, always on so the figure is never frozen
  const breath = Math.sin(t * 2 * Math.PI / 5.2) * 0.5 + 0.5;
  pose.lean = (pose.lean || 0) + (breath - 0.5) * 0.035;
  pose.crouch = (pose.crouch || 0) + (breath - 0.5) * 0.0025;
  // blink: 3-5 s apart, ~0.18 s closure, occasional double blink
  if (t >= nextBlink && blinkStart < 0) { blinkStart = t; }
  let blink = 0;
  if (blinkStart >= 0) {
    const p = (t - blinkStart) / 0.18;
    if (p >= 1) {
      blinkStart = -1;
      nextBlink = t + 3.0 + rand() * 2.0;
    } else blink = Math.sin(Math.PI * p);
  }
  pose.blink = blink;
  await page.evaluate((p) => window.__applyPose(p), pose);
  const file = path.join(outDir, `p-${String(i).padStart(5, '0')}.png`);
  await page.locator('canvas').screenshot({ path: file, omitBackground: true });
  if (i % 100 === 0) console.error(`  ${i}/${frames}`);
}

await browser.close();
server.close();
console.error('patient: done');

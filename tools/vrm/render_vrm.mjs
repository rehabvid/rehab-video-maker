#!/usr/bin/env node
/**
 * Render a talking VRM host to an alpha MOV (PNG frames).
 *
 * Usage:
 *   node render_vrm.mjs --vrm model.vrm --audio master.wav --out avatar.mov \
 *     --height 384 --fps 8
 *
 * Requires three + @pixiv/three-vrm in modules/linkZagShow/node_modules.
 * Mouth is driven by the narration envelope (aa expression); blink is periodic.
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
}
const vrm = path.resolve(args.vrm || 'assets/avatar/me.vrm');
const audio = path.resolve(args.audio);
const out = path.resolve(args.out);
const height = Number(args.height || 384);
const fps = Number(args.fps || 15);
const visemeFile = args.visemes ? path.resolve(args.visemes) : null;
const debug = args.debug === '1';

function loadPlaywright() {
  for (const candidate of [
    path.join(process.cwd(), 'modules/linkZagShow/node_modules/playwright'),
    'playwright',
  ]) {
    try { return require(candidate); } catch (_) {}
  }
  throw new Error('Playwright not found');
}

function readWavEnvelope(file, fps) {
  return new Promise((resolve) => {
    const chunks = [];
    const ff = spawn('ffmpeg', ['-v', 'error', '-i', file, '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']);
    ff.stdout.on('data', (c) => chunks.push(c));
    ff.on('close', () => {
      const buf = Buffer.concat(chunks);
      const samples = new Float32Array(buf.buffer, buf.byteOffset, Math.floor(buf.length / 4));
      const window = Math.max(1, Math.floor(16000 / fps));
      const frames = Math.floor(samples.length / window);
      const env = new Float32Array(frames);
      for (let i = 0; i < frames; i++) {
        let sum = 0;
        for (let j = 0; j < window; j++) sum += samples[i * window + j] ** 2;
        env[i] = Math.sqrt(sum / window);
      }
      let sorted = Array.from(env).sort((a, b) => a - b);
      const peak = sorted[Math.floor(sorted.length * 0.95)] || 1;
      for (let i = 0; i < env.length; i++) env[i] = Math.min(1, env[i] / peak);
      resolve(env);
    });
  });
}

(async () => {
  const { chromium } = loadPlaywright();
  const root = process.cwd();
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
  const env = await readWavEnvelope(audio, fps);
  const visemeTrack = visemeFile ? JSON.parse(fs.readFileSync(visemeFile, 'utf8')) : null;
  // Natural blink: 3-5s apart, 0.18s closure, ~12% double blinks. The eyelid
  // weight follows a half-cosine so it closes and reopens instead of popping.
  let seed = 20261105;
  const rand = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  const blinkTrack = new Float32Array(env.length);
  const frames = env.length;
  const blinkFrames = (startAt, count) => {
    for (let k = 0; k < count && startAt + k < frames; k++) {
      const p = count <= 1 ? 1 : k / (count - 1);
      blinkTrack[startAt + k] = Math.max(blinkTrack[startAt + k], Math.sin(Math.PI * p));
    }
  };
  let t = 1.8 + rand() * 2.0;
  while (t * fps < frames) {
    const start = Math.floor(t * fps);
    const hold = Math.max(2, Math.round(0.18 * fps));
    blinkFrames(start, hold);
    if (rand() < 0.12) blinkFrames(start + hold + Math.round(0.12 * fps), hold);
    t += 3.0 + rand() * 2.0;
  }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vrm-'));
  const browser = await chromium.launch({ args: ['--use-gl=angle'] });
  const page = await browser.newPage({ viewport: { width: height, height: height } });
  page.on('pageerror', (e) => console.error('pageerror', e.message));
  const relModel = '/' + path.relative(root, vrm).split(path.sep).join('/');
  const url = `http://127.0.0.1:${port}/tools/vrm/avatar.html?model=${encodeURIComponent(`http://127.0.0.1:${port}${relModel}`)}&size=${height}`;
  await page.goto(url);
  await page.waitForFunction(() => window.__ready === true || window.__error, null, { timeout: 60000 });
  const err = await page.evaluate(() => window.__error || '');
  if (err) throw new Error(err);
  const meta = await page.evaluate(() => ({
    hasFace: window.__hasFace, expressions: window.__expressions,
  }));
  console.error(`vrm expressions: ${(meta.expressions || []).join(', ') || '(none)'}`);
  if (debug) console.error(`probe: ${JSON.stringify(await page.evaluate(() => window.__probe?.()))}`);
  const canvas = page.locator('canvas');
  for (let i = 0; i < env.length; i++) {
    const blink = blinkTrack[i] || 0;
    const yaw = Math.sin(i / fps * 0.7) * 0.18;
    // With a syllable track, silence gaps are explicit nulls. Without one,
    // fall back to a coarse envelope-driven "aa" so the host still talks.
    const viseme = visemeTrack
      ? (visemeTrack.frames[i] || null)
      : (env[i] > 0.12 ? 'aa' : null);
    await page.evaluate(({ viseme, mouth, blink, yaw, t, dt }) =>
      window.renderFrame({ viseme, mouth, blink, yaw, t, dt }),
      { viseme, mouth: env[i], blink, yaw, t: i / fps, dt: 1 / fps });
    await canvas.screenshot({ path: path.join(tmp, `f-${String(i).padStart(5, '0')}.png`), omitBackground: true });
    if (debug && i % 5 === 0) {
      const w = await page.evaluate(() => {
        const r = {};
        for (const [k, v] of Object.entries(window.__weights || {})) r[k] = Math.round(v * 100) / 100;
        try { r.blink = Math.round((window.__vrm?.expressionManager?.getValue('blink') || 0) * 100) / 100; } catch (_) {}
        return r;
      });
      console.error(`frame ${i} viseme=${viseme} blink=${blink.toFixed(2)} weights=${JSON.stringify(w)}`);
    }
  }
  await browser.close();
  server.close();
  fs.mkdirSync(path.dirname(out), { recursive: true });
  await new Promise((resolve, reject) => {
    const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-framerate', String(fps), '-i', path.join(tmp, 'f-%05d.png'), '-c:v', 'png', '-pix_fmt', 'rgba', '-an', out], { stdio: 'inherit' });
    ff.on('close', (code) => (code ? reject(new Error('ffmpeg failed')) : resolve()));
  });
  console.log(out);
})();

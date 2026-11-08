#!/usr/bin/env node
/**
 * Bake the glasses fit into a VRM asset.
 *
 * `tools/vrm/glasses.js` corrects a badly parented frame at load time. This
 * script runs the same fit in a headless browser, then writes the resulting
 * local transform straight into the glTF nodes and marks them with
 * `extras.linkzagGlassesFit`, so the asset is correct on its own and the
 * runtime helper becomes a no-op.
 *
 * Usage:
 *   node tools/vrm/bake_glasses.mjs --vrm assets/avatar/me.vrm            # in place
 *   node tools/vrm/bake_glasses.mjs --vrm me.vrm --out me-baked.vrm       # copy
 *   node tools/vrm/bake_glasses.mjs --vrm me.vrm --dry-run                # report only
 *
 * Requires three + @pixiv/three-vrm in modules/linkZagShow/node_modules and
 * Playwright (bundled there too).
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i];
  if (!key.startsWith('--')) continue;
  const next = process.argv[i + 1];
  if (next && !next.startsWith('--')) { args[key.replace(/^--/, '')] = next; i++; }
  else args[key.replace(/^--/, '')] = '1';
}

const vrmPath = path.resolve(args.vrm || 'assets/avatar/me.vrm');
const outPath = path.resolve(args.out || vrmPath);
const dryRun = args['dry-run'] === '1';
const root = process.cwd();

if (!fs.existsSync(vrmPath)) throw new Error(`VRM not found: ${vrmPath}`);

const mime = {
  '.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html',
  '.vrm': 'application/octet-stream', '.glb': 'model/gltf-binary',
  '.json': 'application/json', '.bin': 'application/octet-stream',
};

const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\//, '');
  const file = path.join(root, rel);
  if (!file.startsWith(root) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {
    'Content-Type': mime[path.extname(file)] || 'application/octet-stream',
    'Cache-Control': 'no-store',
  });
  fs.createReadStream(file).pipe(res);
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

function loadPlaywright() {
  for (const candidate of [
    path.join(root, 'modules/linkZagShow/node_modules/playwright'),
    'playwright',
  ]) {
    try { return require(candidate); } catch (_) {}
  }
  throw new Error('Playwright not found');
}

async function probe(browser, file, { utils = true } = {}) {
  const page = await browser.newPage({ viewport: { width: 512, height: 512 } });
  page.on('pageerror', (e) => console.error('pageerror', e.message));
  const rel = '/' + path.relative(root, file).split(path.sep).join('/');
  const url = `${origin}/tools/vrm/glasses_bake.html?model=${encodeURIComponent(rel)}`
    + `&utils=${utils ? '1' : '0'}&t=${Date.now()}`;
  await page.goto(url);
  await page.waitForFunction(() => window.__ready === true || window.__error, null, { timeout: 120000 });
  const err = await page.evaluate(() => window.__error || '');
  if (err) throw new Error(err);
  const before = await page.evaluate(() => window.__measure());
  const fitted = await page.evaluate(() => window.__fit());
  await page.close();
  return { before, fitted };
}

// --- GLB read / write ------------------------------------------------------

const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;

function readGlb(buf) {
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error('Not a GLB file');
  const total = buf.readUInt32LE(8);
  const chunks = [];
  let off = 12;
  while (off < total) {
    const length = buf.readUInt32LE(off);
    const type = buf.readUInt32LE(off + 4);
    chunks.push({ type, data: buf.subarray(off + 8, off + 8 + length) });
    off += 8 + length;
  }
  return chunks;
}

function writeGlb(chunks) {
  const parts = [];
  for (const chunk of chunks) {
    let data = chunk.data;
    if (chunk.type === JSON_CHUNK) {
      const text = data.toString('utf8').replace(/\s+$/, '');
      const pad = (4 - (Buffer.byteLength(text) % 4)) % 4;
      data = Buffer.from(text + ' '.repeat(pad), 'utf8');
    } else {
      const pad = (4 - (data.length % 4)) % 4;
      if (pad) data = Buffer.concat([data, Buffer.alloc(pad)]);
    }
    const header = Buffer.alloc(8);
    header.writeUInt32LE(data.length, 0);
    header.writeUInt32LE(chunk.type, 4);
    parts.push(header, data);
  }
  const body = Buffer.concat(parts);
  const out = Buffer.alloc(12 + body.length);
  out.writeUInt32LE(0x46546c67, 0);
  out.writeUInt32LE(2, 4);
  out.writeUInt32LE(out.length, 8);
  body.copy(out, 12);
  return out;
}

function applyFit(buffer, nodes) {
  const chunks = readGlb(buffer);
  const jsonChunk = chunks.find((c) => c.type === JSON_CHUNK);
  if (!jsonChunk) throw new Error('GLB has no JSON chunk');
  const gltf = JSON.parse(jsonChunk.data.toString('utf8'));

  for (const node of nodes) {
    if (node.nodeIndex == null) throw new Error(`No glTF node index for ${node.name}`);
    const def = gltf.nodes[node.nodeIndex];
    if (!def) throw new Error(`glTF node ${node.nodeIndex} missing`);
    if (def.matrix) {
      throw new Error(`${node.name} uses a matrix; decompose it before baking`);
    }
    def.translation = node.position.map(round);
    def.scale = node.scale.map(round);
    def.extras = { ...(def.extras || {}), linkzagGlassesFit: true };
  }

  jsonChunk.data = Buffer.from(JSON.stringify(gltf), 'utf8');
  return writeGlb(chunks);
}

function round(v) {
  // ~1e-6 m = 1 micron, plenty for a 1.7 m figure
  return Math.round(v * 1e6) / 1e6;
}

// --- run -------------------------------------------------------------------

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ args: ['--use-gl=angle'] });

try {
  const original = fs.readFileSync(vrmPath);
  const { before, fitted } = await probe(browser, vrmPath);

  console.log(`model      ${path.relative(root, vrmPath)}`);
  console.log(`glasses    ${fitted.nodes.map((n) => `${n.name}#${n.nodeIndex}`).join(', ')}`);
  console.log(`before     dy=${before.dyMm.toFixed(1)}mm dz=${before.dzMm.toFixed(1)}mm`);
  console.log(`after      dy=${fitted.after.dyMm.toFixed(2)}mm dz=${fitted.after.dzMm.toFixed(2)}mm`);

  if (fitted.result?.baked) {
    console.log('already    asset carries the fit marker; nothing to do');
    process.exit(0);
  }

  const patched = applyFit(original, fitted.nodes);
  if (dryRun) {
    console.log(`dry-run    would write ${patched.length} bytes to ${path.relative(root, outPath)}`);
    process.exit(0);
  }

  fs.writeFileSync(outPath, patched);
  console.log(`wrote      ${path.relative(root, outPath)} (${patched.length} bytes, was ${original.length})`);

  // Reload the patched asset: the frame must land where the in-memory fit put
  // it, the fit marker must make the runtime helper a no-op, and the result
  // must not depend on the VRMUtils pass (a consumer may load the glTF raw).
  const want = fitted.after.box.glasses;
  for (const utils of [true, false]) {
    const check = await probe(browser, outPath, { utils });
    const got = check.before.box.glasses;
    const delta = Math.max(
      ...want[0].map((v, i) => Math.abs(v - got[0][i])),
      ...want[1].map((v, i) => Math.abs(v - got[1][i])),
    );
    const label = utils ? 'utils' : 'raw';
    console.log(`verify ${label.padEnd(6)} box delta ${(delta * 1000).toFixed(3)}mm, `
      + `residual dy=${check.before.dyMm.toFixed(2)}mm dz=${check.before.dzMm.toFixed(2)}mm, `
      + `rerun=${check.fitted.result?.baked ? 'no-op' : 'APPLIED AGAIN'}`);

    if (delta > 0.0002) throw new Error(`Baked transform differs from the live fit by ${delta * 1000}mm (${label})`);
    if (!check.fitted.result?.baked) throw new Error('Fit marker missing: the runtime would apply the offset twice');
  }
} finally {
  await browser.close();
  server.close();
}

#!/usr/bin/env node
/**
 * Probe a VRM's normalized humanoid rig: rest-pose directions and world
 * positions. Used to calibrate the full-body rehab renderer.
 *
 *   node tools/vrm/probe.mjs --vrm assets/avatar/me.vrm
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
const root = process.cwd();

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

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ args: ['--use-gl=angle'] });
const page = await browser.newPage({ viewport: { width: 512, height: 512 } });
page.on('pageerror', (e) => console.error('pageerror', e.message));
const relModel = '/' + path.relative(root, vrmPath).split(path.sep).join('/');
await page.goto(`http://127.0.0.1:${port}/tools/vrm/avatar.html?model=${encodeURIComponent(`http://127.0.0.1:${port}${relModel}`)}&size=512`);
await page.waitForFunction(() => window.__ready === true || window.__error, null, { timeout: 60000 });
const err = await page.evaluate(() => window.__error || '');
if (err) throw new Error(err);

const out = await page.evaluate(async () => {
  const THREE = await import('three');
  const vrm = window.__vrm;
  vrm.scene.updateMatrixWorld(true);
  const names = ['hips', 'spine', 'chest', 'neck', 'head', 'rightShoulder', 'rightUpperArm',
    'rightLowerArm', 'rightHand', 'leftUpperArm', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
    'leftUpperLeg'];
  const info = {};
  const v = new THREE.Vector3();
  for (const n of names) {
    const raw = vrm.humanoid.getRawBoneNode(n);
    const norm = vrm.humanoid.getNormalizedBoneNode(n);
    if (!raw) continue;
    const wp = raw.getWorldPosition(new THREE.Vector3());
    const nwp = norm ? norm.getWorldPosition(new THREE.Vector3()) : null;
    // direction to the first humanoid child, in the bone's local space
    let childDir = null, childName = null;
    const map = { rightShoulder: 'rightUpperArm', rightUpperArm: 'rightLowerArm',
      rightLowerArm: 'rightHand', rightUpperLeg: 'rightLowerLeg',
      rightLowerLeg: 'rightFoot', hips: 'spine', spine: 'chest', chest: 'neck', neck: 'head' };
    const cn = map[n];
    if (cn) {
      const cb = vrm.humanoid.getRawBoneNode(cn);
      if (cb) {
        const cw = cb.getWorldPosition(new THREE.Vector3());
        const lw = raw.worldToLocal(cw.clone());
        childDir = [lw.x, lw.y, lw.z];
        childName = cn;
      }
    }
    info[n] = {
      world: [wp.x, wp.y, wp.z],
      normWorld: nwp ? [nwp.x, nwp.y, nwp.z] : null,
      child: childName,
      childDirLocal: childDir,
      localQuat: [raw.quaternion.x, raw.quaternion.y, raw.quaternion.z, raw.quaternion.w],
    };
  }
  const box = new THREE.Box3().setFromObject(vrm.scene);
  return { info, bbox: { min: box.min.toArray(), max: box.max.toArray() }, height: box.getSize(new THREE.Vector3()).y };
});

console.log(JSON.stringify(out, null, 2));
await browser.close();
server.close();

#!/usr/bin/env node
/**
 * Upload one or more vertical videos to WeChat Channels (视频号).
 *
 * This is browser automation of the Channels creator UI, adapted from
 * wangzhaobo168/wechat-channels-upload (MIT). It is not an official API.
 * The owner must scan the WeChat login QR once; the browser profile persists
 * outside the repository. No password or QR session is stored by this repo.
 *
 * Defaults are intentionally conservative:
 *   - headed browser
 *   - one video per run
 *   - do NOT declare "original" unless --original is passed
 *   - do NOT publish unless --publish is passed
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '../../..');
const PACKAGE_CANDIDATES = [
  path.join(ROOT, 'modules/linkZagShow/node_modules/playwright'),
  'playwright',
];
function loadPlaywright() {
  for (const candidate of PACKAGE_CANDIDATES) {
    try { return require(candidate); } catch (_) {}
  }
  throw new Error('Playwright not found. Install it or use the LinkZag node_modules copy.');
}
const { chromium } = loadPlaywright();

const DEFAULT_PROFILE = path.join(
  os.homedir(), '.config', 'podcast-youtuber-agent', 'wechat-channels-profile'
);
const PAGE_URL = 'https://channels.weixin.qq.com/platform/post/create';
const SS_DIR = path.join(ROOT, 'build', 'marketing', 'wechat', 'linkZag', 'screenshots');

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) { out._.push(a); continue; }
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) { out[key] = next; i++; }
    else out[key] = true;
  }
  return out;
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function readManifest(args) {
  if (args.manifest) {
    const data = JSON.parse(fs.readFileSync(args.manifest, 'utf8'));
    return (data.items || []).map((item) => ({
      ...item,
      account: data.account || item.account,
      video: path.isAbsolute(item.video) ? item.video : path.join(ROOT, item.video),
      cover: item.cover && !path.isAbsolute(item.cover) ? path.join(ROOT, item.cover) : item.cover,
    }));
  }
  if (!args.video) throw new Error('pass --manifest or --video');
  return [{
    video: args.video,
    cover: args.cover || '',
    title: args.title || '',
    description: args.description || '',
  }];
}

function validate(item) {
  if (!item.video || !fs.existsSync(item.video)) throw new Error(`video not found: ${item.video}`);
  if (item.cover && !fs.existsSync(item.cover)) throw new Error(`cover not found: ${item.cover}`);
  if (!item.title || item.title.length < 6) throw new Error('short title must be at least 6 characters');
  if (/[，。！？、；：,.!?;:#@]/.test(item.title)) {
    throw new Error('short title must not contain punctuation, emoji or hashtags');
  }
}

function printTuiQr(qrPath) {
  if (process.env.WECHAT_TUI_QR === '0') return;
  const venv = path.join(ROOT, '.venv', 'bin', 'python');
  const python = fs.existsSync(venv) ? venv : 'python3';
  const result = spawnSync(python, [path.join(__dirname, 'tui_qr.py'), qrPath], {
    encoding: 'utf8',
  });
  if (result.status === 0 && String(result.stdout || '').trim()) {
    console.log('\nTUI QR — scan this block:');
    process.stdout.write(String(result.stdout).endsWith('\n')
      ? result.stdout
      : `${result.stdout}\n`);
    console.log('If the block is too wide, open the PNG path above instead.\n');
  } else {
    console.log(`TUI QR render failed: ${String(result.stderr || '').slice(0, 200)}`);
  }
}

async function waitForUpload(page) {
  await page.locator('input[type="file"][accept*="video"]').first().setInputFiles(this.video);
  await page.waitForSelector('input[placeholder*="短标题"]', { timeout: 300000 });
  await sleep(5000);
}

async function uploadCover(page, cover) {
  if (!cover) return;
  for (let i = 0; i < 30; i++) {
    const generating = await page.$$eval('[class*="cover"]', (els) =>
      els.some((el) => (el.innerText || '').includes('生成中')));
    if (!generating) break;
    await sleep(2000);
  }
  await sleep(1500);
  const triggers = [
    '[class*="cover-edit"]', '[class*="cover-trigger"]',
    '[class*="cover-wrap"]:not([class*="video-cover"])', '[class*="cover-area"]',
    'text=编辑封面', 'text=更换封面', 'text=上传封面',
    '[class*="cover"] [class*="edit"]', '[class*="cover"] [class*="change"]',
    '[class*="cover"] [class*="upload"]',
  ];
  let opened = false;
  for (const selector of triggers) {
    try {
      const el = page.locator(selector).first();
      if (!(await el.isVisible({ timeout: 1000 }).catch(() => false))) continue;
      await el.click(); await sleep(1800);
      const dialog = page.locator('.weui-desktop-dialog__wrp:not([style*="display: none"])').first();
      if (await dialog.isVisible({ timeout: 1800 }).catch(() => false)) { opened = true; break; }
    } catch (_) {}
  }
  if (!opened) {
    const thumbs = ['[class*="video-cover-container"]', '[class*="video-cover"]',
      '[class*="poster-container"]', 'img[class*="cover"]', 'img[class*="poster"]'];
    for (const selector of thumbs) {
      try {
        const el = page.locator(selector).first();
        if (!(await el.isVisible({ timeout: 1000 }).catch(() => false))) continue;
        await el.click(); await sleep(1800);
        if (await page.locator('.weui-desktop-dialog__wrp:not([style*="display: none"])').first()
          .isVisible({ timeout: 1500 }).catch(() => false)) { opened = true; break; }
      } catch (_) {}
    }
  }
  if (!opened) {
    console.log('warning: cover dialog did not open; using the video first frame');
    return;
  }
  let uploaded = false;
  try {
    await page.locator('.single-cover-uploader-wrap input[type="file"]').first().setInputFiles(cover);
    uploaded = true;
  } catch (_) {}
  if (!uploaded) {
    const inputs = page.locator('.weui-desktop-dialog__wrp:not([style*="display: none"]) input[type="file"][accept*="image"]');
    for (let i = 0; i < await inputs.count(); i++) {
      try { await inputs.nth(i).setInputFiles(cover); uploaded = true; break; } catch (_) {}
    }
  }
  if (!uploaded) {
    try {
      const trigger = page.locator('.cover-slider-wrap:has-text("上传封面")').first();
      if (await trigger.isVisible({ timeout: 2000 }).catch(() => false)) {
        const [chooser] = await Promise.all([page.waitForEvent('filechooser', { timeout: 5000 }), trigger.click()]);
        await chooser.setFiles(cover); uploaded = true;
      }
    } catch (_) {}
  }
  if (!uploaded) { console.log('warning: cover upload failed; using the first frame'); return; }
  try { await page.waitForSelector('.single-cover-uploader-wrap .finish-wrap img', { timeout: 15000 }); } catch (_) {}
  await sleep(1500);
  await page.locator('.cover-set-footer button.weui-desktop-btn_primary').first().click();
  await sleep(2500);
}

async function runItem(page, item, args, index) {
  validate(item);
  console.log(`\n[item ${index}] ${item.title}`);
  await page.goto(PAGE_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await sleep(2500);
  const waitForLogin = async () => {
    // The redirect to login.html can land after the first check; re-check.
    await sleep(1500);
    if (!page.url().includes('login')) return;
    const waitMs = Number(process.env.WECHAT_LOGIN_TIMEOUT_MS || 900000);
    console.log(`LOGIN REQUIRED: scan the QR in the opened browser; waiting up to ${Math.round(waitMs / 60000)} minutes...`);
    fs.mkdirSync(SS_DIR, { recursive: true });
    await page.screenshot({ path: path.join(SS_DIR, 'login.png'), fullPage: true }).catch(() => {});
    console.log(`login url: ${page.url()}`);
    let loginText = await page.locator('body').innerText().catch(() => '');
    console.log(`login page text: ${String(loginText).replace(/\s+/g, ' ').slice(0, 800)}`);
    // The embedded QR panel sometimes reports "加载失败，点击重试" on first load.
    for (let attempt = 0; attempt < 3; attempt++) {
      const failed = await page.getByText('加载失败', { exact: false }).first()
        .isVisible({ timeout: 1200 }).catch(() => false);
      if (!failed) break;
      console.log(`login QR failed to load; retrying (${attempt + 1}/3)`);
      const retry = page.getByText('点击重试', { exact: false }).first();
      if (await retry.isVisible({ timeout: 1200 }).catch(() => false)) {
        await retry.click().catch(() => {});
      } else {
        await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
      }
      await sleep(3000);
    }
    await page.screenshot({ path: path.join(SS_DIR, 'login-after-retry.png'), fullPage: true }).catch(() => {});
    loginText = await page.locator('body').innerText().catch(() => '');
    console.log(`login page after retry: ${String(loginText).replace(/\s+/g, ' ').slice(0, 500)}`);
    // The QR panel's JS can fail while the iframe HTML still contains the
    // session UUID. Pull the QR image out and save it for scanning.
    await sleep(2500);
    const qrFrame = page.frames().find((f) => f.url().includes('qrconnect'));
    console.log(`qr frames: ${page.frames().map((f) => f.url()).filter(Boolean).length}`);
    if (qrFrame) {
      const html = await qrFrame.content().catch(() => '');
      console.log(`qr frame html: ${html.length}`);
      const match = html.match(/connect\/qrcode\/([A-Za-z0-9]+)/);
      console.log(`qr uuid: ${match ? match[1] : 'none'}`);
      if (match) {
        const qrUrl = `https://open.weixin.qq.com/connect/qrcode/${match[1]}`;
        try {
          const response = await page.context().request.get(qrUrl);
          if (response.ok()) {
            const qrPath = path.join(SS_DIR, 'login-qr.png');
            fs.writeFileSync(qrPath, await response.body());
            console.log(`QR IMAGE: ${qrPath}`);
            printTuiQr(qrPath);
          } else {
            console.log(`QR image fetch failed: HTTP ${response.status()}`);
          }
        } catch (error) {
          console.log(`QR image fetch error: ${error.message}`);
        }
      }
    }
    await page.waitForURL('**/post/create**', { timeout: waitMs });
    await sleep(2000);
  };
  await waitForLogin();
  console.log('uploading video...');
  await waitForLogin();
  await page.locator('input[type="file"][accept*="video"]').first().setInputFiles(item.video);
  await page.waitForSelector('input[placeholder*="短标题"]', { timeout: 300000 });
  await sleep(5000);

  const title = page.locator('input[placeholder*="短标题"]').first();
  await title.click(); await title.fill(''); await title.type(item.title, { delay: 45 });

  const descSelectors = ['[data-placeholder*="描述"]', '[data-placeholder*="添加描述"]', 'text=添加描述'];
  for (const selector of descSelectors) {
    try {
      const el = page.locator(selector).first();
      if (await el.isVisible({ timeout: 1200 }).catch(() => false)) { await el.click(); await sleep(800); break; }
    } catch (_) {}
  }
  const editor = page.locator('div.input-editor, [data-placeholder*="描述"]').first();
  if (await editor.isVisible({ timeout: 2000 }).catch(() => false)) {
    await editor.click(); await sleep(250);
    await page.keyboard.type((item.description || '').replace(/\n+/g, ' ').trim(), { delay: 15 });
  }
  await sleep(1000);

  await uploadCover(page, item.cover || '');

  if (args.original) {
    console.log('declaring original (explicitly requested)');
    try {
      const cb = page.locator('.declare-original-checkbox .ant-checkbox-input, .declare-original-checkbox input[type="checkbox"]').first();
      await cb.click(); await sleep(1500);
      const proto = page.locator('.original-proto-wrapper .ant-checkbox-input, .original-proto-wrapper input[type="checkbox"]').first();
      if (await proto.isVisible({ timeout: 2500 }).catch(() => false)) {
        await proto.click(); await sleep(800);
        await page.locator('button:has-text("声明原创")').first().click(); await sleep(1500);
      }
    } catch (error) { console.log('original declaration skipped:', error.message); }
  }

  fs.mkdirSync(SS_DIR, { recursive: true });
  const slug = `${index}-${(item.title || path.basename(item.video)).replace(/[^a-zA-Z0-9._-]+/g, '-')}`.slice(0, 90);
  await page.screenshot({ path: path.join(SS_DIR, `${slug}-ready.png`), fullPage: true });
  if (!args.publish) {
    console.log('DRAFT READY: --publish not set; left on the publish page.');
    return { status: 'draft', screenshot: path.join(SS_DIR, `${slug}-ready.png`) };
  }

  const publish = page.locator('button:has-text("发表"):not([disabled])').first();
  if (!(await publish.isVisible({ timeout: 3000 }).catch(() => false))) {
    throw new Error('publish button is not available');
  }
  await publish.click(); await sleep(3000);
  try {
    if (await page.locator('text=广告分成').first().isVisible({ timeout: 2500 }).catch(() => false)) {
      console.log('ad-revenue dialog detected; leaving its default (no original claim)');
    }
  } catch (_) {}
  await sleep(5000);
  await page.screenshot({ path: path.join(SS_DIR, `${slug}-published.png`), fullPage: true });
  return { status: 'published', screenshot: path.join(SS_DIR, `${slug}-published.png`) };
}

(async () => {
  const args = parseArgs(process.argv);
  const items = readManifest(args).slice(0, Math.max(1, Number(args.limit || 1)));
  if (items.length === 0) throw new Error('manifest has no items');
  if (args.check) {
    items.forEach((item, index) => {
      validate(item);
      console.log(`ok ${index + 1}: ${item.title} (${path.basename(item.video)})`);
    });
    return;
  }
  if (!args.publish && !args.draft) console.log('dry mode: publishing requires --publish');
  const profile = args.profile || DEFAULT_PROFILE;
  fs.mkdirSync(profile, { recursive: true });
  const context = await chromium.launchPersistentContext(profile, {
    headless: false,
    viewport: { width: 1280, height: 860 },
    slowMo: 120,
    args: ['--start-maximized'],
  });
  const pages = context.pages();
  const page = pages.length ? pages[0] : await context.newPage();
  process.on('SIGINT', async () => { try { await context.close(); } finally { process.exit(130); } });
  const results = [];
  for (let i = 0; i < items.length; i++) {
    try {
      results.push({ title: items[i].title, ...(await runItem(page, items[i], args, i + 1)) });
    } catch (error) {
      console.error(`item ${i + 1} failed:`, error.message);
      results.push({ title: items[i].title, status: 'failed', error: error.message });
      break;
    }
  }
  const receipt = args.receipt || path.join(ROOT, 'build', 'marketing', 'wechat', 'linkZag', 'upload-receipt.json');
  fs.mkdirSync(path.dirname(receipt), { recursive: true });
  fs.writeFileSync(receipt, JSON.stringify({ account: 'linkZag', at: new Date().toISOString(), results }, null, 2) + '\n');
  console.log(`receipt: ${receipt}`);
  await context.close();
})().catch((error) => { console.error('fatal:', error.stack || error.message); process.exit(1); });

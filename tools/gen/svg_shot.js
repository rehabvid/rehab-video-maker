const fs = require('fs');
const path = require('path');

const [, , svgPath, outPath, sizeArg] = process.argv;
const size = Number(sizeArg || 512);

function loadPlaywright() {
  const candidates = [
    path.join(process.cwd(), 'modules/linkZagShow/node_modules/playwright'),
    'playwright',
  ];
  for (const candidate of candidates) {
    try { return require(candidate); } catch (_) {}
  }
  throw new Error('Playwright not found');
}

(async () => {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  await page.goto('file://' + path.resolve(svgPath));
  await page.waitForTimeout(500);
  await page.screenshot({ path: outPath, omitBackground: true });
  await browser.close();
})();

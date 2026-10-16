// render_frames.js ― Playwright でスライド HTML のアニメーションを 1 コマずつ確定的に PNG にする
// 使い方: node render_frames.js jobs.json
// jobs.json: {"width":1920,"height":1080,"jobs":[{"html":"...html","out":"prefix","frames":36,"fps":30}]}
//   frames=1 のときは最終状態を 1 枚だけ撮る
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const opts = {};
  if (process.env.PW_CHANNEL) opts.channel = process.env.PW_CHANNEL;   // 例: chrome（Chrome を使う）
  const browser = await chromium.launch(opts);
  const page = await browser.newPage({ viewport: { width: spec.width, height: spec.height }, deviceScaleFactor: 1 });
  let done = 0;
  for (const job of spec.jobs) {
    const url = 'file://' + path.resolve(job.html);
    await page.goto(url, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const fps = job.fps || 30;
    const n = Math.max(1, job.frames | 0);
    for (let i = 0; i < n; i++) {
      const ms = n === 1 ? 1e7 : Math.round(i * 1000 / fps);
      await page.evaluate((t) => window.__seek(t), ms);
      const out = n === 1 ? `${job.out}.png` : `${job.out}_${String(i).padStart(4, '0')}.png`;
      if (!fs.existsSync(out)) await page.screenshot({ path: out, type: 'png' });
    }
    done++;
    if (done % 10 === 0) process.stderr.write(`  ${done}/${spec.jobs.length}\n`);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });

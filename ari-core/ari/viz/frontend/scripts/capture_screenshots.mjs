// Dashboard screenshot capture for the documentation set.
//
// Drives a real headless Chromium over a running `ari.viz.server` and writes
// one PNG per (locale, route) into docs/assets/images/<locale>/. The docs
// embed these, so a stale capture silently misdocuments the product — the
// sidebar alone changed from 10 to 15 entries when the v2 workspaces landed.
//
// The locale is set through localStorage `ari_lang` BEFORE the first paint
// (addInitScript), because the i18n provider reads it during bootstrap and
// only then resolves the lazily-loaded dictionary chunk.
//
// Usage (from ari-core/ari/viz/frontend):
//   node scripts/capture_screenshots.mjs \
//     --base-url http://127.0.0.1:8765 \
//     --out ../../../../docs/assets/images \
//     --run-id <checkpoint dir name> [--rqgm-run-id <dir name>] \
//     [--langs en,ja,zh] [--only home,projects]
//
// On a machine without the Chromium system libraries, export LD_LIBRARY_PATH
// with a prefix that provides libatk/libgbm before running (see
// docs/guides/dashboard.md, "Regenerating the documentation screenshots").
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const args = new Map();
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ''), process.argv[i + 1]);
}
const BASE = args.get('base-url') ?? 'http://127.0.0.1:8765';
const OUT = path.resolve(args.get('out') ?? '../../../../docs/assets/images');
const LANGS = (args.get('langs') ?? 'en,ja,zh').split(',');
const RUN = args.get('run-id') ?? '';
const RQGM_RUN = args.get('rqgm-run-id') ?? RUN;
const ONLY = args.get('only') ? new Set(args.get('only').split(',')) : null;
const VIEWPORT = { width: 1440, height: 900 };

// `wait` is a CSS selector that must be visible before the shot. Prefer the
// stable DOM ids the route-render baseline test pins; they are locale-neutral,
// unlike headings. `settle` buys time for D3/React Flow layout passes.
const SHOTS = [
  { name: 'dashboard_home', hash: '#/home' },
  { name: 'dashboard_projects', hash: '#/projects' },
  { name: 'dashboard_experiments', hash: '#/experiments' },
  { name: 'dashboard_overview', hash: '#/overview?run=$RUN' },
  { name: 'dashboard_monitor', hash: '#/monitor', wait: '#page-monitor' },
  { name: 'dashboard_tree', hash: '#/tree2?run=$RUN', wait: '#page-tree2', settle: 1500 },
  { name: 'dashboard_ideas', hash: '#/ideas2?run=$RUN', wait: '#page-ideas2' },
  { name: 'dashboard_results', hash: '#/results2?run=$RUN', wait: '#page-results2' },
  { name: 'dashboard_governance', hash: '#/governance?run=$RQGM', useRqgm: true },
  { name: 'dashboard_config', hash: '#/config?run=$RUN' },
  { name: 'dashboard_studio', hash: '#/studio', wait: '#page-studio' },
  { name: 'dashboard_wizard', hash: '#/wizard' },
  { name: 'dashboard_workflow', hash: '#/workflow', settle: 1500 },
  { name: 'dashboard_paperbench', hash: '#/paperbench' },
  { name: 'dashboard_settings', hash: '#/settings' },
];

async function capture(browser, lang) {
  const dir = path.join(OUT, lang);
  await mkdir(dir, { recursive: true });
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  await ctx.addInitScript((l) => {
    window.localStorage.setItem('ari_lang', l);
    // Developer Mode off so the docs show what a normal operator sees.
    window.localStorage.removeItem('ari_dev_mode');
  }, lang);
  const page = await ctx.newPage();
  const results = [];
  for (const shot of SHOTS) {
    if (ONLY && !ONLY.has(shot.name.replace('dashboard_', ''))) continue;
    const hash = shot.hash.replace('$RQGM', RQGM_RUN).replace('$RUN', RUN);
    if (/\$|run=$/.test(hash)) {
      results.push({ name: shot.name, skipped: 'no run id supplied' });
      continue;
    }
    try {
      await page.goto(`${BASE}/${hash}`, { waitUntil: 'networkidle', timeout: 30000 });
      if (shot.wait) await page.waitForSelector(shot.wait, { state: 'visible', timeout: 15000 });
      else await page.waitForSelector('h1, h2, .card-title', { state: 'visible', timeout: 15000 });
      await page.waitForTimeout(shot.settle ?? 700);
      const file = path.join(dir, `${shot.name}.png`);
      await page.screenshot({ path: file });
      results.push({ name: shot.name, file });
    } catch (err) {
      results.push({ name: shot.name, error: String(err).split('\n')[0] });
    }
  }
  await ctx.close();
  return results;
}

const browser = await chromium.launch();
const report = {};
for (const lang of LANGS) report[lang] = await capture(browser, lang);
await browser.close();

let failed = 0;
for (const [lang, rows] of Object.entries(report)) {
  for (const r of rows) {
    if (r.error) failed += 1;
    console.log(`${lang}\t${r.name}\t${r.error ? 'ERROR ' + r.error : r.skipped ? 'SKIP ' + r.skipped : 'ok'}`);
  }
}
process.exit(failed ? 1 : 0);

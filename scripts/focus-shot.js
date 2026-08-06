#!/usr/bin/env node
// Screenshot just the findings a pull request is about.
//
// A whole-report capture of a large repository is both unusable and the wrong
// thing to send: giovanisp/everything-claude-code renders 1,604 findings, which
// is a 60 MB PNG nobody can open, and a full report in someone else's PR reads
// as an advertisement rather than evidence (see docs/UPSTREAM_PR.md). This
// clips to the rows whose text matches a needle — the three lines a reviewer
// actually needs.
//
//   node scripts/focus-shot.js <owner/repo> <out-dir> <needle> [light|dark]
//
//   BASE    deployment to shoot against (default http://localhost:8080)
//   CHROME  browser executable (default: Google Chrome on macOS)
//
// Requires playwright-core: npm i --no-save playwright-core
const { chromium } = require("playwright-core");
const path = require("path");

const EXECUTABLE = process.env.CHROME
  || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = process.env.BASE || "http://localhost:8080";
const [REPO, OUT = ".", NEEDLE, THEME = "dark"] = process.argv.slice(2);

if (!REPO || !NEEDLE) {
  console.error("usage: focus-shot.js <owner/repo> <out-dir> <needle> [light|dark]");
  process.exit(2);
}

/** Rows whose text contains `needle`, as leaf elements. */
const matches = (needle) => {
  const section = document.querySelector('section[aria-label="Findings"]');
  if (!section) return [];
  return [...section.querySelectorAll("*")].filter(
    (el) => el.textContent.includes(needle) && el.children.length === 0
  );
};

(async () => {
  const browser = await chromium.launch({ executablePath: EXECUTABLE, headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,            // retina — the image is going into a PR
    colorScheme: THEME,
  });

  await page.goto(`${BASE}/?repo=${encodeURIComponent(REPO)}`, { waitUntil: "domcontentloaded" });
  // The pillar table only exists once a real report rendered, so it is the
  // honest "analysis finished" signal; a large repo takes tens of seconds.
  await page.waitForSelector('section[aria-label="Pillar scores"]', { timeout: 300000 });
  await page.waitForTimeout(1500);

  const found = await page.evaluate(([src, needle]) => {
    const hits = new Function("needle", `return (${src})(needle)`)(needle);
    if (!hits.length) return 0;
    hits[0].scrollIntoView({ block: "center" });
    return hits.length;
  }, [matches.toString(), NEEDLE]);

  if (!found) {
    console.error(`no findings matched ${JSON.stringify(NEEDLE)}`);
    await browser.close();
    process.exit(1);
  }
  await page.waitForTimeout(600);

  // `clip` is viewport-relative unless the shot is fullPage, and a fullPage
  // render of the whole table is exactly what this script exists to avoid —
  // hence the scroll above, and the on-screen filter here.
  const box = await page.evaluate(([src, needle]) => {
    const hits = new Function("needle", `return (${src})(needle)`)(needle);

    let top = Infinity, bottom = -Infinity, onScreen = 0;
    for (const el of hits) {
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) continue;
      onScreen++;
      top = Math.min(top, r.top);
      bottom = Math.max(bottom, r.bottom);
    }
    if (top === Infinity) return null;

    // Asymmetric padding, because the match is the message cell and a row is
    // not symmetric around it: the severity pill sits level with the message,
    // but the file path renders beneath it. Too much headroom slices the row
    // above in half; too little bottom padding cuts off the path — and the
    // path is the part a reviewer needs. Climbing to a row container instead
    // is not an option: the findings list has no per-row element to climb to,
    // so it lands on the whole section.
    const PAD_TOP = 12;
    const PAD_BOTTOM = 62;
    const sr = document.querySelector('section[aria-label="Findings"]').getBoundingClientRect();
    const y = Math.max(0, top - PAD_TOP);
    return {
      x: Math.max(0, sr.left),
      y,
      width: Math.min(sr.width, window.innerWidth - sr.left),
      height: Math.min(window.innerHeight - y, (bottom - top) + PAD_TOP + PAD_BOTTOM),
      onScreen,
    };
  }, [matches.toString(), NEEDLE]);

  if (!box) {
    console.error("matches were off-screen after scrolling");
    await browser.close();
    process.exit(1);
  }

  const safe = NEEDLE.replace(/[^A-Za-z0-9._-]+/g, "-");
  const file = path.join(OUT, `findings-${safe}.png`);
  await page.screenshot({ path: file, clip: box });
  console.log(`${found} finding(s) matched; wrote ${file}`);
  if (found > 12) {
    console.warn(`note: ${found} matches is a lot for one PR — narrow the needle`);
  }
  await browser.close();
})().catch((err) => { console.error("FAILED:", err.message); process.exit(1); });

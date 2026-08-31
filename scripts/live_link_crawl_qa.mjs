// Link crawl QA: collects every internal (and externally-linked) href
// reachable from the live demo's guided tour, main nav, and Help Center,
// plus the dashboard's public landing and login page, then verifies each
// one resolves without a 4xx/5xx response. Also flags any link pointing
// at a retired Vercel URL, localhost, or a demo URL other than the one
// real public demo address.
import { chromium } from "@playwright/test";

const DEMO_URL = process.argv[2] || "https://demo.aisecurewatch.com";
const DASHBOARD_URL = process.argv[3] || "https://nice-beach-0bb78f810.7.azurestaticapps.net";
const CORRECT_DEMO_URL = "https://demo.aisecurewatch.com";

const collected = new Map(); // href -> Set of pages it was found on

function record(resolvedHref, rawHref, sourcePage) {
  if (!resolvedHref) return;
  // Keyed by the fully resolved URL, not the raw attribute: a relative
  // href like "/agents" means something different depending on which
  // origin (demo vs dashboard) it was found on, and must not collapse
  // into a single shared key just because the raw text matches.
  if (!collected.has(resolvedHref)) collected.set(resolvedHref, new Set());
  collected.get(resolvedHref).add(`${sourcePage} (raw: ${rawHref})`);
}

async function collectLinksOnPage(page, label) {
  const hrefs = await page.$$eval("a[href]", (els) => els.map((el) => el.getAttribute("href")));
  const pageUrl = page.url();
  let recorded = 0;
  for (const h of hrefs) {
    if (!h) continue;
    if (/^(mailto:|tel:|javascript:|#)/i.test(h)) continue;
    let resolved;
    try {
      // Resolve against the actual page the link was found on, not a
      // single global base, so the demo's and the dashboard's own
      // relative paths ("/agents" etc.) don't collide and get checked
      // against the wrong origin.
      resolved = new URL(h, pageUrl).toString();
    } catch {
      continue;
    }
    record(resolved, h, label);
    recorded++;
  }
  console.log(`  collected ${recorded} link(s) from ${label}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  // The Help Center's Developer and Contact tabs open their external
  // links (SDK docs, API docs, aisecurewatch.com/developers/*) via a
  // plain <button onClick={() => window.open(href, "_blank")}>, not a
  // real <a href>, so a DOM query for anchors alone would silently miss
  // every one of them. Capture the real destination the same way a
  // click actually would, instead of hardcoding the list from source.
  await page.addInitScript(() => {
    window.__capturedOpens = [];
    const originalOpen = window.open;
    window.open = (url, ...rest) => {
      window.__capturedOpens.push(String(url));
      return originalOpen ? null : null;
    };
  });

  console.log("=== Demo: landing, nav pages, guided tour, Help Center ===");
  await page.goto(DEMO_URL, { waitUntil: "networkidle" });
  await collectLinksOnPage(page, "demo landing");

  const navPaths = ["/overview", "/agents", "/governance", "/decisions", "/evidence", "/assurance", "/organization"];
  for (const path of navPaths) {
    await page.goto(`${DEMO_URL}${path}`, { waitUntil: "networkidle" }).catch(() => {});
    await collectLinksOnPage(page, `demo ${path}`);
  }

  // Help Center: Getting Started (default) + Developer + Contact tabs
  // carry the only externally-facing links (SDK docs, API docs, mailto,
  // aisecurewatch.com/developers/*).
  await page.goto(DEMO_URL, { waitUntil: "networkidle" });
  const helpButton = page.getByRole("button", { name: /open help center/i });
  if (await helpButton.count() > 0) {
    await helpButton.click();
    await page.waitForTimeout(300);
    await collectLinksOnPage(page, "demo Help Center: Getting Started");

    await page.getByRole("button", { name: /^developer$/i }).click();
    await page.waitForTimeout(200);
    await collectLinksOnPage(page, "demo Help Center: Developer");
    const devResourceButtons = page.locator('div[class*="space-y-2"] > button');
    const devCount = await devResourceButtons.count();
    for (let i = 0; i < devCount; i++) {
      await devResourceButtons.nth(i).click();
    }

    await page.getByRole("button", { name: /^contact$/i }).click();
    await page.waitForTimeout(200);
    await collectLinksOnPage(page, "demo Help Center: Contact");
    // Only the non-mailto, non-internal Contact actions call window.open
    // (Documentation); System Status navigates internally and the three
    // mailto actions are excluded from the crawl entirely.
    const docButton = page.getByRole("button", { name: /^documentation$/i });
    if (await docButton.count() > 0) await docButton.click();

    const openedUrls = await page.evaluate(() => window.__capturedOpens ?? []);
    const pageUrl = page.url();
    openedUrls.forEach((u) => {
      try {
        record(new URL(u, pageUrl).toString(), u, "demo Help Center: window.open target");
      } catch {
        // not a parseable URL, skip
      }
    });
    console.log(`  captured ${openedUrls.length} window.open() target(s) from Developer/Contact tab buttons`);

    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  }

  // Guided tour: walk all 9 steps, collecting any links each step's
  // destination page renders (decision detail, receipt, etc).
  await page.goto(DEMO_URL, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /start guided demo/i }).first().click();
  await page.waitForTimeout(400);
  for (let step = 1; step <= 9; step++) {
    await page.waitForTimeout(400);
    await collectLinksOnPage(page, `demo tour step ${step}`);
    const dialog = page.getByRole("dialog");
    if (await dialog.count() === 0) break;
    const nextBtn = dialog.getByRole("button", { name: /^next$|^finish$/i });
    if (await nextBtn.count() > 0) await nextBtn.click();
  }

  console.log("\n=== Dashboard: public landing and login page ===");
  await page.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
  await collectLinksOnPage(page, "dashboard landing");
  await page.goto(`${DASHBOARD_URL}/login`, { waitUntil: "networkidle" }).catch(() => {});
  await collectLinksOnPage(page, "dashboard login");

  await browser.close();

  console.log(`\n=== ${collected.size} unique link(s) collected, checking each ===`);

  const browser2 = await chromium.launch();
  const requestBrowserContext = await browser2.newContext();
  const requestContext = requestBrowserContext.request;
  const flagged = [];
  const broken = [];

  for (const [resolved, sources] of collected.entries()) {
    if (/localhost|127\.0\.0\.1/i.test(resolved)) {
      flagged.push(`${resolved}, points at localhost (sources: ${[...sources].join(", ")})`);
    }
    if (/vercel\.app/i.test(resolved)) {
      flagged.push(`${resolved}, points at a retired Vercel URL (sources: ${[...sources].join(", ")})`);
    }
    if (/demo\.[a-z0-9.-]*\.(com|app|dev)/i.test(resolved) && !resolved.startsWith(CORRECT_DEMO_URL)) {
      flagged.push(`${resolved}, looks like a demo URL other than the correct one (sources: ${[...sources].join(", ")})`);
    }

    try {
      const resp = await requestContext.get(resolved, { timeout: 15000, failOnStatusCode: false });
      const status = resp.status();
      const ok = status < 400;
      console.log(`  ${ok ? "OK  " : "FAIL"} [${status}] ${resolved}`);
      if (!ok) broken.push(`${resolved} -> HTTP ${status} (sources: ${[...sources].join(", ")})`);
    } catch (e) {
      console.log(`  FAIL [ERROR] ${resolved}, ${e.message}`);
      broken.push(`${resolved} -> request error: ${e.message} (sources: ${[...sources].join(", ")})`);
    }
  }

  await requestBrowserContext.close();
  await browser2.close();

  console.log(`\n=== Summary: ${broken.length} broken link(s), ${flagged.length} flagged link(s) ===`);
  if (broken.length > 0) {
    console.log("\nBroken (4xx/5xx or request error):");
    broken.forEach((b) => console.log("  " + b));
  }
  if (flagged.length > 0) {
    console.log("\nFlagged (localhost / stale Vercel / wrong demo URL):");
    flagged.forEach((f) => console.log("  " + f));
  }
  process.exitCode = broken.length > 0 || flagged.length > 0 ? 1 : 0;
})();

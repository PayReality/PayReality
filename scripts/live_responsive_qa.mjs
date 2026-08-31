// Responsive QA against the live deployed surfaces (not a local dev server).
// Checks for horizontal overflow (documentElement.scrollWidth vs
// clientWidth) on the demo's landing page and guided tour, and on the
// dashboard's public landing shell and login page, at three viewports:
// 1440x900, 1280x800, 768x1024. Also checks that the tour overlay's
// Next/Back/Skip controls stay within the viewport at each width, since
// that is the one piece of custom-positioned UI most likely to clip on a
// narrow tablet width.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const DEMO_URL = process.argv[2] || "https://demo.aisecurewatch.com";
const DASHBOARD_URL = process.argv[3] || "https://nice-beach-0bb78f810.7.azurestaticapps.net";
const OUT_DIR = "scripts/qa-output/live-responsive";
mkdirSync(OUT_DIR, { recursive: true });

const VIEWPORTS = [
  { width: 1440, height: 900, name: "1440x900" },
  { width: 1280, height: 800, name: "1280x800" },
  { width: 768, height: 1024, name: "768x1024" },
];

const failures = [];
function check(label, ok, detail) {
  if (ok) {
    console.log(`  OK   ${label}`);
  } else {
    console.log(`  FAIL ${label}${detail ? ` (${detail})` : ""}`);
    failures.push(`${label}${detail ? `, ${detail}` : ""}`);
  }
}

async function overflowInfo(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

async function checkNoOverflow(page, label) {
  const { scrollWidth, clientWidth } = await overflowInfo(page);
  // One px of rounding slack for subpixel layout, nothing more.
  check(`${label}: no horizontal overflow`, scrollWidth <= clientWidth + 1, `scrollWidth=${scrollWidth} clientWidth=${clientWidth}`);
}

// The tour overlay repositions its dialog live while the target element
// smooth-scrolls into view (TourOverlay.tsx's own scrollIntoView +
// resize/scroll listeners), so a bounding-box check taken mid-scroll can
// briefly read a transient, off-screen position that self-corrects a few
// hundred milliseconds later. Poll until the box stops moving (or a
// generous timeout elapses) instead of asserting against a single,
// possibly mid-animation, snapshot.
async function waitForStableDialog(page, maxWaitMs = 2500) {
  const start = Date.now();
  let last = null;
  while (Date.now() - start < maxWaitMs) {
    const dialog = page.getByRole("dialog");
    if (await dialog.count() === 0) return;
    const box = await dialog.boundingBox();
    const key = box ? `${box.x},${box.y},${box.width},${box.height}` : null;
    if (key && key === last) return;
    last = key;
    await page.waitForTimeout(150);
  }
}

async function boundsCheckLocator(page, locator, label, viewport) {
  const count = await locator.count();
  if (count === 0) {
    check(label, false, "not found");
    return;
  }
  const box = await locator.first().boundingBox();
  if (!box) {
    check(label, false, "no bounding box (not visible)");
    return;
  }
  const withinRight = box.x + box.width <= viewport.width + 1;
  const withinBottom = box.y + box.height <= viewport.height + 1;
  const withinLeft = box.x >= -1;
  check(label, withinRight && withinBottom && withinLeft, `box=${JSON.stringify(box)} viewport=${viewport.width}x${viewport.height}`);
}

(async () => {
  const browser = await chromium.launch();

  for (const viewport of VIEWPORTS) {
    console.log(`\n=== DEMO @ ${viewport.name} ===`);
    const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
    await page.goto(DEMO_URL, { waitUntil: "networkidle" });
    await checkNoOverflow(page, `demo landing @ ${viewport.name}`);
    await page.screenshot({ path: `${OUT_DIR}/demo-landing-${viewport.name}.png`, fullPage: true });

    // Start the guided tour and walk a handful of steps, checking the
    // overlay dialog and its Next/Back/Skip controls stay on-screen.
    const startBtn = page.getByRole("button", { name: /start guided demo/i }).first();
    if (await startBtn.count() > 0) {
      await startBtn.click();
      await page.waitForTimeout(500);
      const STEPS_TO_CHECK = 4;
      for (let i = 1; i <= STEPS_TO_CHECK; i++) {
        await waitForStableDialog(page);
        const dialog = page.getByRole("dialog");
        await boundsCheckLocator(page, dialog, `tour step ${i} dialog on-screen @ ${viewport.name}`, viewport);
        const nextBtn = dialog.getByRole("button", { name: /^next$|^finish$/i });
        await boundsCheckLocator(page, nextBtn, `tour step ${i} Next/Finish button on-screen @ ${viewport.name}`, viewport);
        if (i > 1) {
          const backBtn = dialog.getByRole("button", { name: /^back$/i });
          await boundsCheckLocator(page, backBtn, `tour step ${i} Back button on-screen @ ${viewport.name}`, viewport);
        }
        const skipBtn = dialog.getByRole("button", { name: /skip tour/i });
        await boundsCheckLocator(page, skipBtn, `tour step ${i} Skip tour button on-screen @ ${viewport.name}`, viewport);
        await checkNoOverflow(page, `demo tour step ${i} @ ${viewport.name}`);
        await page.screenshot({ path: `${OUT_DIR}/demo-tour-step${i}-${viewport.name}.png` });
        if (i < STEPS_TO_CHECK) {
          await nextBtn.click();
        }
      }
    } else {
      check(`tour start button present @ ${viewport.name}`, false, "not found");
    }
    await page.close();
  }

  for (const viewport of VIEWPORTS) {
    console.log(`\n=== DASHBOARD (public surface) @ ${viewport.name} ===`);
    const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
    await page.goto(DASHBOARD_URL, { waitUntil: "networkidle" });
    await checkNoOverflow(page, `dashboard public landing @ ${viewport.name}`);
    await page.screenshot({ path: `${OUT_DIR}/dashboard-landing-${viewport.name}.png`, fullPage: true });

    const signInLink = page.getByRole("link", { name: /sign in/i }).first();
    if (await signInLink.count() > 0) {
      await signInLink.click();
    } else {
      await page.goto(`${DASHBOARD_URL}/login`, { waitUntil: "networkidle" });
    }
    await page.waitForTimeout(400);
    await checkNoOverflow(page, `dashboard login page @ ${viewport.name}`);
    const emailField = page.locator('input[type="email"], input[name="email"], input[type="text"]').first();
    await boundsCheckLocator(page, emailField, `dashboard login email field on-screen @ ${viewport.name}`, viewport);
    const submitBtn = page.getByRole("button", { name: /sign in|log in/i }).first();
    await boundsCheckLocator(page, submitBtn, `dashboard login submit button on-screen @ ${viewport.name}`, viewport);
    await page.screenshot({ path: `${OUT_DIR}/dashboard-login-${viewport.name}.png`, fullPage: true });
    await page.close();
  }

  await browser.close();

  console.log(`\n=== Summary: ${failures.length} failing checks ===`);
  failures.forEach((f) => console.log("  " + f));
  process.exitCode = failures.length > 0 ? 1 : 0;
})();

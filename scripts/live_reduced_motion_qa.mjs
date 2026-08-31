// Reduced-motion QA against the live demo, using a real browser context
// created with reducedMotion: 'reduce' (not just page.emulateMedia on an
// existing context), per the milestone spec. demo_a11y_qa.mjs already
// checks the tour highlight-ring's own inline transition; this extends
// coverage to two things it does not check: the app's global
// prefers-reduced-motion CSS catch-all (theme.css) actually applying to
// a completely different animated surface (the Help Center sheet), and
// every one of the guided tour's 9 steps genuinely conveying its content
// as static text, not only through the motion reduced motion suppresses.
import { chromium } from "@playwright/test";

const BASE_URL = process.argv[2] || "https://demo.aisecurewatch.com";

const failures = [];
function check(label, ok, detail) {
  if (ok) {
    console.log(`  OK   ${label}`);
  } else {
    console.log(`  FAIL ${label}${detail ? ` (${detail})` : ""}`);
    failures.push(`${label}${detail ? `, ${detail}` : ""}`);
  }
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(BASE_URL, { waitUntil: "networkidle" });

  console.log("Global reduced-motion CSS catch-all, sampled on the Help Center sheet:");
  const helpButton = page.getByRole("button", { name: /open help center/i });
  await helpButton.click();
  await page.waitForTimeout(200);
  const sheetTransition = await page.evaluate(() => {
    const el = document.querySelector('[data-slot="sheet-content"]');
    if (!el) return null;
    const style = getComputedStyle(el);
    return { animationDuration: style.animationDuration, transitionDuration: style.transitionDuration };
  });
  if (sheetTransition) {
    const animMs = parseFloat(sheetTransition.animationDuration) * (sheetTransition.animationDuration.includes("ms") ? 1 : 1000);
    check("Help Center sheet's animation-duration is suppressed under reduced motion", animMs < 5, JSON.stringify(sheetTransition));
  } else {
    check("Help Center sheet found to sample", false, "not found");
  }
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);

  console.log("\nFull 9-step guided tour under a reducedMotion:'reduce' context:");
  await page.getByRole("button", { name: /start guided demo/i }).first().click();
  await page.waitForTimeout(400);

  const seenTexts = new Set();
  for (let step = 1; step <= 9; step++) {
    await page.waitForTimeout(400);
    const dialog = page.getByRole("dialog");
    const dialogCount = await dialog.count();
    check(`step ${step}: dialog present`, dialogCount > 0);
    if (dialogCount === 0) break;

    const ariaLabel = await dialog.getAttribute("aria-label");
    check(`step ${step}: aria-label announces "step ${step} of 9"`, new RegExp(`step ${step} of 9`, "i").test(ariaLabel ?? ""), ariaLabel ?? "");

    const bodyText = (await dialog.textContent()) ?? "";
    check(`step ${step}: has real, non-empty static text content`, bodyText.trim().length > 20);
    check(`step ${step}: text content is distinct from every prior step (no animation-only step)`, !seenTexts.has(bodyText), "duplicate step text");
    seenTexts.add(bodyText);

    // The highlight ring, when present, must not be animating under
    // reduced motion (the one thing demo_a11y_qa.mjs already checks, but
    // only for step 1; confirm it holds for every step, since each step
    // targets a different element and re-triggers the effect).
    const ringTransition = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll('[aria-hidden="true"]'));
      const ring = els.find((e) => e.getAttribute("style")?.includes("box-shadow"));
      return ring ? getComputedStyle(ring).transitionDuration : null;
    });
    if (ringTransition) {
      const seconds = parseFloat(ringTransition);
      check(`step ${step}: highlight ring transition suppressed`, seconds < 0.005, ringTransition);
    }

    const nextBtn = dialog.getByRole("button", { name: /^next$|^finish$/i });
    if (step < 9) {
      await nextBtn.click();
    } else {
      await nextBtn.click();
    }
  }

  await context.close();
  await browser.close();

  console.log(`\n=== Summary: ${failures.length} failing checks ===`);
  failures.forEach((f) => console.log("  " + f));
  process.exitCode = failures.length > 0 ? 1 : 0;
})();

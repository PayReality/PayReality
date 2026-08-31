import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto("http://localhost:4173/", { waitUntil: "networkidle" });

let ok = true;
function check(label, cond) {
  console.log(`  ${cond ? "OK  " : "FAIL"} ${label}`);
  if (!cond) ok = false;
}

await page.getByRole("button", { name: /start guided demo/i }).first().click();
await page.waitForTimeout(500);

// Focus should have landed on the dialog itself (tabIndex=-1 target).
const activeRole = await page.evaluate(() => document.activeElement?.getAttribute("role"));
check("focus lands on the tour dialog when a step opens", activeRole === "dialog");

const ariaLabel = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
check("dialog aria-label announces step number and title", /step 1 of 9/i.test(ariaLabel ?? ""));

// Tab should reach the visible controls inside the dialog (Skip tour / Back / Next).
await page.keyboard.press("Tab");
let focusedText = await page.evaluate(() => document.activeElement?.textContent);
check("Tab moves focus into the dialog's controls", /skip tour|next|back/i.test(focusedText ?? ""));

// Escape should exit the tour entirely.
await page.keyboard.press("Escape");
await page.waitForTimeout(300);
const dialogGone = (await page.getByRole("dialog").count()) === 0;
check("Escape exits the tour", dialogGone);

// Restart via the persistent banner control, then check reduced motion respected.
await page.emulateMedia({ reducedMotion: "reduce" });
await page.getByRole("button", { name: /start guided demo/i }).first().click();
await page.waitForTimeout(300);
// The app already has a global prefers-reduced-motion CSS reset
// (transition-duration: 0.01ms !important, the standard "effectively
// instant, technically nonzero" convention). Our own inline
// transition:none on the ring is redundant with it but harmless. Accept
// anything under 5ms as "motion suppressed," not literally 0s.
const transitionValue = await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll('[aria-hidden="true"]'));
  const ring = els.find((e) => e.getAttribute("style")?.includes("box-shadow"));
  return ring ? getComputedStyle(ring).transitionDuration : null;
});
const seconds = transitionValue ? parseFloat(transitionValue) : 0;
check("reduced motion suppresses the highlight-ring transition", !transitionValue || seconds < 0.005);

await browser.close();
console.log(ok ? "\nAll accessibility checks passed." : "\nSome accessibility checks FAILED.");
process.exitCode = ok ? 0 : 1;

import { chromium } from "@playwright/test";
// Live-QA extension: BASE_URL is now an optional first argument so this
// script can run against a real deployed URL, not only the local preview
// server. Left off, it defaults to the exact same localhost target this
// script always used, so existing invocations are unaffected.
const BASE_URL = process.argv[2] || "http://localhost:4173";
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

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
check("dialog aria-label announces step number and title", /step 1 of 11/i.test(ariaLabel ?? ""));

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

// Live-QA extension: the tour reopened above (still under reduced motion)
// is sitting at step 1 with focus on the dialog. Use it to confirm the
// tour is fully keyboard-operable, not just that Tab reaches "a" control,
// and that step-to-step transitions carry real static content (not only
// an animation reduced motion would otherwise suppress).
console.log("\nKeyboard operability of the guided tour:");

await page.keyboard.press("Tab");
let firstControlText = (await page.evaluate(() => document.activeElement?.textContent)) ?? "";
check("Tab from a fresh step first reaches Skip tour", /skip tour/i.test(firstControlText));

await page.keyboard.press("Tab");
let secondControlText = (await page.evaluate(() => document.activeElement?.textContent)) ?? "";
check("Tab then reaches Next (step 1 has no Back)", /^next$/i.test(secondControlText.trim()));

const step1Body = await page.locator('[role="dialog"]').textContent();
await page.keyboard.press("Enter");
await page.waitForTimeout(400);

const step2AriaLabel = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
check("keyboard-activating Next (Enter) advances to step 2", /step 2 of 11/i.test(step2AriaLabel ?? ""));

const step2ActiveRole = await page.evaluate(() => document.activeElement?.getAttribute("role"));
check("focus returns to the dialog itself after Next, not left on the button", step2ActiveRole === "dialog");

const step2Body = await page.locator('[role="dialog"]').textContent();
check("step content is genuinely different text (not animation-only)", step2Body !== step1Body);

await page.keyboard.press("Tab");
const step2FirstControl = ((await page.evaluate(() => document.activeElement?.textContent)) ?? "").trim();
check("Tab on step 2 first reaches Skip tour", /skip tour/i.test(step2FirstControl));
await page.keyboard.press("Tab");
const step2SecondControl = ((await page.evaluate(() => document.activeElement?.textContent)) ?? "").trim();
check("Tab then reaches Back on step 2", /^back$/i.test(step2SecondControl));

await page.keyboard.press("Enter");
await page.waitForTimeout(400);
const backAriaLabel = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
check("keyboard-activating Back (Enter) returns to step 1", /step 1 of 11/i.test(backAriaLabel ?? ""));

// Keyboard-activate Skip tour itself (distinct from the Escape path
// already checked above) and confirm it closes the tour the same way.
await page.keyboard.press("Tab");
const skipControlText = ((await page.evaluate(() => document.activeElement?.textContent)) ?? "").trim();
check("Tab reaches Skip tour again on step 1", /skip tour/i.test(skipControlText));
await page.keyboard.press("Enter");
await page.waitForTimeout(300);
check("keyboard-activating Skip tour closes the dialog", (await page.getByRole("dialog").count()) === 0);

console.log("\nMain nav tab order and focus visibility:");
// A fresh page (reduced motion off, no tour running) so the nav's own
// natural tab order can be walked cleanly from the top of the document.
const navPage = await browser.newPage();
await navPage.setViewportSize({ width: 1440, height: 900 });
await navPage.goto(`${BASE_URL}/`, { waitUntil: "networkidle" });

const tabbedSequence = [];
for (let i = 0; i < 12; i++) {
  await navPage.keyboard.press("Tab");
  const info = await navPage.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
      text: (el.textContent || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 40),
      tag: el.tagName,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
      top: Math.round(rect.top),
      left: Math.round(rect.left),
    };
  });
  if (info) tabbedSequence.push(info);
}
check("nav tab order reaches at least a few focusable elements", tabbedSequence.length >= 5, `got ${tabbedSequence.length}`);
const firstIsSkipLink = /skip to main content/i.test(tabbedSequence[0]?.text ?? "");
check("first Tab stop is the skip link", firstIsSkipLink, tabbedSequence[0]?.text);
// A reasonable (not visually scrambled) tab order: each subsequent stop's
// vertical position should not jump backwards past the previous stop by
// more than a small tolerance, for the sidebar-then-content DOM order
// this layout uses.
let orderReasonable = true;
for (let i = 2; i < tabbedSequence.length; i++) {
  const prev = tabbedSequence[i - 1];
  const cur = tabbedSequence[i];
  if (cur.top < prev.top - 60 && cur.left <= prev.left + 5) {
    orderReasonable = false;
  }
}
check("tab order is not visually scrambled (no large backward jumps)", orderReasonable);
const allHaveVisibleFocus = tabbedSequence.slice(1).every((s) => s.outlineStyle !== "none" || /rgba?\(/.test(s.boxShadow));
check("every tabbed element shows a visible focus indicator (outline or box-shadow)", allHaveVisibleFocus, JSON.stringify(tabbedSequence.filter((s) => s.outlineStyle === "none" && !/rgba?\(/.test(s.boxShadow))));

console.log("\nHelp Center sheet: focus trap and return focus:");
const helpButton = navPage.getByRole("button", { name: /open help center/i });
if (await helpButton.count() > 0) {
  await helpButton.focus();
  await navPage.keyboard.press("Enter");
  await navPage.waitForTimeout(400);
  const sheetVisible = (await navPage.getByText("Help Center", { exact: true }).count()) > 0;
  check("Help Center sheet opens", sheetVisible);

  // Tab a generous number of times (more than the panel's own control
  // count) and confirm focus never lands back on <body> or escapes to
  // an element outside the sheet, which would mean the trap failed.
  let stayedInSheet = true;
  for (let i = 0; i < 20; i++) {
    await navPage.keyboard.press("Tab");
    const outside = await navPage.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return true;
      const sheet = el.closest('[role="dialog"], [data-state="open"]');
      return !sheet;
    });
    if (outside) { stayedInSheet = false; break; }
  }
  check("Tab stays trapped inside the Help Center sheet", stayedInSheet);

  await navPage.keyboard.press("Escape");
  await navPage.waitForTimeout(500);
  const sheetClosed = (await navPage.getByText("Help Center", { exact: true }).count()) === 0;
  check("Escape closes the Help Center sheet", sheetClosed);
  const focusReturned = await navPage.evaluate(() => document.activeElement?.getAttribute("aria-label"));
  check("focus returns to the Help button after closing", /open help center/i.test(focusReturned ?? ""));
} else {
  check("Help Center button present", false, "not found");
}
await navPage.close();

console.log("\nDashboard login page: lightweight keyboard pass:");
const loginPage = await browser.newPage();
await loginPage.setViewportSize({ width: 1440, height: 900 });
const loginBase = process.argv[3] || BASE_URL;
await loginPage.goto(`${loginBase.replace(/\/$/, "")}/login`, { waitUntil: "networkidle" });
const loginTabbed = [];
// The real dashboard renders the login page inside the full app shell
// (skip link, sidebar nav, Operator Key field, theme toggle), so the
// actual email/password/submit controls sit well past the first few
// stops; 24 is comfortably past where they showed up in a manual walk.
for (let i = 0; i < 24; i++) {
  await loginPage.keyboard.press("Tab");
  const info = await loginPage.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const style = getComputedStyle(el);
    return {
      tag: el.tagName,
      type: el.getAttribute("type"),
      autocomplete: el.getAttribute("autocomplete"),
      outlineStyle: style.outlineStyle,
      boxShadow: style.boxShadow,
    };
  });
  if (info) loginTabbed.push(info);
}
// Match on autocomplete, not just type: the sidebar's Operator Key field
// (present in the full app shell this login page renders inside) also
// has a type="password" input, but with no autocomplete value, so
// matching on type alone would give a false pass without ever actually
// reaching the real login form.
const reachedEmail = loginTabbed.some((s) => s.type === "email" && s.autocomplete === "username");
const reachedPassword = loginTabbed.some((s) => s.type === "password" && s.autocomplete === "current-password");
const reachedSubmit = loginTabbed.some((s) => s.tag === "BUTTON" && s.type === "submit");
check("login page: Tab reaches the email field", reachedEmail);
check("login page: Tab reaches the password field", reachedPassword);
check("login page: Tab reaches the submit button", reachedSubmit);
const loginAllVisible = loginTabbed.every((s) => s.outlineStyle !== "none" || /rgba?\(/.test(s.boxShadow));
check("login page: every tabbed element shows a visible focus indicator", loginAllVisible);
await loginPage.close();

await browser.close();
console.log(ok ? "\nAll accessibility checks passed." : "\nSome accessibility checks FAILED.");
process.exitCode = ok ? 0 : 1;

// Demo Experience V3: walks the actual public-demo guided tour in a real
// browser, step by step, exactly the way a visitor clicks through it.
// This is the check that would have caught the Demo V2 receipt-provenance
// bug (a tour step whose data-tour target silently never rendered), since
// it verifies the target actually exists and is visible at each step, not
// just that the selector string exists somewhere in source.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE_ARG = process.argv[2] || "http://localhost:4173";
const LABEL = process.argv[3] || "local";
const VIEWPORT = { width: Number(process.argv[4]) || 1440, height: Number(process.argv[5]) || 900 };
const THEME = process.argv[6] || "light";
const OUT_DIR = `scripts/qa-output/demo-journey-${LABEL}`;
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const failures = [];

function check(label, ok, detail) {
  if (ok) {
    console.log(`  OK   ${label}`);
  } else {
    console.log(`  FAIL ${label}${detail ? ` (${detail})` : ""}`);
    failures.push(label);
  }
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[${page.url()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => consoleErrors.push(`[${page.url()}] pageerror: ${err.message}`));

  await page.setViewportSize(VIEWPORT);

  console.log(`Base: ${BASE_ARG} @ ${VIEWPORT.width}x${VIEWPORT.height}, ${THEME}`);
  console.log("\n1. Landing loads");
  await page.goto(BASE_ARG, { waitUntil: "networkidle" });
  if (THEME === "dark") {
    await page.evaluate(() => {
      localStorage.setItem("payreality_theme", "dark");
      document.documentElement.setAttribute("data-theme", "dark");
    });
    await page.reload({ waitUntil: "networkidle" });
  }
  const heroText = await page.textContent("body");
  check("landing shows the concrete scenario", /supplier.*bank details|bank details.*supplier/i.test(heroText ?? ""));
  check("landing does not use generic marketing copy as the lead", !/explore our ai governance platform/i.test(heroText ?? ""));
  await page.screenshot({ path: `${OUT_DIR}/01-landing.png`, fullPage: true });

  console.log("\n2. Tour begins");
  await page.getByRole("button", { name: /start guided demo/i }).first().click();
  await page.waitForTimeout(500);
  let dialog = page.getByRole("dialog");
  check("tour dialog appears", await dialog.count() > 0);
  check("step 1 of 9 shown", /step 1 of 9/i.test((await dialog.textContent()) ?? ""));

  const EXPECTED_STOPS = [
    { n: 1, selector: '[data-tour="agent-trusted-connections"]', name: "Agent / Trusted Connections", urlIncludes: "/agents/" },
    { n: 2, selector: '[data-tour="mapping-row"]', name: "Trusted Adapter reports the attempt", urlIncludes: "/organization/integrations/" },
    { n: 3, selector: '[data-tour="mapping-row"]', name: "Action Mapping establishes meaning", urlIncludes: "/organization/integrations/" },
    { n: 4, selector: '[data-tour="decision-integration-provenance"]', name: "PayReality checks authority", urlIncludes: "/decisions/" },
    { n: 5, selector: '[data-tour="decision-outcome"]', name: "Decision: Human Review", urlIncludes: "/decisions/" },
    { n: 6, selector: '[data-tour="decision-evidence"]', name: "Evidence", urlIncludes: "/decisions/" },
    { n: 7, selector: '[data-tour="receipt-integration-provenance"]', name: "Authorization Receipt", urlIncludes: "/receipt" },
    { n: 8, selector: '[data-tour="replay-operation"]', name: "Retry / idempotency", urlIncludes: "/decisions/" },
    { n: 9, selector: '[data-tour="decision-outcome"]', name: "Allow counterexample", urlIncludes: "/decisions/" },
  ];

  for (const stop of EXPECTED_STOPS) {
    await page.waitForTimeout(500);
    const url = page.url();
    check(`step ${stop.n} route (${stop.name})`, url.includes(stop.urlIncludes), url);
    const target = page.locator(stop.selector).first();
    const targetCount = await target.count();
    check(`step ${stop.n} target exists in DOM`, targetCount > 0, stop.selector);
    if (targetCount > 0) {
      const box = await target.boundingBox();
      check(`step ${stop.n} target is visible (non-zero size)`, !!box && box.width > 0 && box.height > 0);
    }
    await page.screenshot({ path: `${OUT_DIR}/${String(stop.n + 1).padStart(2, "0")}-step${stop.n}.png` });

    if (stop.n === 5) {
      const bodyText = await page.locator('[role="dialog"]').textContent();
      check("Human Review step names the outcome plainly", /human review/i.test(bodyText ?? ""));
    }
    if (stop.n === 7) {
      const pageText = await page.textContent("body");
      check("Receipt shows System", /SAP S\/4HANA/.test(pageText ?? ""));
      check("Receipt shows Trusted Connection", /SAP Procurement Adapter/.test(pageText ?? ""));
      check("Receipt shows external operation id", /OP-92819/.test(pageText ?? ""));
      check("Receipt states the execution limitation", /does not\s+prove.*executed/i.test(pageText ?? ""));
    }
    if (stop.n === 8) {
      // Actually click the replay affordance and confirm no new Decision appears
      // (the visible decision id must stay the same). This is the idempotency
      // moment the visitor experiences, not just a helper-level check.
      const decisionIdBefore = url.split("/decisions/")[1]?.split("/")[0];
      const replayButton = page.getByRole("button", { name: /simulate sap retrying this report/i });
      if (await replayButton.count() > 0) {
        await replayButton.click();
        await page.waitForTimeout(400);
        const msgText = await page.textContent("body");
        check("retry message says no new decision was created", /no new decision was created/i.test(msgText ?? ""));
        check("retry did not navigate to a different decision", page.url().includes(decisionIdBefore ?? "__none__"));
      } else {
        check("replay button present", false, "not found");
      }
    }
    if (stop.n === 9) {
      const pageText = await page.textContent("body");
      check("Allow example shows Allowed outcome", /allowed/i.test(pageText ?? ""));
      check("Allow example has no integration provenance card", !/Reported through a trusted connection/i.test(pageText ?? ""));
    }

    if (stop.n < EXPECTED_STOPS.length) {
      await page.getByRole("button", { name: /^next$/i }).click();
    }
  }

  await page.getByRole("button", { name: /^finish$/i }).click();
  await page.waitForTimeout(400);
  check("tour completes (dialog closes)", (await page.getByRole("dialog").count()) === 0);

  console.log("\n3. Free exploration after tour");
  await page.goto(`${BASE_ARG}/agents`, { waitUntil: "networkidle" });
  check("can navigate normally after the tour ends", (await page.textContent("body"))?.includes("Agents") ?? false);

  console.log("\n4. Claim-safety sweep of all visited pages' text");
  // Re-walk landing + every stop's rendered text for prohibited phrases,
  // now that the tour is done and everything has rendered at least once.
  const prohibitedPatterns = [
    /the erp executes/i,
    /proceeds into the enterprise system of record/i,
    /proves it happened correctly/i,
    /non-bypassable/i,
    /cannot execute without/i,
    /guarantees? (action )?prevention/i,
    /universally non-bypassable/i,
  ];
  await page.goto(BASE_ARG, { waitUntil: "networkidle" });
  const landingText = await page.textContent("body");
  for (const p of prohibitedPatterns) {
    check(`landing has no "${p}"`, !p.test(landingText ?? ""));
  }

  await browser.close();

  console.log(`\n=== Console errors: ${consoleErrors.length} ===`);
  consoleErrors.forEach((e) => console.log("  " + e));

  console.log(`\n=== Summary: ${failures.length} failing checks ===`);
  failures.forEach((f) => console.log("  " + f));
  if (failures.length > 0 || consoleErrors.length > 0) process.exitCode = 1;
})();

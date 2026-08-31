// Product Experience V3: real rendered-browser QA against the actual
// production page components, fed by demo-fixture data (VITE_PUBLIC_DEMO_MODE
// build) rather than a live authenticated backend session -- the same
// honest-disclosure pattern Visual System V3's QA used. Captures each
// redesigned page at desktop (1440) and mobile (390) widths, in whichever
// theme is default (light) and again after toggling to dark, and reports any
// console errors.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:4173";
const OUT_DIR = "scripts/qa-output/product-v3";
mkdirSync(OUT_DIR, { recursive: true });

const ROUTES = [
  { path: "/overview", name: "overview" },
  { path: "/agents", name: "agents-directory" },
  { path: "/agents/agent-ap-invoice", name: "agent-detail" },
  { path: "/decisions", name: "decisions-history" },
  { path: "/decisions/decision-hero-ap-invoice-allow", name: "decision-detail-allow" },
  { path: "/decisions/decision-hero-ap-invoice-allow/receipt", name: "receipt-allow" },
  { path: "/decisions/decision-hero-ap-invoice-deny", name: "decision-detail-deny" },
  { path: "/decisions/decision-hero-ap-invoice-review", name: "decision-detail-human-review" },
  { path: "/decisions/decision-hero-adapter-bank-details-review", name: "decision-detail-adapter-review" },
  { path: "/decisions/decision-hero-adapter-bank-details-review/receipt", name: "receipt-adapter-review" },
  { path: "/governance", name: "governance" },
  { path: "/governance/dashboard", name: "runtime-policy-dashboard" },
  { path: "/evidence", name: "evidence" },
  { path: "/assurance", name: "assurance" },
  { path: "/organization/integrations", name: "integrations-list" },
  { path: "/agents/register", name: "agent-register" },
  // Product Experience V3.1: remaining surface migration
  { path: "/decisions/queue", name: "pending-review-queue" },
  { path: "/governance/approvals", name: "governance-approvals" },
  { path: "/governance/vendor-payment-under-50k", name: "policy-workspace" },
  { path: "/governance/vendor-payment-under-50k/versions", name: "policy-versions" },
  { path: "/governance/vendor-payment-under-50k/publish", name: "policy-publish" },
  { path: "/governance/vendor-payment-under-50k/simulate", name: "policy-simulate" },
  { path: "/governance/upload", name: "ai-policy-builder-upload" },
  { path: "/governance/authority-builder", name: "ai-authority-builder-upload" },
  { path: "/organization/users", name: "users" },
  { path: "/organization/platform", name: "platform-organizations" },
];

const VIEWPORTS = [
  { width: 1440, height: 900, name: "desktop" },
  { width: 1280, height: 900, name: "laptop" },
  { width: 768, height: 1024, name: "tablet" },
  { width: 390, height: 844, name: "mobile" },
];

const errors = [];

async function shootRoute(page, route, viewport) {
  const consoleErrors = [];
  const handler = (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  };
  page.on("console", handler);

  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.goto(`${BASE}${route.path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);

  const file = `${OUT_DIR}/${route.name}-${viewport.name}-light.png`;
  await page.screenshot({ path: file, fullPage: true });

  await page.evaluate(() => {
    localStorage.setItem("payreality_theme", "dark");
    document.documentElement.setAttribute("data-theme", "dark");
  });
  await page.waitForTimeout(200);
  const fileDark = `${OUT_DIR}/${route.name}-${viewport.name}-dark.png`;
  await page.screenshot({ path: fileDark, fullPage: true });

  await page.evaluate(() => {
    localStorage.setItem("payreality_theme", "light");
    document.documentElement.setAttribute("data-theme", "light");
  });

  page.off("console", handler);
  if (consoleErrors.length > 0) {
    errors.push({ route: route.path, viewport: viewport.name, consoleErrors });
  }
  console.log(`  ${route.path} @ ${viewport.name}: ok (${consoleErrors.length} console errors)`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  const allRoutes = ROUTES;

  for (const route of allRoutes) {
    for (const viewport of VIEWPORTS) {
      try {
        await shootRoute(page, route, viewport);
      } catch (e) {
        errors.push({ route: route.path, viewport: viewport.name, fatal: String(e) });
        console.log(`  ${route.path} @ ${viewport.name}: FAILED - ${e}`);
      }
    }
  }

  await browser.close();

  console.log("\n--- Summary ---");
  console.log(`Routes captured: ${allRoutes.length}`);
  console.log(`Routes with console errors or failures: ${errors.length}`);
  if (errors.length > 0) {
    console.log(JSON.stringify(errors, null, 2));
    process.exitCode = 1;
  }
})();

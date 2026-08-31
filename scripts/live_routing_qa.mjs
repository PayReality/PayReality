// 404/routing QA against the live demo. Confirms Azure Static Web Apps'
// navigationFallback (public/staticwebapp.config.json: rewrite everything
// except /assets and static file extensions to /index.html) is actually
// wired up correctly end to end: a direct, fresh (non-client-side)
// navigation to a real deep route resolves the real app, a hard refresh
// on that same deep route survives, and a genuinely unknown route gets a
// real Not Found experience rather than a blank page or a raw server
// error.
import { chromium } from "@playwright/test";

const DEMO_URL = process.argv[2] || "https://demo.aisecurewatch.com";

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

  console.log("=== Direct fresh navigation to a deep route ===");
  {
    const page = await browser.newPage();
    const resp = await page.goto(`${DEMO_URL}/agents`, { waitUntil: "networkidle" });
    check("HTTP status is 200 (not a server error)", resp.status() === 200, `status=${resp.status()}`);
    const bodyText = (await page.textContent("body")) ?? "";
    check("real app shell loaded (nav present)", /Overview/.test(bodyText) && /Decisions/.test(bodyText));
    check("the deep route's own content rendered, not a blank/error page", /Agents/i.test(bodyText));
    check("did not silently fall back to the landing page instead of the requested route", !/Start Guided Demo/.test(bodyText) || page.url().endsWith("/agents"));

    console.log("\n=== Hard refresh on that same deep route ===");
    const reloadResp = await page.reload({ waitUntil: "networkidle" });
    check("hard refresh: HTTP status is 200", reloadResp.status() === 200, `status=${reloadResp.status()}`);
    check("hard refresh: URL is unchanged (still /agents, no redirect to /)", page.url() === `${DEMO_URL}/agents` || page.url() === `${DEMO_URL}/agents/`, page.url());
    const reloadedBody = (await page.textContent("body")) ?? "";
    check("hard refresh: the same route's content is still there", /Agents/i.test(reloadedBody));
    await page.close();
  }

  console.log("\n=== A second, differently-shaped deep route (decision detail) ===");
  {
    const page = await browser.newPage();
    const resp = await page.goto(`${DEMO_URL}/decisions/decision-hero-ap-invoice-review`, { waitUntil: "networkidle" });
    check("HTTP status is 200", resp.status() === 200, `status=${resp.status()}`);
    const bodyText = (await page.textContent("body")) ?? "";
    check("decision detail content rendered on a fresh load", /decision/i.test(bodyText));
    await page.close();
  }

  console.log("\n=== Genuinely unknown route ===");
  {
    const page = await browser.newPage();
    const resp = await page.goto(`${DEMO_URL}/this-does-not-exist`, { waitUntil: "networkidle" });
    check("HTTP status is 200 (SPA fallback serves index.html, not a raw 404/500)", resp.status() === 200, `status=${resp.status()}`);
    const bodyText = (await page.textContent("body")) ?? "";
    check("page is not blank", bodyText.trim().length > 50);
    check("shows a real Not Found experience, not the landing page silently substituted", /page not found/i.test(bodyText));
    const returnLink = page.getByRole("link", { name: /return to dashboard/i });
    check("Not Found page offers a real way back in", await returnLink.count() > 0);
    await page.close();
  }

  console.log("\n=== Unknown route nested under a real segment ===");
  {
    const page = await browser.newPage();
    const resp = await page.goto(`${DEMO_URL}/agents/this-agent-does-not-exist-at-all`, { waitUntil: "networkidle" });
    check("HTTP status is 200", resp.status() === 200, `status=${resp.status()}`);
    const bodyText = (await page.textContent("body")) ?? "";
    // AgentDetailPage is expected to render its own "not found"-shaped
    // state for an unknown id (a real page, not the router's generic
    // NotFound), so just confirm it isn't blank and isn't a raw error.
    check("page is not blank and not a raw error page", bodyText.trim().length > 50 && !/application error|unhandled exception/i.test(bodyText));
    await page.close();
  }

  await browser.close();

  console.log(`\n=== Summary: ${failures.length} failing checks ===`);
  failures.forEach((f) => console.log("  " + f));
  process.exitCode = failures.length > 0 ? 1 : 0;
})();

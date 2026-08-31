// Visual System V3 (section 34): real rendered-browser evidence for the
// five prototype pages, in both themes. Ad hoc, not part of the test
// suite, run manually against `vite preview`, screenshots saved to
// the given output directory for human review. Deleted or kept as a
// dev-only QA script; never imported by app code.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.QA_BASE_URL ?? "http://localhost:4173";
const OUT = process.argv[2] ?? "./qa-screenshots";
mkdirSync(OUT, { recursive: true });

const PAGES = [
  { path: "/_design-system", name: "gallery" },
  { path: "/_design-system/overview", name: "overview" },
  { path: "/_design-system/agent-detail", name: "agent-detail" },
  { path: "/_design-system/decision-detail", name: "decision-detail" },
  { path: "/_design-system/integration-detail", name: "integration-detail" },
  { path: "/_design-system/receipt", name: "receipt" },
];

const browser = await chromium.launch();
let failures = 0;

for (const { path, name } of PAGES) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(`console.error: ${m.text()}`); });

  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  // The real app's actual default (src/app/lib/theme.ts) is light, not
  // dark; label the first screenshot by what's really on screen
  // rather than assuming, and toggle by a stable selector so this works
  // regardless of which theme happens to be the starting one.
  const startTheme = await page.evaluate(() => document.documentElement.dataset.theme === "light" ? "light" : "dark");
  await page.screenshot({ path: `${OUT}/${name}-${startTheme}.png`, fullPage: true });

  // Toggle via the prototype shell's own button (gallery has none, skip).
  const toggle = page.getByTestId("prototype-theme-toggle");
  if (await toggle.count() > 0) {
    await toggle.click();
    await page.waitForTimeout(200);
    const endTheme = startTheme === "dark" ? "light" : "dark";
    await page.screenshot({ path: `${OUT}/${name}-${endTheme}.png`, fullPage: true });
  }

  if (consoleErrors.length > 0) {
    failures++;
    console.log(`FAIL ${path}: ${consoleErrors.join(" | ")}`);
  } else {
    console.log(`OK   ${path}`);
  }
  await page.close();
}

await browser.close();
console.log(failures === 0 ? "\nALL PAGES CLEAN (no console/page errors)" : `\n${failures} page(s) had console/page errors`);
process.exit(failures === 0 ? 0 : 1);

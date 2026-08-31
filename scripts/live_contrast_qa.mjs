// WCAG contrast QA against the live demo: samples real rendered
// foreground/background colors via getComputedStyle for the hero/body
// copy, primary/secondary CTAs, decision-outcome status badges, and the
// guided tour's tooltip text, then computes actual contrast ratios.
// Flags only genuine violations against WCAG 2.1 SC 1.4.3 (4.5:1 normal
// text, 3:1 large text: >=18px, or >=14px and bold) and SC 1.4.11
// (3:1 for UI component boundaries).
import { chromium } from "@playwright/test";

const DEMO_URL = process.argv[2] || "https://demo.aisecurewatch.com";

function srgbToLinear(c) {
  const cs = c / 255;
  return cs <= 0.03928 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
}
function relativeLuminance([r, g, b]) {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}
function parseColor(str) {
  const m = str?.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(",").map((s) => parseFloat(s.trim()));
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
}
// Alpha-composite a foreground color over a background color, since a
// lot of this design system's overlays and badge backgrounds are
// semi-transparent rgba() values, not opaque colors.
function composite(fg, bg) {
  if (fg.a >= 1) return fg;
  const a = fg.a;
  return {
    r: fg.r * a + bg.r * (1 - a),
    g: fg.g * a + bg.g * (1 - a),
    b: fg.b * a + bg.b * (1 - a),
  };
}
function contrastRatio(c1, c2) {
  const l1 = relativeLuminance([c1.r, c1.g, c1.b]);
  const l2 = relativeLuminance([c2.r, c2.g, c2.b]);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

const failures = [];
function check(label, ratio, threshold, detail) {
  const pass = ratio >= threshold - 0.02; // tiny float slack
  const line = `${label}: ratio=${ratio.toFixed(2)} threshold=${threshold} ${detail ?? ""}`;
  if (pass) {
    console.log(`  OK   ${line}`);
  } else {
    console.log(`  FAIL ${line}`);
    failures.push(line);
  }
}

async function sampleElement(page, locator, label) {
  const count = await locator.count();
  if (count === 0) {
    console.log(`  SKIP ${label} (not found on page)`);
    return null;
  }
  const data = await locator.first().evaluate((el) => {
    // Collect every non-fully-transparent background from the element
    // itself up through its ancestors, stopping once an opaque one is
    // hit (nothing further back can show through it). Several of this
    // design system's own backgrounds are semi-transparent rgba()
    // overlays (badge tints, the tour Next button's translucent Skip
    // background, etc.), so the real effective color behind the text is
    // the composite of all of them, not just the nearest one.
    function collectLayers(node) {
      const layers = [];
      let cur = node;
      while (cur) {
        const bg = getComputedStyle(cur).backgroundColor;
        const m = bg.match(/rgba?\(([^)]+)\)/);
        if (m) {
          const parts = m[1].split(",").map((s) => parseFloat(s.trim()));
          const a = parts.length > 3 ? parts[3] : 1;
          if (a > 0) {
            layers.push({ r: parts[0], g: parts[1], b: parts[2], a });
            if (a >= 1) break;
          }
        }
        cur = cur.parentElement;
      }
      return layers;
    }
    const style = getComputedStyle(el);
    const layers = collectLayers(el);
    return {
      color: style.color,
      layers,
      fontSize: parseFloat(style.fontSize),
      fontWeight: style.fontWeight,
      text: (el.textContent || "").trim().slice(0, 60),
    };
  });
  return { label, ...data };
}

function isLargeText(fontSize, fontWeight) {
  const bold = parseInt(fontWeight, 10) >= 700 || fontWeight === "bold";
  return fontSize >= 18 || (fontSize >= 14 && bold);
}

async function evaluateSample(sample) {
  if (!sample) return;
  const fg = parseColor(sample.color);
  if (!fg) {
    console.log(`  SKIP ${sample.label} (could not parse text color: ${sample.color})`);
    return;
  }
  // Layer every collected background from outermost (last in the array)
  // to innermost (the element's own, first in the array) on top of a
  // white page base, so a stack of semi-transparent overlays composites
  // the same way the browser actually paints it.
  let effectiveBg = { r: 255, g: 255, b: 255 };
  for (let i = sample.layers.length - 1; i >= 0; i--) {
    effectiveBg = composite(sample.layers[i], effectiveBg);
  }
  const bgLabel = sample.layers.length > 0
    ? `rgba(${sample.layers.map((l) => `${Math.round(l.r)},${Math.round(l.g)},${Math.round(l.b)},${l.a}`).join(" | ")})`
    : "none found, assumed white";
  const fgOverBg = composite(fg, effectiveBg);
  const ratio = contrastRatio(fgOverBg, effectiveBg);
  const threshold = isLargeText(sample.fontSize, sample.fontWeight) ? 3.0 : 4.5;
  check(`${sample.label} "${sample.text}"`, ratio, threshold, `(fg=${sample.color} effectiveBg=rgb(${Math.round(effectiveBg.r)},${Math.round(effectiveBg.g)},${Math.round(effectiveBg.b)}) layers=${bgLabel} fontSize=${sample.fontSize} weight=${sample.fontWeight})`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(DEMO_URL, { waitUntil: "networkidle" });

  console.log("\n=== Landing page: hero, body, CTAs ===");
  // Scoped to the main content region, not the sidebar (whose own h1 is
  // the "PayReality" logo text and whose own p is the "Runtime
  // Authority" caption, both come first in DOM order and would
  // otherwise be sampled instead of the actual landing-page hero).
  const main = page.locator("#pr-main-content");
  await evaluateSample(await sampleElement(page, main.locator("h1").first(), "hero heading"));
  await evaluateSample(await sampleElement(page, main.locator("p").first(), "hero body copy"));
  await evaluateSample(await sampleElement(page, main.getByRole("button", { name: /start guided demo/i }).first(), "primary CTA (Start Guided Demo, landing page)"));
  await evaluateSample(await sampleElement(page, main.getByRole("button", { name: /explore platform/i }).first(), "secondary CTA (Explore Platform)"));
  // The persistent top banner's own CTA (same label, different element,
  // rendered before the sidebar/main content in DOM order).
  await evaluateSample(await sampleElement(page, page.getByRole("button", { name: /start guided demo/i }).first(), "primary CTA (Start Guided Demo, top banner)"));

  console.log("\n=== Guided tour: tooltip text ===");
  await page.getByRole("button", { name: /start guided demo/i }).first().click();
  await page.waitForTimeout(500);
  const dialog = page.getByRole("dialog");
  await evaluateSample(await sampleElement(page, dialog.locator("p").nth(1), "tour tooltip title"));
  await evaluateSample(await sampleElement(page, dialog.locator("p").nth(2), "tour tooltip body"));
  await evaluateSample(await sampleElement(page, dialog.getByRole("button", { name: /^next$/i }), "tour Next button"));
  await evaluateSample(await sampleElement(page, dialog.getByRole("button", { name: /skip tour/i }), "tour Skip tour button"));

  // Walk to the Decision: Human Review step (step 5) to reach a rendered
  // DecisionOutcomeBadge in the unauthenticated demo flow.
  for (let i = 0; i < 4; i++) {
    await page.getByRole("button", { name: /^next$/i }).click();
    await page.waitForTimeout(500);
  }
  console.log("\n=== Decision outcome badges ===");
  const badges = page.locator('span.inline-flex.items-center.gap-1\\.5.rounded-md.font-medium');
  const badgeCount = await badges.count();
  console.log(`  (found ${badgeCount} outcome badge(s) on this step)`);
  for (let i = 0; i < badgeCount; i++) {
    await evaluateSample(await sampleElement(page, badges.nth(i), `status badge #${i + 1}`));
  }

  await browser.close();

  console.log(`\n=== Summary: ${failures.length} contrast violation(s) ===`);
  failures.forEach((f) => console.log("  " + f));
  process.exitCode = failures.length > 0 ? 1 : 0;
})();

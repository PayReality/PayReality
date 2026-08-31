import { describe, expect, it } from "vitest";
import fs from "fs";
import path from "path";

// Contact & About Freshness Pass: source-level regression checks, the same
// tier as claimSafety-style tests elsewhere in this codebase. Reads the
// actual source files directly rather than rendering OrganizationSettingsPage
// (which needs an authenticated context and a mocked organization API to
// render at all) so these checks stay cheap and don't need to fake a login
// just to confirm a string is present or absent.

const DEMO_LANDING = fs.readFileSync(path.resolve(__dirname, "demo/DemoLanding.tsx"), "utf8");
const ORG_SETTINGS = fs.readFileSync(path.resolve(__dirname, "organization/OrganizationSettingsPage.tsx"), "utf8");
const HELP_CONTENT = fs.readFileSync(path.resolve(__dirname, "help/content.ts"), "utf8");
const INDEX_HTML = fs.readFileSync(path.resolve(__dirname, "..", "..", "index.html"), "utf8");

describe("canonical public contact address", () => {
  it("the demo Help panel's contact actions use the canonical address", () => {
    expect(HELP_CONTENT).toMatch(/sean@aisecurewatch\.com/);
  });

  it("Settings -> About lists the canonical support address", () => {
    expect(ORG_SETTINGS).toMatch(/sean@aisecurewatch\.com/);
  });

  it("no stale Gmail fallback address is exposed anywhere in the frontend source", () => {
    const files = [DEMO_LANDING, ORG_SETTINGS, HELP_CONTENT, INDEX_HTML];
    for (const text of files) {
      expect(text).not.toMatch(/gmail\.com/i);
    }
  });
});

describe("locked category positioning", () => {
  it("the demo landing page states the locked category", () => {
    expect(DEMO_LANDING).toMatch(/enterprise ai authority infrastructure/i);
  });

  it("Settings -> About states the locked category", () => {
    expect(ORG_SETTINGS).toMatch(/enterprise ai authority infrastructure/i);
  });

  it("Settings -> About names the three pillars", () => {
    expect(ORG_SETTINGS).toMatch(/authority intelligence/i);
    expect(ORG_SETTINGS).toMatch(/runtime authority/i);
    expect(ORG_SETTINGS).toMatch(/verifiable evidence/i);
  });

  it("Settings -> About states the company relationship", () => {
    expect(ORG_SETTINGS).toMatch(/AI Securewatch \(Pty\) Ltd/);
  });
});

describe("Settings -> About: stale deployment facts removed", () => {
  it("no longer claims Azure is staged/not live", () => {
    expect(ORG_SETTINGS).not.toMatch(/render \+ vercel/i);
    expect(ORG_SETTINGS).not.toMatch(/azure staged, not yet live/i);
  });

  it("no longer links to the pre-rename GitHub org/repo", () => {
    expect(ORG_SETTINGS).not.toMatch(/AI-Securewatch\/Pay-Reality-/);
  });
});

describe("prohibited claims absent from About/landing content", () => {
  const CHECKED = [DEMO_LANDING, ORG_SETTINGS];

  it("never claims PayReality itself executes or universally blocks downstream actions", () => {
    for (const text of CHECKED) {
      expect(text).not.toMatch(/payreality (itself )?executes/i);
      expect(text).not.toMatch(/blocks all/i);
      expect(text).not.toMatch(/non-bypassable/i);
    }
  });

  it("never claims Capability Authorization is live for the Trusted-Adapter path", () => {
    for (const text of CHECKED) {
      expect(text).not.toMatch(/capability authorization.{0,40}(adapter|trusted).{0,20}(available|live|today|shipped)/i);
    }
  });
});

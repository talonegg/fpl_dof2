import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe as group, expect, it } from "vitest";
import {
  AA_LARGE_OR_UI,
  AA_TEXT,
  auditPalette,
  contrastRatio,
  describe,
  extractPalettes,
  parseHex,
  relativeLuminance,
  TOKEN_PAIRINGS,
} from "./contrast";

// Read from disk rather than importing: the point is to check the stylesheet the browser will be
// served, and a bundler-processed import is a different artefact. Resolved against the vitest root
// (`web/`), which `vite.config.ts` fixes.
const tokensCss = readFileSync(resolve("src/tokens.css"), "utf8");
const palettes = extractPalettes(tokensCss);

group("contrast arithmetic", () => {
  it("puts black on white at 21:1 and a colour against itself at 1:1", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#3ddc97", "#3ddc97")).toBeCloseTo(1, 10);
  });

  it("is symmetric — a ratio has no foreground", () => {
    expect(contrastRatio("#101a24", "#f4f7fa")).toBeCloseTo(contrastRatio("#f4f7fa", "#101a24"), 10);
  });

  it("matches the WCAG luminance of the reference endpoints", () => {
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 10);
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 10);
    // Mid grey is well under 0.5: luminance is not linear in the channel value, and a checker that
    // got this wrong would pass most pairings and quietly wave through the marginal ones.
    expect(relativeLuminance("#808080")).toBeCloseTo(0.2159, 3);
  });

  it("rejects anything that is not a six-digit hex colour", () => {
    expect(() => parseHex("#fff")).toThrow(/six-digit/);
    expect(() => parseHex("rebeccapurple")).toThrow(/six-digit/);
  });
});

group("tokens.css", () => {
  it("defines a light and a dark palette, and a system-preference copy", () => {
    expect(Object.keys(palettes.light).length).toBeGreaterThan(20);
    expect(Object.keys(palettes.dark).length).toBeGreaterThan(20);
    expect(Object.keys(palettes.system).length).toBeGreaterThan(20);
  });

  // The dark palette is written twice — once under `prefers-color-scheme` and once under the
  // attribute — because a manual choice must win in both directions. Two copies is two chances to
  // edit one of them, and the failure is invisible to whichever theme the editor was testing in.
  it("keeps the two dark palettes identical", () => {
    for (const [token, value] of Object.entries(palettes.dark)) {
      expect(`${token}=${palettes.system[token]}`).toBe(`${token}=${value}`);
    }
    expect(Object.keys(palettes.system).sort()).toEqual(Object.keys(palettes.dark).sort());
  });

  it("gives every token in the light palette a dark value too", () => {
    // A colour defined only in one theme is right in that theme and undefined in the other, which
    // renders as whatever it inherits — usually black on black.
    for (const token of Object.keys(palettes.light)) {
      expect({ token, hasDark: token in palettes.dark }).toEqual({ token, hasDark: true });
    }
  });
});

group("WCAG AA, light theme", () => {
  for (const result of auditPalette("light", palettes.light)) {
    it(`${result.foreground} on ${result.background} — ${result.where}`, () => {
      // Asserting on the formatted string rather than the bare number so a failure names the ratio,
      // the requirement and the place it renders, instead of "expected 4.41 to be >= 4.5".
      expect(result.passes ? "meets AA" : describe(result)).toBe("meets AA");
    });
  }
});

group("WCAG AA, dark theme", () => {
  for (const result of auditPalette("dark", palettes.dark)) {
    it(`${result.foreground} on ${result.background} — ${result.where}`, () => {
      expect(result.passes ? "meets AA" : describe(result)).toBe("meets AA");
    });
  }
});

group("the audit itself", () => {
  // DP-13: the safety mechanism is tested by being shown to fail. An audit that cannot go red is
  // decoration, and every pairing above would pass equally well against a broken checker.
  it("fails a pairing that does not meet its minimum", () => {
    const results = auditPalette(
      "contrived",
      { "--fg": "#777777", "--bg": "#808080" },
      [{ foreground: "--fg", background: "--bg", minimum: AA_TEXT, where: "a contrived pairing" }],
    );
    expect(results[0].passes).toBe(false);
    expect(describe(results[0])).toMatch(/needs 4.5:1 \(a contrived pairing\)/);
  });

  it("holds a pairing to the text minimum rather than the looser UI one", () => {
    // #949494 on white is 3.03:1 — fine for a control's edge, not fine for words. A checker that
    // used one threshold everywhere would pass this as text.
    const palette = { "--fg": "#949494", "--bg": "#ffffff" };
    const asText = auditPalette("t", palette, [
      { foreground: "--fg", background: "--bg", minimum: AA_TEXT, where: "text" },
    ]);
    const asUi = auditPalette("t", palette, [
      { foreground: "--fg", background: "--bg", minimum: AA_LARGE_OR_UI, where: "ui" },
    ]);
    expect(asText[0].passes).toBe(false);
    expect(asUi[0].passes).toBe(true);
  });

  it("throws rather than skipping when a pairing names a token that does not exist", () => {
    // Silently skipping an unknown token is how a renamed colour stops being checked while the
    // suite stays green.
    expect(() =>
      auditPalette("t", { "--bg": "#ffffff" }, [
        { foreground: "--gone", background: "--bg", minimum: AA_TEXT, where: "a renamed token" },
      ]),
    ).toThrow(/no value for --gone/);
  });

  it("checks every pairing against both themes", () => {
    expect(auditPalette("light", palettes.light)).toHaveLength(TOKEN_PAIRINGS.length);
    expect(auditPalette("dark", palettes.dark)).toHaveLength(TOKEN_PAIRINGS.length);
  });
});

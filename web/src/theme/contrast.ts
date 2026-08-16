/**
 * WCAG contrast arithmetic, and the table of token pairings the app is required to meet.
 *
 * **Why this is code rather than a one-off audit.** A contrast failure is invisible in exactly the
 * way DP-13 says to test hardest against: nothing throws, no test goes red, the page looks fine to
 * whoever chose the colour, and the reader it fails is not in the room. The audit that found the two
 * defects fixed in E6-S9 — `--border` at 1.43:1 bounding the scout search box, and `--fdr-blank-fg`
 * at 4.41:1 missing AA by a hair — would find nothing on the next palette edit unless it runs every
 * time. So the pairing table lives here and `contrast.test.ts` fails the build on a regression.
 *
 * **Both themes, always.** Every pairing is checked against the light palette and the dark one. A
 * colour is only ever right in one theme by accident, which is the same reasoning that put every
 * token in `tokens.css` with two values in the first place.
 *
 * Ratios follow WCAG 2.1 §1.4.3 (contrast minimum) and §1.4.11 (non-text contrast).
 */

/** AA for body text. */
export const AA_TEXT = 4.5;
/** AA for large text, and for the visual boundary of a user-interface component (§1.4.11). */
export const AA_LARGE_OR_UI = 3;

/** `#rrggbb` to its three channels. Throws rather than guessing — a malformed token is a defect. */
export function parseHex(hex: string): [number, number, number] {
  const match = /^#([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!match) throw new Error(`Not a six-digit hex colour: ${hex}`);
  const value = match[1];
  return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16)) as [number, number, number];
}

/** Relative luminance, per WCAG 2.1. */
export function relativeLuminance(hex: string): number {
  const linear = parseHex(hex).map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** Contrast ratio between two colours, from 1 (identical) to 21 (black on white). Order-free. */
export function contrastRatio(a: string, b: string): number {
  const [lighter, darker] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Pull the light and dark palettes out of `tokens.css`.
 *
 * The light palette is the bare `:root` block and the dark one is the `[data-theme="dark"]` block.
 * The `prefers-color-scheme` block is deliberately not read: it is required to be a copy of the
 * attribute block, and `tokensAgree` is what checks that rather than this.
 */
export function extractPalettes(css: string): { light: Palette; dark: Palette; system: Palette } {
  const readBlock = (pattern: RegExp): Palette => {
    const found = pattern.exec(css);
    if (!found) throw new Error(`No block in tokens.css matching ${String(pattern)}`);
    const palette: Palette = {};
    for (const [, name, value] of found[1].matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
      palette[name] = value;
    }
    return palette;
  };
  return {
    light: readBlock(/^:root \{([\s\S]*?)\n\}/m),
    dark: readBlock(/^:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/m),
    system: readBlock(/:root:not\(\[data-theme="light"\]\) \{([\s\S]*?)\n {2}\}/),
  };
}

export type Palette = Record<string, string>;

export interface Pairing {
  /** The token painted in front. */
  foreground: string;
  /** The token painted behind it. */
  background: string;
  /** The ratio this pairing must clear. */
  minimum: number;
  /** Where in the app the two actually meet. A pairing nothing renders is not worth enforcing. */
  where: string;
}

/**
 * Every foreground/background pair the app actually renders, and the ratio it owes.
 *
 * Each entry names a real site. The temptation is to enumerate the cross product of every token,
 * which produces a table full of combinations nothing draws and buries the ones that matter; a
 * pairing earns its place by being something a reader sees.
 */
export const TOKEN_PAIRINGS: readonly Pairing[] = [
  // --- body text on the three surfaces ---
  { foreground: "--text", background: "--bg", minimum: AA_TEXT, where: "page text" },
  { foreground: "--text", background: "--bg-panel", minimum: AA_TEXT, where: "panel text" },
  { foreground: "--text", background: "--bg-panel-alt", minimum: AA_TEXT, where: "table stripes, chips" },
  { foreground: "--text", background: "--nav-bg", minimum: AA_TEXT, where: "nav labels" },
  { foreground: "--text", background: "--nav-active-bg", minimum: AA_TEXT, where: "the active nav link" },
  { foreground: "--text", background: "--row-selected-bg", minimum: AA_TEXT, where: "the selected scout row" },

  // --- secondary text. The most common real failure: muted is chosen against white and then used
  //     on a tinted panel, where it has less room than it looks like it has. ---
  { foreground: "--text-muted", background: "--bg", minimum: AA_TEXT, where: "captions" },
  { foreground: "--text-muted", background: "--bg-panel", minimum: AA_TEXT, where: "chart summaries, readouts" },
  { foreground: "--text-muted", background: "--bg-panel-alt", minimum: AA_TEXT, where: "secondary cells" },
  { foreground: "--text-muted", background: "--nav-bg", minimum: AA_TEXT, where: "inactive nav links" },

  // --- emphasis and alerts ---
  { foreground: "--on-accent", background: "--accent", minimum: AA_TEXT, where: "primary buttons, active filters" },
  { foreground: "--accent", background: "--bg-panel", minimum: AA_TEXT, where: "accent text on a panel" },
  { foreground: "--accent", background: "--bg", minimum: AA_TEXT, where: "accent text on the page" },
  { foreground: "--text", background: "--warn-bg", minimum: AA_TEXT, where: "warning alert text" },
  { foreground: "--text", background: "--danger-bg", minimum: AA_TEXT, where: "danger alert text" },
  { foreground: "--warn-border", background: "--warn-bg", minimum: AA_LARGE_OR_UI, where: "warning alert edge" },
  { foreground: "--danger-border", background: "--danger-bg", minimum: AA_LARGE_OR_UI, where: "danger alert edge" },
  { foreground: "--value-positive", background: "--bg-panel", minimum: AA_TEXT, where: "a price rise" },
  { foreground: "--value-negative", background: "--bg-panel", minimum: AA_TEXT, where: "a price fall" },
  { foreground: "--value-positive", background: "--bg-panel-alt", minimum: AA_TEXT, where: "a price rise in a table" },
  { foreground: "--value-negative", background: "--bg-panel-alt", minimum: AA_TEXT, where: "a price fall in a table" },
  { foreground: "--badge-vice-fg", background: "--badge-vice-bg", minimum: AA_TEXT, where: "the vice-captain badge" },

  // --- confidence badges. These are the DP-09 surface: if the badge saying how sure the model is
  //     cannot be read, the uncertainty may as well not be published. ---
  { foreground: "--confidence-high-fg", background: "--confidence-high-bg", minimum: AA_TEXT, where: "high-confidence badge" },
  { foreground: "--confidence-medium-fg", background: "--confidence-medium-bg", minimum: AA_TEXT, where: "medium-confidence badge" },
  { foreground: "--confidence-low-fg", background: "--confidence-low-bg", minimum: AA_TEXT, where: "low-confidence badge" },
  { foreground: "--confidence-none-fg", background: "--confidence-none-bg", minimum: AA_TEXT, where: "unquantified badge" },

  // --- the fixture grid. Every cell carries its score and band name as text (E6-S8), so the text
  //     is the carrier of the meaning and owes the full text ratio, not the UI one. ---
  { foreground: "--fdr-1-fg", background: "--fdr-1-bg", minimum: AA_TEXT, where: "easiest fixture cell" },
  { foreground: "--fdr-2-fg", background: "--fdr-2-bg", minimum: AA_TEXT, where: "easy fixture cell" },
  { foreground: "--fdr-3-fg", background: "--fdr-3-bg", minimum: AA_TEXT, where: "neutral fixture cell" },
  { foreground: "--fdr-4-fg", background: "--fdr-4-bg", minimum: AA_TEXT, where: "hard fixture cell" },
  { foreground: "--fdr-5-fg", background: "--fdr-5-bg", minimum: AA_TEXT, where: "hardest fixture cell" },
  { foreground: "--fdr-blank-fg", background: "--fdr-blank-bg", minimum: AA_TEXT, where: "a blank gameweek cell" },

  // --- user-interface components (§1.4.11), which owe 3:1 and not 4.5:1 ---
  { foreground: "--focus-ring", background: "--bg", minimum: AA_LARGE_OR_UI, where: "focus outline on the page" },
  { foreground: "--focus-ring", background: "--bg-panel", minimum: AA_LARGE_OR_UI, where: "focus outline on a panel" },
  { foreground: "--focus-ring", background: "--bg-panel-alt", minimum: AA_LARGE_OR_UI, where: "focus outline on a chip" },
  { foreground: "--border-strong", background: "--bg", minimum: AA_LARGE_OR_UI, where: "a control's edge on the page" },
  { foreground: "--border-strong", background: "--bg-panel", minimum: AA_LARGE_OR_UI, where: "a control's edge on a panel" },
  { foreground: "--border-strong", background: "--bg-panel-alt", minimum: AA_LARGE_OR_UI, where: "a button's edge" },
];

export interface PairingResult extends Pairing {
  theme: string;
  ratio: number;
  passes: boolean;
}

/** Score every pairing against one palette. */
export function auditPalette(
  theme: string,
  palette: Palette,
  pairings: readonly Pairing[] = TOKEN_PAIRINGS,
): PairingResult[] {
  return pairings.map((pairing) => {
    const foreground = palette[pairing.foreground];
    const background = palette[pairing.background];
    if (!foreground || !background) {
      throw new Error(
        `${theme}: tokens.css defines no value for ${foreground ? pairing.background : pairing.foreground}`,
      );
    }
    const ratio = contrastRatio(foreground, background);
    return { ...pairing, theme, ratio, passes: ratio >= pairing.minimum };
  });
}

/** Format a result for a failure message that says what to change, not merely that something failed. */
export function describe(result: PairingResult): string {
  return (
    `${result.theme}: ${result.foreground} on ${result.background} is ${result.ratio.toFixed(2)}:1, ` +
    `needs ${result.minimum}:1 (${result.where})`
  );
}

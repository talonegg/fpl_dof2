/**
 * The data layer imports no component (WEB-04, 03 §12 W6). There is no eslint here, so the rule is a
 * scan: every import in `web/src/data/` is read, and one reaching `components/` fails.
 */

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const DATA = import.meta.dirname;
const IMPORT = /(?:import|export)\s[^;]*?from\s+["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)/g;

function componentImports(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((name) => /\.tsx?$/.test(name) && name !== "layering.test.ts")
    .flatMap((name) =>
      [...readFileSync(resolve(dir, name), "utf8").matchAll(IMPORT)]
        .map((m) => m[1] ?? m[2])
        .filter((spec) => /(^|\/)components\//.test(spec))
        .map((spec) => `${name}: ${spec}`),
    );
}

describe("the data layer", () => {
  it("imports nothing from web/src/components/", () => {
    expect(componentImports(DATA)).toEqual([]);
  });

  it("would catch one that did", () => {
    // The scan must see the shapes the codebase uses, or the test above passes vacuously.
    const sample = 'import { x } from "../components/squad/effective";\nimport type { Y } from "./store";';
    expect([...sample.matchAll(IMPORT)].map((m) => m[1])).toEqual(["../components/squad/effective", "./store"]);
  });
});

/**
 * The TypeScript half of the lineup conformance test (WEB-04, owner answer Q2): `chooseLineup` and
 * `squad/selection.py` read the same `contracts/conformance/lineup-corpus.json` (DL-39), and the
 * ruleset is named from the legality corpus. Read with `node:fs` so neither file reaches the bundle.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Rules } from "../../contract/types";
import { rules as publishedRules } from "../../test/fixtures";
import { POSITIONS, type Position } from "./legality";
import { chooseLineup, type LineupCandidate } from "./lineup";

type Spec = Omit<LineupCandidate, "player_id">;

interface Corpus {
  player_pool: Record<string, Spec>;
  cases: Array<{
    name: string;
    why: string;
    rules: string;
    player_overrides: Record<string, Partial<Spec>>;
    expected: { starting: number[]; bench_order: number[]; captain: number; vice_captain: number; formation: string };
  }>;
}

const conformance = resolve(import.meta.dirname, "../../../../contracts/conformance");
const read = <T,>(name: string): T => JSON.parse(readFileSync(resolve(conformance, name), "utf8")) as T;
const corpus = read<Corpus>("lineup-corpus.json");
const rulesets = read<{ rulesets: Record<string, Rules["squad"] & { $comment?: string }> }>("legality-corpus.json").rulesets;

describe("chooseLineup agrees with the Python selector, case by case", () => {
  it("loads, and names every case exactly once", () => {
    const names = corpus.cases.map((c) => c.name);
    expect(names.length).toBeGreaterThanOrEqual(5);
    expect(new Set(names).size).toBe(names.length);
  });

  for (const testCase of corpus.cases) {
    it(`${testCase.name} — ${testCase.why}`, () => {
      const { $comment: _, ...squad } = rulesets[testCase.rules];
      const players = Object.entries(corpus.player_pool).map(([id, spec]) => ({
        player_id: Number(id),
        ...spec,
        ...(testCase.player_overrides[id] ?? {}),
      }));
      const lineup = chooseLineup(players, { ...publishedRules, squad });
      expect(lineup).not.toBeNull();
      if (!lineup) return;
      expect({
        starting: [...lineup.starting].sort((a, b) => a - b),
        bench_order: lineup.bench_order,
        captain: lineup.captain,
        vice_captain: lineup.vice_captain,
        formation: POSITIONS.map((p: Position) => lineup.formation[p]).join("-"),
      }).toEqual(testCase.expected);
    });
  }
});

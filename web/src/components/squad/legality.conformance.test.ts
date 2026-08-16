/**
 * The TypeScript half of the cross-language legality conformance test.
 *
 * `legality.ts` is a mirror of `pipeline/src/fpl_dof/rules/legality.py`, and a mirror is worth
 * exactly as much as the thing that keeps it aligned. `legality.test.ts` proves this implementation
 * is internally consistent and reads its rules rather than knowing them; it cannot prove the two
 * implementations *agree*, because it never asks the other one.
 *
 * This does. `contracts/conformance/legality-corpus.json` holds the rulesets, the squads and the
 * exact ordered list of `(code, detail)` pairs each squad must produce, and
 * `pipeline/tests/test_legality_conformance.py` asserts against the same file. One file, two
 * readers — a corpus copied into two test directories would catch nothing, which is the entire
 * reason it lives outside both `pipeline/` and `web/`.
 *
 * `message` is deliberately not asserted: it is prose for a reader, and each language phrases it for
 * its own audience.
 *
 * Read with `node:fs` rather than imported. The corpus sits outside this project's `tsconfig`
 * include and outside Vite's root, and a build-time JSON import would drag it into the client bundle
 * for no reason; a test-time read keeps it firmly on the test side of the line.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Rules } from "../../contract/types";
import { validateSquad, type Position, type SquadMember, type ViolationCode } from "./legality";
import { rules as publishedRules } from "../../test/fixtures";

interface PlayerSpec {
  position: Position;
  team_id: number;
  price: number;
}

interface CorpusCase {
  name: string;
  why: string;
  rules: string;
  budget?: number;
  squad: {
    players: number[];
    player_defaults?: Partial<PlayerSpec>;
    player_overrides?: Record<string, Partial<PlayerSpec>>;
    starting?: number[];
    captain?: number;
    vice_captain?: number;
    bench_order?: number[];
  };
  expected: Array<{ code: ViolationCode; detail: Record<string, unknown> }>;
}

interface Corpus {
  corpus_version: number;
  rulesets: Record<string, Rules["squad"] & { $comment?: string }>;
  player_pool: Record<string, PlayerSpec>;
  cases: CorpusCase[];
}

const CORPUS_PATH = resolve(
  import.meta.dirname,
  "../../../../contracts/conformance/legality-corpus.json",
);

const corpus: Corpus = JSON.parse(readFileSync(CORPUS_PATH, "utf8")) as Corpus;

/**
 * The named ruleset, dropped into the published contract's rules object.
 *
 * Only the squad rules vary — scoring and transfers have no bearing on legality — so the rest comes
 * from the shared contract fixture rather than being invented here.
 */
function rulesFor(testCase: CorpusCase): Rules {
  const ruleset = { ...corpus.rulesets[testCase.rules] };
  delete ruleset.$comment;
  return { ...publishedRules, squad: ruleset };
}

/**
 * A member is the pool entry, then `player_defaults`, then `player_overrides`, in that order.
 *
 * The same three lines exist in the Python reader. It is the only logic the two sides share, and it
 * is small enough to be obviously the same in both.
 */
function buildMembers(testCase: CorpusCase): SquadMember[] {
  const { players, player_defaults: defaults = {}, player_overrides: overrides = {} } = testCase.squad;
  return players.map((playerId) => {
    const attributes = {
      ...corpus.player_pool[String(playerId)],
      ...defaults,
      ...(overrides[String(playerId)] ?? {}),
    };
    return { player_id: playerId, ...attributes };
  });
}

describe("the shared legality corpus", () => {
  it("loads, and names every case exactly once", () => {
    // A corpus that silently failed to load would make every case below vacuously pass.
    const names = corpus.cases.map((testCase) => testCase.name);
    expect(names.length).toBeGreaterThanOrEqual(20);
    expect(new Set(names).size).toBe(names.length);
  });

  it("covers every violation code the validator can emit", () => {
    // Written out rather than derived, because TypeScript's union type does not survive to runtime.
    // The Python half asserts the same set against its enum, so a new code fails there too.
    const codes: ViolationCode[] = [
      "squad_size",
      "duplicate_player",
      "composition",
      "budget",
      "club_limit",
      "starting_size",
      "starter_not_in_squad",
      "formation",
      "captain_not_starting",
      "vice_not_starting",
      "captain_is_vice",
      "bench_order",
    ];
    const covered = new Set(
      corpus.cases.flatMap((testCase) => testCase.expected.map((violation) => violation.code)),
    );
    expect([...covered].sort()).toEqual([...codes].sort());
  });
});

describe("validateSquad agrees with the Python validator, case by case", () => {
  for (const testCase of corpus.cases) {
    it(`${testCase.name} — ${testCase.why}`, () => {
      const violations = validateSquad(
        {
          players: buildMembers(testCase),
          starting: testCase.squad.starting,
          captain: testCase.squad.captain,
          vice_captain: testCase.squad.vice_captain,
          bench_order: testCase.squad.bench_order,
        },
        rulesFor(testCase),
        testCase.budget === undefined ? {} : { budget: testCase.budget },
      );

      const actual = violations.map((violation) => ({
        code: violation.code,
        detail: violation.detail,
      }));
      expect(actual).toEqual(testCase.expected);
    });
  }
});

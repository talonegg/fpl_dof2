/**
 * The draft and its derived state.
 *
 * The property under test throughout is that legality is *derived*, never remembered: every edit
 * recomputes the violations from the draft as it now stands, so there is no path where the panel and
 * the squad disagree.
 */

import { describe, expect, it } from "vitest";
import {
  addToDraft,
  autoLineup,
  draftFromSquad,
  indexPlayers,
  removeFromDraft,
  replaceInDraft,
  resolveDraft,
  shortfall,
  toggleStarter,
} from "./draft";
import { builtSquad, LEGAL_IDS, LEGAL_XI, pool, rules } from "./testFixtures";

const index = indexPlayers(pool, builtSquad);
const budget = rules.squad.budget;
const start = draftFromSquad(builtSquad);

describe("draftFromSquad", () => {
  it("starts from the published squad and its published XI", () => {
    expect(start.memberIds).toEqual(LEGAL_IDS);
    expect([...start.starting].sort()).toEqual([...LEGAL_XI].sort());
  });

  it("resolves to a legal squad with no violations", () => {
    expect(resolveDraft(start, index, rules, budget).violations).toEqual([]);
  });
});

describe("indexPlayers", () => {
  it("knows every player in the pool", () => {
    expect(index.size).toBeGreaterThanOrEqual(pool.length);
    expect(index.get(pool[0].id)?.in_pool).toBe(true);
  });

  it("still indexes a squad member the pool has dropped, flagged as outside it", () => {
    const orphaned = { ...builtSquad, players: [{ ...builtSquad.players[0], player_id: 9999 }] };
    const withOrphan = indexPlayers(pool, orphaned);
    expect(withOrphan.get(9999)?.in_pool).toBe(false);
  });
});

describe("editing the draft", () => {
  it("removing a player produces a composition and squad-size violation immediately", () => {
    const edited = removeFromDraft(start, 202);
    const resolved = resolveDraft(edited, index, rules, budget);
    const codes = resolved.violations.map((v) => v.code);
    expect(codes).toContain("squad_size");
    expect(codes).toContain("composition");
    expect(resolved.members.map((m) => m.player_id)).not.toContain(202);
  });

  it("removing a starter also removes them from the XI", () => {
    const edited = removeFromDraft(start, LEGAL_XI[0]);
    expect(edited.starting).not.toContain(LEGAL_XI[0]);
  });

  it("adding the same player twice is a no-op rather than a duplicate", () => {
    const once = addToDraft(removeFromDraft(start, 202), 207);
    const twice = addToDraft(once, 207);
    expect(twice.memberIds).toEqual(once.memberIds);

    // 202 was a starter, so the XI is one short until it is re-picked — that is the only thing left
    // to complain about, and in particular there is no duplicate.
    const codes = resolveDraft(twice, index, rules, budget).violations.map((v) => v.code);
    expect(codes).not.toContain("duplicate_player");
    expect(codes).toEqual(["starting_size"]);
    expect(resolveDraft(autoLineup(twice, index, rules), index, rules, budget).violations).toEqual([]);
  });

  it("replacing keeps the outgoing player's place in the XI", () => {
    const edited = replaceInDraft(start, LEGAL_XI[1], 207);
    expect(edited.memberIds).toContain(207);
    expect(edited.memberIds).not.toContain(LEGAL_XI[1]);
    expect(edited.starting).toContain(207);
    expect(edited.starting).toHaveLength(start.starting.length);
  });

  it("flags a replacement that breaks the budget, and only then", () => {
    const dear = { ...index.get(207)!, price: 60 };
    const richIndex = new Map(index).set(207, dear);
    const edited = replaceInDraft(start, 202, 207);
    expect(resolveDraft(edited, index, rules, budget).violations).toEqual([]);
    expect(
      resolveDraft(edited, richIndex, rules, budget).violations.map((v) => v.code),
    ).toContain("budget");
  });

  it("flags a replacement that breaks the club limit", () => {
    // Club 1 already holds 100 and 300; two more defenders from it takes the count to four.
    const sameClub = pool.filter((p) => p.position === "DEF" && p.team_id === 1).map((p) => p.id);
    let edited = replaceInDraft(start, 202, sameClub[0]);
    edited = replaceInDraft(edited, 203, sameClub[1]);
    edited = replaceInDraft(edited, 204, sameClub[2]);
    const codes = resolveDraft(edited, index, rules, budget).violations.map((v) => v.code);
    expect(codes).toContain("club_limit");
  });

  it("reports ids that are in the draft but in no published data", () => {
    const stale = { ...start, memberIds: [...start.memberIds, 123456] };
    expect(resolveDraft(stale, index, rules, budget).unknownIds).toEqual([123456]);
  });
});

describe("starting and benching", () => {
  it("benching a starter breaks the starting size, live", () => {
    const edited = toggleStarter(start, LEGAL_XI[0]);
    const codes = resolveDraft(edited, index, rules, budget).violations.map((v) => v.code);
    expect(codes).toContain("starting_size");
  });

  it("lets the reader build an illegal shape rather than silently refusing the click", () => {
    // Both forwards benched, a fifth defender and a fifth midfielder in: still eleven starters, but
    // no forward at all. The clicks must all work and the panel must say what is wrong — a control
    // that quietly does nothing is far more confusing than a violation a reader can read.
    let edited = toggleStarter(start, 403);
    edited = toggleStarter(edited, 404);
    edited = toggleStarter(edited, 206);
    edited = toggleStarter(edited, 306);

    const resolved = resolveDraft(edited, index, rules, budget);
    expect(resolved.starting).toHaveLength(rules.squad.starting_size);
    const formation = resolved.violations.filter((v) => v.code === "formation");
    expect(formation.map((v) => v.detail.position)).toEqual(["FWD"]);
    expect(formation[0].detail).toMatchObject({
      actual: 0,
      min: rules.squad.formation_min.FWD,
      max: rules.squad.formation_max.FWD,
    });
  });

  it("derives the armbands from the two best-forecast starters", () => {
    const resolved = resolveDraft(start, index, rules, budget);
    const ranked = resolved.starters.sort(
      (a, b) => b.xp_next - a.xp_next || a.player_id - b.player_id,
    );
    expect(resolved.captain).toBe(ranked[0].player_id);
    expect(resolved.vice_captain).toBe(ranked[1].player_id);
  });

  it("keeps the reserve goalkeeper out of the bench order", () => {
    const resolved = resolveDraft(start, index, rules, budget);
    expect(resolved.bench_order).not.toContain(101);
    expect(resolved.bench[0].position).toBe("GKP");
  });

  it("autoLineup restores a legal XI from a broken one", () => {
    const broken = { ...start, starting: [] };
    expect(resolveDraft(broken, index, rules, budget).violations).toEqual([]);
    const fixed = autoLineup({ ...start, starting: LEGAL_XI.slice(0, 5) }, index, rules);
    expect(resolveDraft(fixed, index, rules, budget).violations).toEqual([]);
    expect(fixed.starting).toHaveLength(rules.squad.starting_size);
  });

  it("autoLineup leaves an unfillable squad alone rather than inventing an XI", () => {
    const tooFew = { memberIds: LEGAL_IDS.slice(0, 3), starting: [] };
    expect(autoLineup(tooFew, index, rules)).toEqual(tooFew);
  });
});

describe("shortfall", () => {
  it("is zero everywhere for a complete squad", () => {
    expect(shortfall(start, index, rules)).toEqual({ GKP: 0, DEF: 0, MID: 0, FWD: 0 });
  });

  it("counts what is missing per position", () => {
    const edited = removeFromDraft(removeFromDraft(start, 202), 203);
    expect(shortfall(edited, index, rules)).toEqual({ GKP: 0, DEF: 2, MID: 0, FWD: 0 });
  });

  it("goes negative when a position is over-filled", () => {
    const edited = addToDraft(start, 406);
    expect(shortfall(edited, index, rules).FWD).toBe(-1);
  });

  it("reads the composition from the rules rather than assuming one", () => {
    const sixDefenders = {
      ...rules,
      squad: { ...rules.squad, composition: { ...rules.squad.composition, DEF: 6 } },
    };
    expect(shortfall(start, index, sixDefenders).DEF).toBe(1);
  });
});

describe("the budget is whatever it is told", () => {
  it("uses the figure passed in, not the rules' opening budget", () => {
    const spend = resolveDraft(start, index, rules, budget).totalPrice;
    expect(resolveDraft(start, index, rules, spend).violations).toEqual([]);
    expect(
      resolveDraft(start, index, rules, spend - 0.1).violations.map((v) => v.code),
    ).toContain("budget");
  });

  it("reports what is left, negative when over", () => {
    const resolved = resolveDraft(start, index, rules, 50);
    expect(resolved.remaining).toBeLessThan(0);
  });
});

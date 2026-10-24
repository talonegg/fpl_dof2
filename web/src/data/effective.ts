import type { Players, Squad, Week } from "../contract/types";

/**
 * The squad the app should show, given that the from-scratch solve is skipped in-season (DL-67).
 *
 * Preseason `squad.json` is the pipeline's solved fifteen and is used as published. In-season the
 * solve does not run — the decision is the transfer plan — so `squad.json` arrives with
 * `skipped: true` and no players. Rather than leave the pitch, the builder and the "In squad"
 * badge empty, the app starts from **this week's advised squad**: the fifteen `week.advised`
 * names after the recommended transfers, with the advised XI, captain and bench order, and each
 * player's forecast looked up from `players.json`. That is what every consumer of `squad.json`
 * actually wants in-season, and it was what the E13-S2 badge was documented as meaning.
 *
 * Nothing is fetched and nothing is recomputed: every number here was published by the pipeline
 * (Invariant 8, DP-09). The result carries `source: "week_advice"` so a view can say where it
 * came from rather than presenting it as a solve.
 *
 * When the solve is skipped *and* there is no advice (preseason before a squad is declared, or a
 * skipped week), the skipped squad is returned as published, with its empty players list — an
 * honest nothing rather than an invented fifteen (DP-15).
 */
export function effectiveSquad(squad: Squad, week: Week | null, players: Players): Squad {
  if (!squad.skipped && squad.status !== "skipped") return squad;
  const advised = week && !week.skipped ? week.advised : undefined;
  if (!advised || advised.squad.length === 0) return squad;
  return fromLineup(squad, advised, players);
}

/**
 * The owner's team as it stands, before any advice is taken (Home, WEB-08). In-season it is the
 * advised fifteen with the recommended moves undone — the squad the pipeline read; preseason, the
 * squad as published. The XI and armband are the ones last played (`week.reconciliation`) when that
 * was these fifteen, and none otherwise: the owner's next lineup is not published, and the advised
 * one is the model's, not the owner's.
 */
export function currentSquad(squad: Squad, week: Week | null, players: Players): Squad {
  if (!squad.skipped && squad.status !== "skipped") return squad;
  const advised = week && !week.skipped ? week.advised : undefined;
  if (!week || !advised || advised.squad.length === 0) return squad;
  const back = new Map((week.recommendation?.moves ?? []).map((m) => [m.in.player_id, m.out.player_id]));
  const ids = advised.squad.map((id) => back.get(id) ?? id);
  // `played` is an untyped record in the contract: read only what has the expected shape.
  const played = (week.reconciliation?.played ?? {}) as { squad?: unknown; starting?: unknown; captain?: unknown };
  const playedSquad = Array.isArray(played.squad) ? (played.squad as unknown[]) : [];
  const same = playedSquad.length === ids.length && ids.every((id) => playedSquad.includes(id));
  return fromLineup(
    squad,
    {
      squad: ids,
      starting: same && Array.isArray(played.starting) ? (played.starting as number[]) : [],
      captain: same && typeof played.captain === "number" ? played.captain : null,
      vice_captain: null,
    },
    players,
  );
}

interface Lineup {
  squad: number[];
  starting: number[];
  captain: number | null;
  vice_captain: number | null;
  bench_order?: number[];
  expected_points?: number;
}

/** These ids as squad members, each with the published player's numbers; nothing is recomputed. */
function fromLineup(squad: Squad, advised: Lineup, players: Players): Squad {
  const byId = new Map(players.players.map((player) => [player.id, player]));
  const starting = new Set(advised.starting);
  const members: Squad["players"] = [];
  for (const id of advised.squad) {
    const player = byId.get(id);
    if (!player) continue;
    members.push({
      player_id: player.id,
      web_name: player.name,
      position: player.position,
      team: player.team,
      team_id: player.team_id,
      price: player.price,
      xp_next: player.xp_next,
      xp_next_sd: player.xp_next_sd,
      xp_horizon: player.xp_horizon,
      xp_horizon_sd: player.xp_horizon_sd,
      start_probability: player.start_probability,
      confidence: player.confidence,
      starting: starting.has(player.id),
      is_captain: player.id === advised.captain,
      is_vice_captain: player.id === advised.vice_captain,
      components: Object.fromEntries(Object.entries(player.components)),
    });
  }
  if (members.length === 0) return squad;

  const formation: Squad["formation"] = {};
  for (const member of members) {
    if (member.starting) formation[member.position] = (formation[member.position] ?? 0) + 1;
  }

  return {
    ...squad,
    status: "optimal",
    source: "week_advice",
    objective: advised.expected_points ?? 0,
    total_price: Number(members.reduce((sum, member) => sum + member.price, 0).toFixed(1)),
    formation,
    captain_id: advised.captain,
    vice_captain_id: advised.vice_captain,
    bench_order: advised.bench_order ?? [],
    players: members,
  };
}

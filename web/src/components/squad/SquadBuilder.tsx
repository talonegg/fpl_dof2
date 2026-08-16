import { useCallback, useMemo, useState } from "react";
import type { Player, Rules, Squad, Week } from "../../contract/types";
import { formatPrice, formatXp, formatXpRange } from "../../format";
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
  type BuilderPlayer,
  type SquadDraft,
} from "./draft";
import { POSITIONS, type Position } from "./legality";
import { useSquadMarks } from "./locks";
import { reoptimise, type ReoptimiseResult } from "./reoptimise";

/**
 * The squad builder (E6-S7, FR-31): edit the fifteen, see the rules bite as you do it.
 *
 * Three things about it are obligations rather than choices.
 *
 * **Every legality check reads `rules.json`.** Squad size, composition, budget, club limit and the
 * formation bounds are all in `legality.ts`, parameterised from the published rules and nowhere
 * restated (DL-14, Invariant 9). This file names no rule value either — where it needs to say "15"
 * or "3" to a reader it asks `rules.squad`.
 *
 * **The re-optimiser says what it is.** It is a greedy build plus a hill-climb, not the MILP that
 * produced the published squad, and the panel says so next to the button rather than in a comment.
 * A fallback presented as a full solve is the failure DP-15 names.
 *
 * **Prices are current prices, and the page says so.** The published contract carries no per-player
 * purchase price, so the browser cannot compute what an individual player would raise under the
 * sell-on fee. What it can do is spend against `week.squad_state.budget`, which is sell value plus
 * bank and already has the fee netted off in aggregate — so budget legality is real, while the
 * arithmetic of any *single* sale is approximate. That distinction is on the page, because a budget
 * bar that is quietly wrong by £0.2m is worse than one that admits it.
 */
export function SquadBuilder({
  players,
  squad,
  rules,
  week,
}: {
  players: readonly Player[];
  squad: Squad;
  rules: Rules;
  week: Week | null;
}) {
  const index = useMemo(() => indexPlayers(players, squad), [players, squad]);
  const [draft, setDraft] = useState<SquadDraft>(() => draftFromSquad(squad));
  const [replacing, setReplacing] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [pickerPosition, setPickerPosition] = useState<Position | "ALL">("ALL");
  const [lastRun, setLastRun] = useState<ReoptimiseResult | null>(null);
  const marks = useSquadMarks();

  /**
   * What there is to spend. `week.squad_state.budget` is squad value plus bank once a season is
   * under way; before that there is no squad state and the opening budget from the rules is the
   * honest figure. Never a literal.
   */
  const budget = week?.squad_state?.budget ?? squad.budget ?? rules.squad.budget;

  const resolved = useMemo(
    () => resolveDraft(draft, index, rules, budget),
    [draft, index, rules, budget],
  );
  const needed = useMemo(() => shortfall(draft, index, rules), [draft, index, rules]);
  const selected = useMemo(() => new Set(draft.memberIds), [draft.memberIds]);

  const legal = resolved.violations.length === 0;

  const candidates = useMemo(() => {
    const query = search.trim().toLowerCase();
    const wantedPosition =
      replacing !== null ? (index.get(replacing)?.position ?? null) : null;

    return players
      .filter((player) => !selected.has(player.id))
      .filter((player) => !marks.isBanned(player.id))
      // Replacing pins the picker to the outgoing player's position — a swap that changes the
      // composition is never the move the reader meant. Otherwise the filter is theirs to set.
      .filter((player) => {
        if (wantedPosition) return player.position === wantedPosition;
        return pickerPosition === "ALL" || player.position === pickerPosition;
      })
      .filter((player) =>
        query === ""
          ? true
          : player.name.toLowerCase().includes(query) ||
            (player.full_name ?? "").toLowerCase().includes(query) ||
            player.team.toLowerCase().includes(query),
      )
      .sort((a, b) => b.xp_horizon - a.xp_horizon || a.id - b.id)
      .slice(0, CANDIDATE_ROWS);
  }, [players, selected, marks, replacing, index, pickerPosition, search]);

  const add = useCallback(
    (id: number) => {
      setDraft((current) =>
        replacing === null ? addToDraft(current, id) : replaceInDraft(current, replacing, id),
      );
      setReplacing(null);
      setSearch("");
    },
    [replacing],
  );

  const runReoptimise = useCallback(() => {
    const result = reoptimise({
      pool: players,
      rules,
      budget,
      locked: marks.locked,
      banned: marks.banned,
    });
    setLastRun(result);
    if (result.status === "heuristic") {
      setDraft({
        memberIds: result.members.map((member) => member.player_id),
        starting: result.lineup?.starting ?? [],
      });
    }
  }, [players, rules, budget, marks.locked, marks.banned]);

  const reset = useCallback(() => {
    setDraft(draftFromSquad(squad));
    setLastRun(null);
    setReplacing(null);
  }, [squad]);

  return (
    <section className="builder" data-testid="squad-builder" aria-labelledby="builder-heading">
      <h2 id="builder-heading">Squad builder</h2>

      <div className="builder-summary" data-testid="builder-summary">
        <div>
          <span className="builder-figure">
            {resolved.members.length} / {rules.squad.size}
          </span>
          <span className="builder-label">players</span>
        </div>
        <div>
          <span className="builder-figure">{formatPrice(resolved.totalPrice)}</span>
          <span className="builder-label">of {formatPrice(budget)}</span>
        </div>
        <div>
          <span
            className={
              resolved.remaining < 0 ? "builder-figure builder-over" : "builder-figure"
            }
          >
            {formatPrice(resolved.remaining)}
          </span>
          <span className="builder-label">remaining</span>
        </div>
        <div>
          <span className="builder-figure">
            {POSITIONS.map((position) => resolved.formation[position]).join("-")}
          </span>
          <span className="builder-label">
            {resolved.starting.length} / {rules.squad.starting_size} starting
          </span>
        </div>
      </div>

      <p className="builder-basis" data-testid="builder-basis">
        Valued at current prices against{" "}
        {week?.squad_state
          ? "your squad's sell value plus bank, as published"
          : "the opening budget from the published rules"}
        . The sell-on fee is already netted off that total; what any single sale raises is not
        published per player, so a one-for-one swap here is approximate to within the fee on that
        player's rise.
      </p>

      {legal ? (
        <p className="builder-legal" data-testid="builder-legal" role="status">
          This squad is legal under the published rules.
        </p>
      ) : (
        <div className="builder-violations" data-testid="builder-violations" role="status">
          <h3>What the rules say</h3>
          <ul>
            {resolved.violations.map((violation, order) => (
              <li key={`${violation.code}-${order}`} data-violation={violation.code}>
                {violation.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="builder-actions">
        <button type="button" onClick={runReoptimise} data-testid="builder-reoptimise">
          Re-optimise around my locks
        </button>
        <button
          type="button"
          onClick={() => setDraft((current) => autoLineup(current, index, rules))}
          data-testid="builder-auto-xi"
        >
          Pick the best legal XI
        </button>
        <button type="button" onClick={reset} data-testid="builder-reset">
          Back to the published squad
        </button>
        {(marks.locked.length > 0 || marks.banned.length > 0) && (
          <button type="button" onClick={marks.clear} data-testid="builder-clear-marks">
            Clear {marks.locked.length} lock(s) and {marks.banned.length} ban(s)
          </button>
        )}
      </div>

      <p className="builder-honesty" data-testid="builder-reoptimise-note">
        Re-optimising here is a <strong>heuristic</strong>, not the optimiser that produced the
        published squad. It builds greedily on expected points per pound and then hill-climbs
        one-for-one swaps within a position, so it respects every rule but will not find a move that
        needs two players sold at once. It also ignores transfer costs entirely. For what to actually
        do before the deadline, read the plan below — that one is solved properly.
      </p>

      {lastRun && <ReoptimiseReport result={lastRun} />}

      {resolved.unknownIds.length > 0 && (
        <p className="builder-unknown" data-testid="builder-unknown">
          {resolved.unknownIds.length} player(s) in this draft are not in the published data and
          cannot be checked.
        </p>
      )}

      <div className="builder-columns">
        <div className="builder-squad">
          {POSITIONS.map((position) => {
            const rows = resolved.members.filter((member) => member.position === position);
            return (
              <div className="builder-group" key={position} data-testid={`builder-group-${position}`}>
                <h3>
                  {position}{" "}
                  <span className="builder-group-count">
                    {rows.length} / {rules.squad.composition[position]}
                  </span>
                </h3>
                {rows.length === 0 && <p className="builder-empty">None selected.</p>}
                {rows.map((member) => (
                  <MemberRow
                    key={member.player_id}
                    member={member}
                    starting={resolved.starting.includes(member.player_id)}
                    isCaptain={resolved.captain === member.player_id}
                    isVice={resolved.vice_captain === member.player_id}
                    locked={marks.isLocked(member.player_id)}
                    onStart={() => setDraft((current) => toggleStarter(current, member.player_id))}
                    onLock={() => marks.lock(member.player_id)}
                    onBan={() => {
                      marks.ban(member.player_id);
                      setDraft((current) => removeFromDraft(current, member.player_id));
                    }}
                    onReplace={() =>
                      setReplacing((current) =>
                        current === member.player_id ? null : member.player_id,
                      )
                    }
                    replacing={replacing === member.player_id}
                  />
                ))}
              </div>
            );
          })}
        </div>

        <div className="builder-picker" data-testid="builder-picker">
          <h3>{replacing === null ? "Add a player" : `Replace ${index.get(replacing)?.name}`}</h3>

          <p className="builder-needed" data-testid="builder-needed">
            {POSITIONS.filter((position) => needed[position] !== 0)
              .map((position) => `${position} ${needed[position] > 0 ? "+" : ""}${needed[position]}`)
              .join(" · ") || "Every position is filled."}
          </p>

          <div className="builder-picker-controls">
            <label className="builder-field">
              <span>Search</span>
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name or club"
                data-testid="builder-search"
              />
            </label>
            {replacing === null && (
              <label className="builder-field">
                <span>Position</span>
                <select
                  value={pickerPosition}
                  onChange={(event) => setPickerPosition(event.target.value as Position | "ALL")}
                  data-testid="builder-position-filter"
                >
                  <option value="ALL">All</option>
                  {POSITIONS.map((position) => (
                    <option key={position} value={position}>
                      {position}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {replacing !== null && (
              <button type="button" onClick={() => setReplacing(null)} data-testid="builder-cancel-replace">
                Cancel
              </button>
            )}
          </div>

          <ul className="builder-candidates">
            {candidates.map((player) => (
              <li key={player.id} data-testid={`builder-candidate-${player.id}`}>
                <button type="button" className="builder-add" onClick={() => add(player.id)}>
                  Add
                </button>
                <span className="builder-candidate-name">{player.name}</span>
                <span className="builder-candidate-sub">
                  {player.position} · {player.team} · {formatPrice(player.price)}
                </span>
                <span
                  className="builder-candidate-xp"
                  title={formatXpRange(player.xp_horizon, player.xp_horizon_sd)}
                >
                  {formatXp(player.xp_horizon, player.xp_horizon_sd)}
                </span>
                <button
                  type="button"
                  className="builder-mark"
                  onClick={() => marks.lock(player.id)}
                  aria-pressed={marks.isLocked(player.id)}
                >
                  {marks.isLocked(player.id) ? "Locked" : "Lock"}
                </button>
                <button
                  type="button"
                  className="builder-mark"
                  onClick={() => marks.ban(player.id)}
                  aria-pressed={marks.isBanned(player.id)}
                >
                  Ban
                </button>
              </li>
            ))}
            {candidates.length === 0 && (
              <li className="builder-empty" data-testid="builder-no-candidates">
                Nobody in the published pool matches.
              </li>
            )}
          </ul>

          {marks.banned.length > 0 && (
            <div className="builder-banned" data-testid="builder-banned">
              <h4>Banned</h4>
              <ul>
                {marks.banned.map((id) => (
                  <li key={id}>
                    {index.get(id)?.name ?? `#${id}`}{" "}
                    <button type="button" onClick={() => marks.ban(id)}>
                      Lift
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * How many candidate rows the picker shows.
 *
 * DP-06: named, with a reason. The pool is around seven hundred players and this list is not
 * virtualised — the scout table is the place to browse them all. Twenty-five is enough that the
 * best options for a position are all present, and few enough to render inside the interaction
 * budget on a phone (NFR-04).
 */
const CANDIDATE_ROWS = 25;

function MemberRow({
  member,
  starting,
  isCaptain,
  isVice,
  locked,
  replacing,
  onStart,
  onLock,
  onBan,
  onReplace,
}: {
  member: BuilderPlayer;
  starting: boolean;
  isCaptain: boolean;
  isVice: boolean;
  locked: boolean;
  replacing: boolean;
  onStart: () => void;
  onLock: () => void;
  onBan: () => void;
  onReplace: () => void;
}) {
  return (
    <div
      className={`builder-row${starting ? " builder-row-starting" : ""}${locked ? " builder-row-locked" : ""}`}
      data-testid={`builder-row-${member.player_id}`}
    >
      <span className="builder-row-name">
        {member.name}
        {isCaptain && <span className="builder-armband" title="Captain">C</span>}
        {isVice && <span className="builder-armband" title="Vice-captain">V</span>}
      </span>
      <span className="builder-row-sub">
        {member.team} · {formatPrice(member.price)}
      </span>
      <span className="builder-row-xp" title={formatXpRange(member.xp_next, member.xp_next_sd)}>
        {formatXp(member.xp_next, member.xp_next_sd)}
      </span>
      <span className="builder-row-actions">
        <button type="button" onClick={onStart} aria-pressed={starting}>
          {starting ? "Starting" : "Bench"}
        </button>
        <button type="button" onClick={onLock} aria-pressed={locked}>
          {locked ? "Locked" : "Lock"}
        </button>
        <button type="button" onClick={onReplace} aria-pressed={replacing}>
          {replacing ? "Choosing…" : "Replace"}
        </button>
        <button type="button" onClick={onBan}>
          Ban
        </button>
      </span>
    </div>
  );
}

function ReoptimiseReport({ result }: { result: ReoptimiseResult }) {
  if (result.status === "infeasible") {
    return (
      <div className="builder-infeasible" data-testid="builder-infeasible" role="status">
        <h3>No legal squad fits those constraints</h3>
        <ul>
          {result.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <p className="builder-run" data-testid="builder-run" role="status">
      Heuristic squad built: {formatPrice(result.totalPrice)} spent, {result.swaps} improving swap(s)
      over {result.passes} pass(es). Not proven optimal.
    </p>
  );
}

# Cross-language conformance corpora

`contracts/v1/` defines the *data* boundary between the pipeline and the web app. This directory
defines the **behavioural** boundary: where the same rule is implemented twice, once in each
language, this is where the cases that must agree are written down.

One file, two readers. Never two files.

## `legality-corpus.json`

Squad legality is implemented twice on purpose — `pipeline/src/fpl_dof/rules/legality.py` decides
what the optimiser is allowed to publish, and `web/src/components/squad/legality.ts` tells a reader
editing a squad in the browser what is wrong with it before they submit it. Two implementations of
one rule set will drift, and legality drift is invisible: the page looks entirely normal while
approving a squad the game will reject.

The corpus closes that. It is read by:

- `pipeline/tests/test_legality_conformance.py` (pytest)
- `web/src/components/squad/legality.conformance.test.ts` (vitest)

Both build the same squads from the same rules and assert the **same ordered list of
`(code, detail)` pairs**. Prose `message` fields are deliberately outside the contract — they are
written for a reader, and the two languages phrase them for their own audiences.

### Shape

| Key | What it is |
| --- | --- |
| `rulesets` | Named squad-rule objects, matching `SquadRules` in Python and `Rules["squad"]` in TypeScript. Each side validates the object into its own type, so a ruleset that is internally inconsistent fails loudly rather than testing nothing. |
| `player_pool` | `id → {position, team_id, price}`. Cases name ids rather than restating players. |
| `cases[]` | `name`, `why`, `rules` (a ruleset key), optional `budget` override, a `squad`, and `expected`. |
| `cases[].squad` | `players` (ids, repeatable — that is how the duplicate case is built), optional `player_defaults` and `player_overrides`, optional `starting`, `captain`, `vice_captain`, `bench_order`. |
| `cases[].expected` | The exact ordered list of `{code, detail}` both validators must return. `[]` means legal. |

A member is built as pool entry → `player_defaults` → `player_overrides[id]`, in that order. That is
the only shared logic either reader implements, and it is a few lines on each side.

### The rule values in here are test input, not configuration

Invariant 2 forbids FPL values as literals **in code**. Nothing reads this file at runtime; it is a
test input that exists precisely to hand the validators rules and check they obey them. The second
ruleset, `twelve_a_side`, is deliberately a game FPL does not play — twelve players, eight starting,
two per club, sixty million — because a validator that carried a literal `15` or `3` would pass every
`fpl_2026_27` case and fail there. `twelve-a-side-rejects-the-legal-fifteen` is Invariant 9 as a
single case: the same squad, different rules, a different answer.

### Adding a case

Write the case, run both suites, and make the *implementations* agree — never soften an expectation
to make a red test green. If the two disagree, `legality.py` is the authority (Invariant 2/9: it
reads the same rules configuration the contract publishes) and the TypeScript mirror is what changes.
One such disagreement has already been found and fixed that way; see DL-39.

## `realised/realised-corpus.json`

What a team actually scored is FPL's to say, so this corpus is FPL's own answer, not ours. Each case
is a real public 2026/27 entry for one finished gameweek — the owner's and the mini-league's, by
entry id and nothing else — and its `expected` is what the game published:
`entry_history.points` (before the hit), `entry_history.event_transfers_cost`, and the game's
`automatic_subs`. Only Python reads it today (`pipeline/tests/test_rules_realised.py`, against
`fpl_dof/rules/realised.py`); it is here so a second implementation never gets its own copy.

A case that the scorer cannot reproduce is a failing test, not an expectation to soften.

| Key | What it is |
| --- | --- |
| `picks` | The fifteen in submitted order: starters 1–11, the reserve goalkeeper, then the outfield bench in order. Each has its `position` and `fixtures`, one `[minutes, points]` per fixture played (two in a double gameweek, none in a blank). |
| `captain`, `vice_captain`, `chip` | As submitted. `chip` is the game's own name (`bboost`, `3xc`, `freehit`, `wildcard`) or `null`. |
| `transfers`, `free_transfers` | `event_transfers` from `entry_history`, and the free transfers derived from the entry's history (below). `null` free transfers in the first gameweek, whose transfers are unlimited. |
| `tags` | What the case exercises, so the test can insist the corpus still covers it. |

### How a case is built from the public endpoints

`scripts/realised_corpus.py` builds the file (DP-11). The committed cut is
`python scripts/realised_corpus.py --owner 4529900 --league 1656895 --last-gameweek 7`, the owner
and the mini-league's ten others; it keeps the owner's gameweeks and every other case with a tag.
It reads `entry/{id}/event/{gw}/picks/`, `event/{gw}/live/` and `entry/{id}/history/`, with no
credentials (Invariant 4), one request a second, cached under `data/`:

1. **The submitted team.** A finished gameweek's picks are the XI *after* substitution. Each pair in
   `automatic_subs` is swapped back, last first, to recover the team as it stood at the deadline.
2. **Per-fixture points.** Each player's `explain` in the live endpoint is one entry per fixture;
   minutes are its `minutes` stat and points the sum of its stats' points.
3. **Free transfers.** One at the second gameweek; after each gameweek, the unused ones plus one,
   capped at the configured maximum; a Wildcard or Free Hit keeps the banked ones and adds one.

No double gameweek or blank had been played when the corpus was cut (GW1 to GW7). The first double
gameweek's entries are the next cases to add.

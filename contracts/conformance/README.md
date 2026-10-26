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

## `lineup-corpus.json`

Choosing the XI, the armbands and the bench order from a fixed fifteen is implemented twice:
`pipeline/src/fpl_dof/squad/selection.py` for the published advice, and
`web/src/components/squad/lineup.ts` for the squad builder. The bench is ranked by
**P(plays) × xP**, ties by the lower player id, in both (WEB-04, the owner's answer in the R1.4.0
plan §5 Q2); the two had drifted, the app sorting by xP alone. Read by:

- `pipeline/tests/test_lineup_conformance.py` (pytest, against `select_team`)
- `web/src/components/squad/lineup.conformance.test.ts` (vitest, against `chooseLineup`)

| Key | What it is |
| --- | --- |
| `player_pool` | `id → {position, xp_next, start_probability}`: the fifteen every case starts from. |
| `cases[]` | `name`, `why`, `rules` (a ruleset key **in `legality-corpus.json`**, not copied here), `player_overrides` (`id → fields`), and `expected`. |
| `cases[].expected` | `starting` (ids, sorted), `bench_order` (the outfield substitutes, in order), `captain`, `vice_captain`, and `formation` as `GKP-DEF-MID-FWD`. |

The XI is ranked on xP alone with no start-probability floor; only the bench is discounted. As with
the legality corpus, `selection.py` is the authority when the two disagree.

## `realised/realised-corpus.json`

What a team actually scored is FPL's to say, so this corpus is FPL's own answer, not ours. Each case
is a real public 2026/27 entry for one finished gameweek — the owner's and the mini-league's, by
entry id and nothing else — and its `expected` is what the game published:
`entry_history.points` (before the hit), `entry_history.event_transfers_cost`, and the game's
`automatic_subs`. Only Python reads it (`pipeline/tests/test_rules_realised.py`, against
`fpl_dof/rules/realised.py`): the app has no scorer and reads scores from the published artefacts.
It is here so a second implementation never gets its own copy.

A case that the scorer cannot reproduce is a failing test, not an expectation to soften.

**The gameweek in play is ours to say** (LIVE-03, DL-99): FPL publishes no answer for a team part
way through a gameweek. The cases tagged `constructed` take one real case (`from`) and rewind some
of its fixtures to unfinished, and their `expected` is the in-play rule worked by hand: a starter or
captain yet to play keeps his place and the armband, a blank is substituted at once, a substitute
yet to play cannot come on and holds the place against those below him while he could enter (the
plan's LIVE-03 states the rule). Each says why in `why`. One constructed case has every fixture finished
and keeps FPL's own answer for the case it is from. The builder writes no constructed case and a
rebuild keeps them.

| Key | What it is |
| --- | --- |
| `picks` | The fifteen in submitted order: starters 1–11, the reserve goalkeeper, then the outfield bench in order. Each has its `position` and `fixtures`, one `[minutes, points]` per fixture played (two in a double gameweek, none in a blank). A constructed case writes each as `[minutes, points, finished]`: `false` is a fixture not yet over, its minutes and points so far. |
| `captain`, `vice_captain`, `chip` | As submitted. `chip` is the game's own name (`bboost`, `3xc`, `freehit`, `wildcard`) or `null`. |
| `transfers`, `free_transfers` | `event_transfers` from `entry_history`, and the free transfers derived from the entry's history (below). `null` free transfers in the first gameweek, whose transfers are unlimited. |
| `tags` | What the case exercises, so the test can insist the corpus still covers it. |
| `from`, `why`, `expected.armband` | A constructed case only: the real case it rewinds, what it shows, and who wears the armband. |

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

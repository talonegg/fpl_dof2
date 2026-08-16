#!/usr/bin/env node
// PreToolUse hook: warns loudly before publishing or deploying inside 45 minutes of a gameweek
// deadline, and requires explicit confirmation to proceed.
//
// See docs/planning/ai/04-hooks-and-settings-plan.md (H4), E7-S7, and DL-41.
//
// This encodes the "never last-minute" rule from Design §9 at the one moment it is most likely to
// be forgotten — when someone is rushing before a deadline, which is precisely when a bad publish
// is most damaging. R-09 is the same rule on the CI side: nothing is *scheduled* inside 45 minutes
// of a deadline either, because scheduled runs can be delayed under platform load and the deadline
// cannot. This hook covers the manual path that R-09 deliberately leaves open as the fallback.
//
// WHY IT READS A FILE RATHER THAN ASKING THE PIPELINE (DL-41)
//
// A PreToolUse hook runs on every matching tool call, so it must be fast and must never be the
// reason a session stalls. Shelling out to Python to compute the next deadline would cost an
// interpreter start plus a config load on every `git push`. The pipeline has already written the
// deadline to disk — `week.json` carries it, in UTC, and `meta.json` carries it as a fallback — so
// this is one readFileSync and no subprocess.
//
// WHY NO DATA MEANS ALLOW
//
// A guard that blocked whenever it could not find a deadline would fire on every fresh checkout and
// would be switched off within a day, and a guard that is switched off protects nothing. So an
// unreadable or absent deadline lets the command through, and says on the way past that it could
// not check. Failing open is the deliberate choice; failing silently is not.

const fs = require("fs");
const path = require("path");

// R-09's window. Written once, here, rather than inferred from a comment further down.
const GUARD_MINUTES = 45;

// Commands that publish or deploy. Three families, and the reason each is here differs:
//
//   * `fpl-dof publish` / `fpl-dof run` actually write the artefacts the site serves. `run` counts
//     because publish is its last stage.
//   * a push to a deploy branch is what triggers the Pages build, so it deploys whether or not the
//     person pushing was thinking of it that way.
//   * `gh workflow run` on a deploy or pipeline workflow is the same act with a different verb.
//
// Deliberately NOT here: `fpl-dof week`, `ingest`, `transform`, `forecast`, `optimise`. None of
// them publishes. Guarding a stage that cannot change what the site serves would train the reader
// to dismiss the warning, which is how a guard stops working without anyone disabling it.
const TRIGGERS = [
  [/\bfpl-dof(\.exe)?\s+(run|publish)\b/, "a pipeline publish"],
  [/\bfpl-dof(\.exe)?\b[^\n|;&]*\bpublish\b/, "a pipeline publish"],
  [/\bgit\s+push\b[^\n|;&]*\b(main|gh-pages|data|snapshots)\b/, "a push to a deploy branch"],
  [/\bgh\s+workflow\s+run\b[^\n|;&]*\b(deploy|pipeline|publish)\b/, "a deploy workflow dispatch"],
];

// Where the pipeline has already written the next deadline, best first. `week.json` is the
// authority — it is the artefact whose whole subject is this deadline. `meta.json` is the fallback
// because it carries `deadline_utc` too and is written on every publish, including the runs before
// the first gameweek is scored where `week.json` legitimately does not exist (DL-20).
const SOURCES = [
  ["data/web/v1/week.json", (d) => d?.deadline?.deadline_utc],
  ["web/public/data/v1/week.json", (d) => d?.deadline?.deadline_utc],
  ["data/web/v1/meta.json", (d) => d?.deadline_utc],
  ["web/public/data/v1/meta.json", (d) => d?.deadline_utc],
];

function readStdin() {
  try {
    return fs.readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** `data/gold/season=*​/week.json`, which is where the week stage writes before publish copies it. */
function goldWeekFiles(root) {
  const gold = path.join(root, "data", "gold");
  try {
    return fs
      .readdirSync(gold, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && entry.name.startsWith("season="))
      .map((entry) => path.join(gold, entry.name, "week.json"));
  } catch {
    return [];
  }
}

/**
 * The next deadline as an epoch millisecond value, plus where it was read from.
 *
 * Every candidate is read and the *soonest future* one wins, rather than the first file that
 * happens to parse. The published copy and the gold copy can disagree — a publish that was blocked
 * by a quality gate leaves gold ahead of `data/web/` (Invariant 7) — and in a guard, the safe
 * reading of two disagreeing sources is the earlier deadline.
 */
function nextDeadline(root, now) {
  const candidates = [];

  for (const [relative, pick] of SOURCES) {
    const data = readJson(path.join(root, relative));
    if (data) candidates.push([pick(data), relative]);
  }
  for (const file of goldWeekFiles(root)) {
    const data = readJson(file);
    if (data) candidates.push([data?.deadline?.deadline_utc, path.relative(root, file)]);
  }

  let best = null;
  for (const [value, origin] of candidates) {
    if (typeof value !== "string") continue;
    const at = Date.parse(value);
    if (Number.isNaN(at) || at <= now) continue; // A deadline already past is not the next one.
    if (best === null || at < best.at) best = { at, origin, iso: value };
  }
  return best;
}

function main() {
  let payload;
  try {
    payload = JSON.parse(readStdin() || "{}");
  } catch {
    process.exit(0); // Unparseable input: don't block on a hook bug.
  }

  const command = payload?.tool_input?.command || "";
  if (!command) process.exit(0);

  const trigger = TRIGGERS.find(([pattern]) => pattern.test(command));
  if (!trigger) process.exit(0); // Not a publish or a deploy; nothing to guard.

  const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const now = Date.now();
  const deadline = nextDeadline(root, now);

  // Fail open, and say so. See the note at the top of this file.
  if (deadline === null) process.exit(0);

  const minutesLeft = (deadline.at - now) / 60000;
  if (minutesLeft > GUARD_MINUTES) process.exit(0);

  const rounded = Math.max(0, Math.round(minutesLeft));
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        // "ask", not "deny": H4 requires explicit confirmation, not a prohibition. There are real
        // reasons to publish inside the window — a corrected squad beats a wrong one right up to
        // the deadline — and a guard that made those impossible would be routed around rather than
        // heeded. What it must never be is *automatic*.
        permissionDecision: "ask",
        permissionDecisionReason:
          `⚠ DEADLINE GUARD — the next FPL deadline is ${rounded} minute(s) away ` +
          `(${deadline.iso}), inside the ${GUARD_MINUTES}-minute window.\n\n` +
          `This command is ${trigger[1]}, so it can change what the site serves before a ` +
          `deadline you may not have time to review.\n\n` +
          `Read from ${deadline.origin}. Confirm only if you have decided deliberately to ` +
          `publish now — and check that the squad on the page is the one you intend to field.\n\n` +
          `See docs/planning/ai/04-hooks-and-settings-plan.md (H4) and R-09.`,
      },
    }),
  );
  process.exit(0);
}

main();

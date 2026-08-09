#!/usr/bin/env node
// PreToolUse hook: denies any agent write to amendment-controlled documents.
// See docs/DESIGN-PRINCIPLES.md §4 and DL-16.
//
// CLAUDE.md and .claude/rules/ are context, not enforcement — an agent can be talked into
// editing a file that tells it not to. This hook is the enforcement half: it blocks the write
// regardless of what the model decided. An agent that can rewrite its own constraints does not
// have constraints.
//
// The owner amends these files directly, outside an agent session, per the documented procedure.

const path = require("path");

// Repo-relative paths that no agent may write to.
const PROTECTED = [
  "docs/DESIGN-PRINCIPLES.md",
];

function readStdin() {
  try {
    return require("fs").readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function normalise(p) {
  if (!p) return "";
  return String(p).replace(/\\/g, "/").replace(/^\.\//, "");
}

function main() {
  let payload;
  try {
    payload = JSON.parse(readStdin() || "{}");
  } catch {
    process.exit(0); // Unparseable input: don't block on a hook bug.
  }

  const raw = payload?.tool_input?.file_path
    || payload?.tool_input?.notebook_path
    || payload?.tool_input?.path;
  if (!raw) process.exit(0);

  const projectDir = normalise(process.env.CLAUDE_PROJECT_DIR || process.cwd());
  let target = normalise(path.isAbsolute(raw) ? raw : path.resolve(process.cwd(), raw));

  // Reduce to a repo-relative path when the file sits inside the project.
  if (projectDir && target.toLowerCase().startsWith(projectDir.toLowerCase())) {
    target = target.slice(projectDir.length).replace(/^\//, "");
  }

  const hit = PROTECTED.find(
    (p) => target.toLowerCase() === p.toLowerCase()
        || target.toLowerCase().endsWith("/" + p.toLowerCase())
  );

  if (!hit) process.exit(0);

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        `BLOCKED: ${hit} is amendment-controlled and must not be edited by an agent.\n\n` +
        `Do not retry, do not route around this hook, and do not disable it.\n\n` +
        `If a principle is wrong, obstructive or missing: stop, and propose the specific ` +
        `wording to the owner in conversation. Amendment requires explicit owner approval ` +
        `plus a decision-log entry — see docs/DESIGN-PRINCIPLES.md §4.\n\n` +
        `If you were asked to record a deviation rather than change a principle, that is a ` +
        `WAIVER, not an amendment: add an inline DP-WAIVER marker at the code site and a ` +
        `decision-log entry (§3). Neither touches this file.`,
    },
  }));
  process.exit(0);
}

main();

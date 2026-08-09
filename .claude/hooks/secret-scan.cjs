#!/usr/bin/env node
// PreToolUse hook: blocks `git commit` when staged content looks like it contains a secret.
// See docs/planning/ai/04-hooks-and-settings-plan.md H3.
//
// Reads the PreToolUse payload from stdin, and if the Bash command being run is a `git commit`,
// scans `git diff --cached` for common secret shapes. Deliberately conservative: false positives
// cost a re-run; a leaked key in git history is effectively permanent.

const { execSync } = require("child_process");

const PATTERNS = [
  [/-----BEGIN[ A-Z]*PRIVATE KEY-----/, "a private key block"],
  [/AKIA[0-9A-Z]{16}/, "an AWS access key ID"],
  [/ghp_[A-Za-z0-9]{36}/, "a GitHub personal access token"],
  [/gho_[A-Za-z0-9]{36}/, "a GitHub OAuth token"],
  [/xox[baprs]-[A-Za-z0-9-]{10,}/, "a Slack token"],
  [/sk-[A-Za-z0-9]{20,}/, "an API secret key (sk- prefix)"],
  // generic KEY = "..." / SECRET: '...' / TOKEN=... assignments with a non-trivial value
  [/\b[A-Z0-9_]*(API|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE)[A-Z0-9_]*\s*[:=]\s*["'][^"'\s]{8,}["']/i, "a credential-like assignment"],
];

function readStdin() {
  try {
    return require("fs").readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function main() {
  let payload;
  try {
    payload = JSON.parse(readStdin() || "{}");
  } catch {
    process.exit(0); // Can't parse input; don't block on a hook bug.
  }

  const command = payload?.tool_input?.command || "";
  if (!/\bgit\s+commit\b/.test(command)) {
    process.exit(0); // Not a commit; nothing to check.
  }

  let diff;
  try {
    diff = execSync("git diff --cached", { encoding: "utf8", maxBuffer: 20 * 1024 * 1024 });
  } catch (err) {
    process.exit(0); // No repo, nothing staged, or git unavailable; let it through.
  }

  if (!diff) {
    process.exit(0);
  }

  for (const [pattern, label] of PATTERNS) {
    if (pattern.test(diff)) {
      const out = {
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason:
            `Staged changes appear to contain ${label}. Blocked before commit ` +
            `(see docs/planning/ai/04-hooks-and-settings-plan.md, H3). ` +
            `If this is a false positive, unstage the offending file, confirm it is safe, ` +
            `and re-stage deliberately.`,
        },
      };
      process.stdout.write(JSON.stringify(out));
      process.exit(0);
    }
  }

  process.exit(0); // Clean; no decision, normal flow continues.
}

main();

/**
 * The owner-triggered `workflow_dispatch` link (E13-S3, Q-16).
 *
 * GitHub's "Run workflow" UI does not read query parameters to pre-fill a dispatched run's inputs —
 * there is no supported deep-link format for that — so this composes a link to the workflow's Actions
 * page plus the entered IDs as copyable text, for the owner to paste into the `team_id` / `league_id`
 * inputs `pipeline.yml`'s `workflow_dispatch` trigger declares (E13-S1). No GitHub token is ever
 * constructed, held or transmitted here: the owner authenticates to GitHub themselves by following the
 * link (Invariant 10, NFR-13). Auto-dispatch from the browser is explicitly out of scope — Q-16 stays
 * open.
 */

/** This repository, for the one link a reader might follow off the site (Invariant 10 — public). */
const REPO = "talonegg/fpl_dof2";
const PIPELINE_WORKFLOW_FILE = "pipeline.yml";

export function pipelineWorkflowUrl(): string {
  return `https://github.com/${REPO}/actions/workflows/${PIPELINE_WORKFLOW_FILE}`;
}

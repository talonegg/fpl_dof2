---
name: release
description: The branching and release procedure for this repository — feature branches merged straight into the dev/Rx.y.z release branch, promotion through pre-release into main, tagging, hotfixes, and starting the next release. Load before creating or merging a branch, opening a pull request, promoting a release, tagging, or fixing something in production.
user-invokable: true
---

# Branching and releases

Policy and rationale: DL-80, DL-82 and the release register (`docs/planning/epics/README.md`). This skill is
the procedure. Releases are numbered `Rx.y.z`; `main` carries one annotated tag per release.

## The branches

| Branch | What it is | Who writes to it |
| --- | --- | --- |
| `main` | Production. Scheduled workflows run its code; every merge deploys to Pages | Pull request from `pre-release` only (protected) |
| `pre-release` | Main plus the promotion under test. CI and the pre-release smoke test run on it | Pull request from `dev/Rx.y.z` or a hotfix branch only (protected) |
| `dev/Rx.y.z` | The open release, e.g. `dev/R1.1.0`. Cut from `main` when the release starts | Direct merges from `feature/*`, after the local checks pass (DL-82) |
| `feature/<description>` | One feature or fix, kebab-case description. Kept until the release is tagged, then deleted | You |
| `data`, `snapshots`, `ledger` | Pipeline state, written by workflows | Never by hand |

**Never** commit or push directly to `main` or `pre-release`, never force-push either, and never
delete a `dev/Rx.y.z` branch before its release is tagged.

## A feature or fix for the open release

No pull request (DL-82). Run the local checks first — lint, format, type check, the Python and web
tests and the docs check, as `CLAUDE.md` lists them — and do not push into a red dev branch.

```bash
git fetch origin
git switch -c feature/<description> origin/dev/R1.1.0
# ...commit, naming the FR/NFR ids; run the local checks...
git push -u origin feature/<description>        # optional: a remote copy while it is open
git switch dev/R1.1.0 && git pull --ff-only
git merge --no-ff feature/<description> -m "Merge feature/<description> into dev/R1.1.0"
git push origin dev/R1.1.0                      # CI runs on dev/**; fix any failure first
```

Keep the feature branch: it is deleted with the others when the release is tagged.

## Promote the release

1. **Bring `pre-release` level with `main`** (it must be main plus only this promotion). If
   `git log origin/pre-release..origin/main` lists anything, open and merge
   `gh pr create --base pre-release --head main --title "Sync pre-release with main"`.
2. **Promote:** `gh pr create --base pre-release --head dev/R1.1.0 --title "Promote R1.1.0"`; merge it
   once CI passes. The push to `pre-release` runs CI and the pre-release smoke test.
3. **If anything fails,** fix it on a `feature/*` branch merged into `dev/R1.1.0` and promote again.
   Never fix on `pre-release` itself.
4. **Release:** `gh pr create --base main --head pre-release --title "Release R1.1.0"`. CI and the
   smoke test must pass (both are required checks). Merge with a merge commit; `deploy.yml` deploys.
5. **Tag** the merge commit on main, annotated, and push it — `release.yml` publishes the GitHub
   Release:
   ```bash
   git fetch origin && git tag -a R1.1.0 origin/main -m "R1.1.0 — <title>" && git push origin R1.1.0
   ```
6. **Delete the release's feature branches**, local and remote, now that the tag exists:
   ```bash
   git branch --merged origin/main --list 'feature/*' | xargs -r git branch -d
   git branch -r --merged origin/main --list 'origin/feature/*' | sed 's|origin/||' | xargs -r git push origin --delete
   ```
7. **Close the release in the docs** (release register: fill its Status line, archive its plan to
   `docs/planning/archive/R1.1.0/`), on the next dev branch.

## Start the next release

```bash
git fetch origin
git switch -c dev/R1.2.0 origin/main && git push -u origin dev/R1.2.0
```

Increment `y` for a planned release, `x` for a major change of direction. Delete the old
`dev/Rx.y.z` branch only after its tag exists. Record the decision to build it (a DL entry) and add
its row to the release register.

## Hotfix

A fix that cannot wait for the open release:

1. `git switch -c feature/<fix-description> origin/main`, fix, push, and
   `gh pr create --base pre-release` (sync `pre-release` with `main` first, as above).
2. Merge once CI passes; the smoke test runs on `pre-release`. Then
   `gh pr create --base main --head pre-release --title "Hotfix R1.0.1"`, merge, and tag with the
   **patch** number incremented from main's latest tag (`git describe --tags --abbrev=0 origin/main`).
3. Delete the hotfix branch, and **merge `main` into the open `dev/Rx.y.z`** so the fix is not lost
   when that release promotes.

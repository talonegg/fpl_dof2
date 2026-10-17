---
name: release
description: The branching and release procedure for this repository — feature branches, the dev/Rx.y.z release branch, promotion through pre-release into main, tagging, hotfixes, and starting the next release. Load before creating a branch, opening or merging a pull request, promoting a release, tagging, or fixing something in production.
user-invokable: true
---

# Branching and releases

Policy and rationale: DL-80 and the release register (`docs/planning/epics/README.md`). This skill is
the procedure. Releases are numbered `Rx.y.z`; `main` carries one annotated tag per release.

## The branches

| Branch | What it is | Who writes to it |
| --- | --- | --- |
| `main` | Production. Scheduled workflows run its code; every merge deploys to Pages | Pull request from `pre-release` only (protected) |
| `pre-release` | Main plus the promotion under test. CI and the pre-release smoke test run on it | Pull request from `dev/Rx.y.z` or a hotfix branch only (protected) |
| `dev/Rx.y.z` | The open release, e.g. `dev/R1.1.0`. Cut from `main` when the release starts | Pull requests from `feature/*` |
| `feature/<description>` | One feature or fix, kebab-case description. Deleted once merged | You |
| `data`, `snapshots`, `ledger` | Pipeline state, written by workflows | Never by hand |

**Never** commit or push directly to `main` or `pre-release`, never force-push either, and never
delete a `dev/Rx.y.z` branch before its release is tagged.

## A feature or fix for the open release

```bash
git fetch origin
git switch -c feature/<description> origin/dev/R1.1.0
# ...commit, naming the FR/NFR ids...
git push -u origin feature/<description>
gh pr create --base dev/R1.1.0 --title "<what>" --body "<why; FR/NFR; DL-nn>"
# after CI passes and it is merged:
gh pr merge <n> --merge --delete-branch
```

## Promote the release

1. **Bring `pre-release` level with `main`** (it must be main plus only this promotion). If
   `git log origin/pre-release..origin/main` lists anything, open and merge
   `gh pr create --base pre-release --head main --title "Sync pre-release with main"`.
2. **Promote:** `gh pr create --base pre-release --head dev/R1.1.0 --title "Promote R1.1.0"`; merge it
   once CI passes. The push to `pre-release` runs CI and the pre-release smoke test.
3. **If anything fails,** fix it on a `feature/*` branch into `dev/R1.1.0` and promote again. Never
   fix on `pre-release` itself.
4. **Release:** `gh pr create --base main --head pre-release --title "Release R1.1.0"`. CI and the
   smoke test must pass (both are required checks). Merge with a merge commit; `deploy.yml` deploys.
5. **Tag** the merge commit on main, annotated, and push it — `release.yml` publishes the GitHub
   Release:
   ```bash
   git fetch origin && git tag -a R1.1.0 origin/main -m "R1.1.0 — <title>" && git push origin R1.1.0
   ```
6. **Close the release in the docs** (release register: fill its Status line, archive its plan to
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

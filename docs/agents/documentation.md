# Writing and keeping documents

How to keep the documents lean as the season runs (DL-74): one home for each fact, live pages that
say what is true now, and history archived with its text kept. The map of homes is
[`docs/README.md`](../README.md).

## Live pages

A live page is any document outside an archive and outside `docs/decisions/`. It says what is true
now.

- **Rewrite, do not append.** When a decision changes a page, rewrite the sentence to the new truth
  and cite the entry: "The risk dial defaults to Balanced (DL-25)". No "*Amended <date>:* …
  originally …" notes; the entry holds the old position and the reason.
- **Cite, do not narrate.** No "since E9", "until GW6", "moved here by". A citation leads to the
  history.
- **Link, do not restate.** One sentence and a link to the fact's home. A second copy goes stale the
  day the first changes.
- **No figures that rot.** Test counts, timings, backtest scores and file sizes belong in a record —
  a DL entry, a commit message, the model card. A live page states a limit or a rule, never the last
  measurement.
- **Repository-relative links only.** Never `file:///` or a path on one machine; the repository is
  public and the links break everywhere else.
- **British English; currency is £.**

## Decisions

The rules for writing, citing and superseding an entry are in
[`docs/decisions/README.md`](../decisions/README.md). An entry is a record: after acceptance it takes
only a re-pointed link or a `Superseded by DL-nn` note.

## Epics

An epic is a plan: stories, acceptance boxes, files. A box's note names its DL entry in a line; the
narrative of the build goes in the entry or the commit. When an epic closes, follow the steps in the
[epic register](../planning/epics/README.md).

## Archiving

An archive keeps a document's text word for word, so nothing is lost and the live tree shrinks. What
is archived is changed only to re-point its links. Archives are `docs/planning/archive/` and
`docs/architecture/archive/`.

- **A whole document**: `git mv` it into the archive, add its row to the archive's README, re-point
  the links to it.
- **A section that is no longer live**: move its text to an archive file headed with what it is, when
  and why it moved (its DL entry), and "only links are re-pointed". Leave a one-line pointer in its
  place, so section numbers and anchors stay stable.
- **A live section inside a closing document** (as the debt register was inside E0): move it to a
  live page of its own first, then archive the rest.

`docs/.rgignore` leaves the archives out of a plain search, so a search finds what is true now.
Search an archive by naming its path.

## Amendment-controlled files

`docs/DESIGN-PRINCIPLES.md` is never edited by an agent (DL-16). When a move would break one of its
links, leave a stub at the old path that points to the new home and keeps any linked heading, and
tell the owner which links to re-point. Delete the stub once they are re-pointed.

## The check

Run `python scripts/docs.py check` after changing any document or a comment that cites one. CI runs
it too. It fails on a stale decision index, a relative Markdown link to a missing file, or a `DL-nn`
cited anywhere in the repository that has no entry.

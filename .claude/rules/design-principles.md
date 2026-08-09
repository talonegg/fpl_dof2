<!--
  Always-loaded pointer. No `paths:` frontmatter, so this loads every session.
  Deliberately carries principle NAMES ONLY — never the reasoning, the practice notes,
  or the anti-patterns. Duplicated text would drift from docs/DESIGN-PRINCIPLES.md.
  Update this file only when a principle is added, retired or renamed.
-->

# Design principles are binding in this repository

The full text is **`docs/DESIGN-PRINCIPLES.md`**. It is authoritative, and it is
**amendment-controlled** — a `PreToolUse` hook blocks writes to it. If you think a principle is wrong
or obstructive, say so and stop; propose the change in conversation. Never edit the file, work around
the hook, or disable it.

**Read the full document before**: designing a module, adding a data source, adding or changing a
model, changing the optimiser formulation, altering a contract or schema, or deciding how something
gets tested. The summary below is for recognition only — it is not enough to design from.

| | Structure | | Adaptability |
| --- | --- | --- | --- |
| DP-01 | Sources are plugins; the core never names one | DP-05 | Business rules are configuration, in every language |
| DP-02 | Prediction and decision are separate concerns | DP-06 | Every tunable is named, defaulted and justified |
| DP-03 | Pure core, effectful edge | DP-07 | Build vertical slices that each exit usable |
| DP-04 | Every seam is a versioned, typed contract | DP-08 | New behaviour ships dark, promoted on evidence |

| | Transparency | | Trust |
| --- | --- | --- | --- |
| DP-09 | Every number carries derivation, uncertainty, provenance | DP-11 | Every run is reproducible from its recorded inputs |
| DP-10 | Prefer the formulation you can argue with | DP-12 | Measure skill against a baseline, never absolutely |
| | | DP-13 | Test hardest where being wrong is invisible |
| | | DP-14 | Every artefact traces to a requirement |
| | | DP-15 | Degrade, never break |

**Status: binding constraints, not aspirations.** Violating code is a defect — fix it, or record a
waiver: an inline `DP-WAIVER(DP-nn): <reason> — see DL-nn` marker at the code site **plus** a
decision-log entry. Both, never one alone.

**When a principle conflicts with a deadline, the principle holds and scope is cut instead** (DL-10).
"No time" is not a waiver reason; it is a scope decision, and should be taken as one.

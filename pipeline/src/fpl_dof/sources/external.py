"""Sources the pipeline depends on that sit outside the adapter registry (T-003).

The frozen prospective harness reads these directly, so no adapter fetches them and no bronze
snapshot records them. They are declared here so the data health page can list them; the evidence
for each (when it was last fetched, whether its pinned files still match) comes from the
prospective record the publish job already receives, never from a fetch made for the page.

Labels and wording are Scribe's (projects/fpl-data-sources/labels.md, T-004). Facts behind them are
pinned by ``tests/test_source_catalogue.py``:

* the history seasons are exactly ``prospective.fdcouk.HISTORY`` (hash-pinned in the bundle
  manifest at the 2026-10-13 freeze); 2026/27 is deliberately not one of them;
* the 2026/27 backfill is the dated copy ``scripts/models_history/data/fdcouk/E0_2627_20261017.csv``
  (also written once to the ledger at ``backfill/fdcouk/E0_2627_20261017.csv``);
* the fplcache index in the frozen bundle ends at the 2025/26 GW38 snapshot of 2026-05-24.
"""

from __future__ import annotations

from fpl_dof.sources.catalogue import LIVE, REFERENCE, SourceDescriptor

EXTERNAL_SOURCES: tuple[SourceDescriptor, ...] = (
    SourceDescriptor(
        key="fdcouk_fixtures",
        kind=LIVE,
        label="Upcoming match odds (football-data.co.uk)",
        description=(
            "Bookmaker odds for this gameweek's fixtures, fetched before the deadline. These are "
            "the odds the odds-based model (A+odds) decides with."
        ),
        enabled=True,
        registered=False,
        record_block="odds",
        record_check="live_odds",
    ),
    SourceDescriptor(
        key="fdcouk_history",
        kind=REFERENCE,
        label="Past match odds, 2023/24–2025/26 (football-data.co.uk)",  # noqa: RUF001 - Scribe's label, verbatim
        description=(
            "Premier League match odds from past seasons that the odds-based model learns from. "
            "Each run checks the files against pinned copies."
        ),
        enabled=True,
        registered=False,
        note="Fixed seasons. Each run checks the files against their pinned copies.",
        as_of="2026-10-13",
        record_check="odds_history",
    ),
    SourceDescriptor(
        key="fdcouk_backfill_2627",
        kind=REFERENCE,
        label="Early-season odds, 2026/27 (football-data.co.uk)",
        description=(
            "Odds for this season's opening gameweeks, saved once on 17 Oct 2026. They're used "
            "only to replay the model's GW1–6 record, not for live picks."  # noqa: RUF001 - Scribe's label, verbatim
        ),
        enabled=True,
        registered=False,
        note="Saved once on 17 Oct 2026 and never updated. Covers GW1–6.",  # noqa: RUF001 - Scribe's label, verbatim
        as_of="2026-10-17",
    ),
    SourceDescriptor(
        key="fplcache",
        kind=REFERENCE,
        label="Archived FPL snapshots (fplcache)",
        description=(
            "Saved copies of the official game data from past deadlines, used to rebuild last "
            "season's model history. The archive ends at 2025/26 gameweek 38."
        ),
        enabled=True,
        registered=False,
        note=(
            "Fixed archive that ends at 2025/26 gameweek 38. It's used for replays and backtests "
            "only."
        ),
        as_of="2026-05-24",
    ),
)

__all__ = ["EXTERNAL_SOURCES"]

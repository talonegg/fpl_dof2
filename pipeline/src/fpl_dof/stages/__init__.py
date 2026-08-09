"""Stage entry points.

One module per pipeline stage, each exposing ``run(ctx) -> StageResult``. These modules are the
effectful edge (DP-03): they read and write files and call adapters. The logic they call into is
pure and lives elsewhere.
"""

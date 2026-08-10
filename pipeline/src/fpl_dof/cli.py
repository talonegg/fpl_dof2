"""``fpl-dof`` command line entry point.

Stdlib argparse on purpose: one fewer dependency, and the CLI is a thin shell over
:mod:`fpl_dof.pipeline`. All the interesting behaviour is there and is testable without a process.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from fpl_dof import __version__
from fpl_dof.config import ConfigError, layout_for, load_config
from fpl_dof.obs import ManifestWriter, StageStatus, configure_logging, get_logger, new_run_id
from fpl_dof.obs.logging import run_context
from fpl_dof.paths import find_repo_root
from fpl_dof.pipeline import (
    ALL_STAGES,
    STAGES,
    StageContext,
    StageFailedError,
    StageOptions,
    UnknownStageError,
    resolve_stages,
    run_stages,
)

log = get_logger(__name__)

EXIT_OK = 0
EXIT_STAGE_FAILED = 1
EXIT_BAD_USAGE = 2
EXIT_CONFIG_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpl-dof",
        description="FPL DOF pipeline: ingest, conform, forecast, optimise, publish.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Stages run in the order listed. `run` executes all of them.",
    )
    parser.add_argument("--version", action="version", version=f"fpl-dof {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override the configured log level for this invocation.",
    )
    parser.add_argument(
        "--data-dir",
        help="Override the data root for this invocation.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="STAGE", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--force-refresh",
            action="store_true",
            help="Ignore caches and re-fetch from source.",
        )
        sub.add_argument(
            "--offline",
            action="store_true",
            help="Fail rather than make a network call. Uses existing bronze snapshots.",
        )
        sub.add_argument(
            "--player-limit",
            type=int,
            default=None,
            help="Cap per-player fetches. For development only; never for a real run.",
        )

    for stage in ALL_STAGES:
        sub = subparsers.add_parser(stage.name, help=stage.summary, description=stage.summary)
        add_common(sub)

    run_parser = subparsers.add_parser(
        "run",
        help="Run every stage in order",
        description="Run every stage in order: " + ", ".join(s.name for s in STAGES) + ".",
    )
    add_common(run_parser)
    run_parser.add_argument(
        "--only",
        nargs="+",
        metavar="STAGE",
        help="Run only these stages, in registry order.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Command-line overrides are expressed as environment overrides so there is exactly one
    # precedence order in the system, defined in the config loader.
    environ = dict(os.environ)
    if args.data_dir:
        environ["FPL_DOF_DATA_DIR"] = args.data_dir
    if args.log_level:
        environ["FPL_DOF_LOG_LEVEL"] = args.log_level

    try:
        config, digest = load_config(environ=environ)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    configure_logging(config.runtime.log_level)
    layout = layout_for(config)
    layout.ensure()

    try:
        names = args.only if args.command == "run" else [args.command]
        stages = resolve_stages(names)
    except UnknownStageError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_USAGE

    run_id = new_run_id()
    options = StageOptions(
        force_refresh=args.force_refresh,
        offline=args.offline,
        player_limit=args.player_limit,
    )
    ctx = StageContext(config=config, layout=layout, run_id=run_id, options=options)
    writer = ManifestWriter(
        run_id=run_id,
        config_digest=digest,
        runs_dir=layout.runs,
        data_root=layout.root,
        requested_stages=[stage.name for stage in stages],
        repo=find_repo_root(),
    )

    with run_context(run_id):
        log.info(
            "run.start",
            extra={
                "stages": [stage.name for stage in stages],
                "data_dir": str(layout.root),
                "config_digest": digest,
            },
        )
        try:
            manifest = run_stages(stages, ctx, writer)
        except StageFailedError as exc:
            log.error("run.failed", extra={"error": str(exc)})
            print(f"run failed: {exc}\nmanifest: {writer.path}", file=sys.stderr)
            return EXIT_STAGE_FAILED

        log.info("run.done", extra={"manifest": str(writer.path)})

    print(f"run {manifest.run_id} {manifest.status or StageStatus.SUCCEEDED}: {writer.path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

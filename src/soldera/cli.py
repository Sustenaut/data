"""The soldera command.

    soldera run PIPELINE.yaml [--from STAGE|auto] [--to STAGE] [--force]
                              [--store DIR] [--run-log FILE] [--run-id ID] [--trigger KIND]

`--from auto` starts at the earliest stage whose pinned parser changed or whose
input changed, and runs nothing when every stage is up to date. Without
`--from`, the run starts at the first stage.

Exit codes: 0 every stage succeeded, 1 a stage failed (one failed item fails it), 2 the
run could not start as asked."""

from __future__ import annotations

import argparse
import os
import sys

from soldera import __version__
from soldera.core import pipeline as pipeline_mod
from soldera.core.runlog import JsonlRunLog
from soldera.core.runner import AUTO, RunError, Runner
from soldera.core.storage import LocalStorage

TRIGGERS = ("manual", "schedule", "deploy", "rerun")


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="soldera", description="Run soldera's ingest pipelines.")
    main.add_argument("--version", action="version", version=f"soldera {__version__}")
    commands = main.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a pipeline, or part of it")
    run.add_argument("pipeline", help="the pipeline's YAML file")
    run.add_argument("--from", dest="start", metavar="STAGE",
                     help=f"the first stage to run, or {AUTO}: where a parser or input changed")
    run.add_argument("--to", dest="end", metavar="STAGE", help="the last stage to run")
    run.add_argument("--force", action="store_true", help="build every item again, stored or not")
    run.add_argument("--store", default=os.environ.get("SOLDERA_STORE", "store"),
                     help="the directory stage outputs are kept in (SOLDERA_STORE)")
    run.add_argument("--run-log", default=os.environ.get("SOLDERA_RUN_LOG", "runs.jsonl"),
                     help="the JSONL file run log rows are appended to (SOLDERA_RUN_LOG)")
    run.add_argument("--run-id", help="the run's id, when what started it made one")
    run.add_argument("--trigger", choices=TRIGGERS, default="manual", help="what started the run")
    return main


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        pipeline = pipeline_mod.load(args.pipeline)
        runner = Runner(pipeline, LocalStorage(args.store), JsonlRunLog(args.run_log), sys.stdout, sys.stderr)
        return runner.run(start=args.start, end=args.end, force=args.force, run_id=args.run_id,
                          trigger=args.trigger)
    except (pipeline_mod.PipelineError, RunError) as error:
        print(f"soldera: {error}", file=sys.stderr)
        return 2

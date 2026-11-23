"""The soldera command.

    soldera run PIPELINE.yaml [--from STAGE|auto] [--to STAGE] [--force]
                              [--store DIR] [--run-log FILE|bigquery:PROJECT.DATASET.TABLE] [--run-id ID] [--trigger KIND]
    soldera output PIPELINE.yaml STAGE [--name NAME] [--copy-to FILE] [--store DIR]
    soldera corrections check FILE

`output` prints where the newest published output of a stage is kept (the
store files outputs by content hash), or copies it to FILE.

`corrections check` checks a corrections file's shape and tries each rule on
the excerpt it keeps of the file it corrects.

`--from auto` starts at the earliest stage whose pinned parser changed or whose
input changed, and runs nothing when every stage is up to date. Without
`--from`, the run starts at the first stage.

Exit codes: 0 every stage succeeded, 1 a stage failed (one failed item fails it), 2 the
run could not start as asked."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from soldera import __version__
from soldera.core import pipeline as pipeline_mod
from soldera.core.runlog import RunLogError, open_run_log
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
    run.add_argument("--store-uri", default=os.environ.get("SOLDERA_STORE_URI") or None,
                     help="what the store is, as the run log names it, such as gs://BUCKET when the "
                          "store is that bucket, mounted (SOLDERA_STORE_URI)")
    run.add_argument("--run-log", default=os.environ.get("SOLDERA_RUN_LOG", "runs.jsonl"),
                     help="where run log rows go: a JSONL file, or bigquery:PROJECT.DATASET.TABLE "
                          "(SOLDERA_RUN_LOG)")
    run.add_argument("--run-id", help="the run's id, when what started it made one")
    run.add_argument("--trigger", choices=TRIGGERS, default="manual", help="what started the run")
    output = commands.add_parser("output", help="where a stage's newest published output is, or a copy of it")
    output.add_argument("pipeline", help="the pipeline's YAML file")
    output.add_argument("stage", help="the stage")
    output.add_argument("--name", help="the output's name, when the stage has several")
    output.add_argument("--copy-to", metavar="FILE", help="copy the output to FILE")
    output.add_argument("--store", default=os.environ.get("SOLDERA_STORE", "store"),
                        help="the directory stage outputs are kept in (SOLDERA_STORE)")
    fixes = commands.add_parser("corrections", help="work with a corrections file")
    fix_commands = fixes.add_subparsers(dest="action", required=True)
    check = fix_commands.add_parser("check", help="check each rule against the excerpt it keeps")
    check.add_argument("file", help="the corrections file")
    return main


def check_corrections(path: str) -> int:
    from soldera.core import corrections  # noqa: PLC0415

    try:
        rules = corrections.load(path)
    except corrections.CorrectionError as error:
        print(f"soldera: {error}", file=sys.stderr)
        return 2
    problems = corrections.check(rules)
    for problem in problems:
        print(f"{path}: {problem}", file=sys.stderr)
    checked = sum(1 for r in rules if r["kind"] in corrections.ROW_KINDS)
    print(f"{path}: {len(rules)} rules, {checked} checked against their excerpts, {len(problems)} problems")
    return 1 if problems else 0


def show_output(args: argparse.Namespace) -> int:
    pipeline = pipeline_mod.load(args.pipeline)
    stage = pipeline.stage(args.stage)
    storage = LocalStorage(args.store)
    latest = storage.get_json_or_none(f"{stage.prefix}/latest.json")
    if latest is None:
        raise RunError(f"stage {stage.name} ({stage.parser.ref()}) has published nothing in {args.store}")
    manifest = storage.get_json(latest["manifest"])
    outputs = [o for item in manifest["items"] for o in item["outputs"] if args.name in (None, o["name"])]
    if not outputs:
        raise RunError(f"stage {stage.name}'s run {latest['run_id']} published no output named {args.name}")
    if args.copy_to:
        if len(outputs) > 1:
            raise RunError(f"stage {stage.name} published {len(outputs)} outputs; name one with --name: "
                           + ", ".join(o["name"] for o in outputs[:10]))
        target = Path(args.copy_to)
        shutil.copyfile(storage.path(outputs[0]["key"]), target)
        print(f"{target}: {outputs[0]['name']} from run {latest['run_id']}, sha256 {outputs[0]['sha256']}")
        return 0
    for o in outputs:
        print(storage.path(o["key"]) if len(outputs) == 1 else f"{o['name']}\t{storage.path(o['key'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "corrections":
        return check_corrections(args.file)
    if args.command == "output":
        try:
            return show_output(args)
        except (pipeline_mod.PipelineError, RunError, OSError) as error:
            print(f"soldera: {error}", file=sys.stderr)
            return 2
    try:
        pipeline = pipeline_mod.load(args.pipeline)
        storage = LocalStorage(args.store, args.store_uri)
        runner = Runner(pipeline, storage, open_run_log(args.run_log), sys.stdout, sys.stderr)
        return runner.run(start=args.start, end=args.end, force=args.force, run_id=args.run_id,
                          trigger=args.trigger)
    except (pipeline_mod.PipelineError, RunError) as error:
        print(f"soldera: {error}", file=sys.stderr)
        return 2
    except RunLogError as error:
        print(f"soldera: the run stopped: {error}", file=sys.stderr)
        return 1

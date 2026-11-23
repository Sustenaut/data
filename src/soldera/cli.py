"""The soldera command.

    soldera run PIPELINE.yaml [--from STAGE|auto] [--to STAGE] [--force]
                              [--store DIR] [--run-log FILE|bigquery:PROJECT.DATASET.TABLE] [--run-id ID] [--trigger KIND]
    soldera output PIPELINE.yaml STAGE [--name NAME] [--copy-to FILE] [--store DIR|gs://BUCKET]
    soldera corrections check FILE
    soldera app [--store DIR|gs://BUCKET] [--database FILE] [--port PORT]

`output` prints where the newest published output of a stage is kept (the
store files outputs by content hash), or copies it to FILE.

`app` serves the power-auctions app (src/soldera/app) with Streamlit, on the
newest database the merge stage published in the store, or on FILE.

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
import sys
from pathlib import Path

from soldera import __version__
from soldera.core import pipeline as pipeline_mod
from soldera.core.runlog import RunLogError, open_run_log
from soldera.core.runner import AUTO, RunError, Runner
from soldera.core.storage import LocalStorage, latest_outputs, open_store

TRIGGERS = ("manual", "schedule", "deploy", "rerun")
APP_PIPELINE = "pipelines/eex-french-power-auctions.yaml"
# Streamlit's settings for the app: light, in the plots' ink, and nothing
# sent to Streamlit. It listens where Streamlit does by default, which Cloud
# Run reaches; no address is set here.
APP_SETTINGS = {
    "server.headless": "true", "browser.gatherUsageStats": "false",
    "server.enableXsrfProtection": "true", "client.toolbarMode": "viewer",
    "theme.base": "light", "theme.primaryColor": "#2F5D7C", "theme.textColor": "#2b2b2a",
}


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
                        help="the directory stage outputs are kept in, or gs://BUCKET to read the bucket "
                             "over its API (SOLDERA_STORE)")
    app = commands.add_parser("app", help="serve the power-auctions app")
    app.add_argument("--store", default=os.environ.get("SOLDERA_STORE", "store"),
                     help="the store whose newest merged database it shows: a directory, or gs://BUCKET "
                          "(SOLDERA_STORE)")
    app.add_argument("--database", default=os.environ.get("SOLDERA_DATABASE") or None,
                     help="show this DuckDB file instead (SOLDERA_DATABASE)")
    app.add_argument("--pipeline", default=os.environ.get("SOLDERA_PIPELINE", APP_PIPELINE),
                     help="the pipeline whose merge stage made the database (SOLDERA_PIPELINE)")
    app.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8501")),
                     help="the port to serve on (PORT, as Cloud Run sets it)")
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


def copy_target(path: str) -> Path:
    """Where --copy-to writes, resolved, which must be under the working
    directory, as a pipeline file must."""
    base = Path.cwd().resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        raise RunError(f"{path} is outside {base}; --copy-to must name a file inside the working directory")
    return target


def show_output(args: argparse.Namespace) -> int:
    pipeline = pipeline_mod.load(args.pipeline)
    stage = pipeline.stage(args.stage)
    storage = open_store(args.store)
    try:
        latest, outputs = latest_outputs(storage, stage.prefix, args.name)
    except LookupError as error:
        raise RunError(f"stage {stage.name} ({stage.parser.ref()}) has published nothing in {args.store}") from error
    if not outputs:
        raise RunError(f"stage {stage.name}'s run {latest['run_id']} published no output named {args.name}")
    if args.copy_to:
        if len(outputs) > 1:
            raise RunError(f"stage {stage.name} published {len(outputs)} outputs; name one with --name: "
                           + ", ".join(o["name"] for o in outputs[:10]))
        target = copy_target(args.copy_to)
        storage.copy_to(outputs[0]["key"], target)
        print(f"{args.copy_to}: {outputs[0]['name']} from run {latest['run_id']}, sha256 {outputs[0]['sha256']}")
        return 0
    for o in outputs:
        print(storage.path(o["key"]) if len(outputs) == 1 else f"{o['name']}\t{storage.path(o['key'])}")
    return 0


def serve_app(args: argparse.Namespace) -> int:
    """Streamlit, on the app, with the store or database in its environment."""
    script = Path(__file__).resolve().parent / "app" / "streamlit_app.py"
    env = {**os.environ, "SOLDERA_STORE": str(args.store), "SOLDERA_PIPELINE": str(args.pipeline)}
    if args.database:
        env["SOLDERA_DATABASE"] = str(args.database)
    settings = {**APP_SETTINGS, "server.port": str(args.port)}
    argv = [sys.executable, "-m", "streamlit", "run", str(script), *(f"--{k}={v}" for k, v in settings.items())]
    os.execve(sys.executable, argv, env)
    return 0  # pragma: no cover - execve does not return


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "corrections":
        return check_corrections(args.file)
    if args.command == "app":
        return serve_app(args)
    if args.command == "output":
        try:
            return show_output(args)
        except (pipeline_mod.PipelineError, RunError, OSError, ValueError) as error:
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

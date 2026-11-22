"""The generic stage runner: the same for every stage of every pipeline.

For each stage it asks the pinned parser for the stage's work items, runs
each item (a sub-stage), skips items whose output is already stored, keeps
going when one item fails, writes the stage's manifest and notes, and logs a
row when the stage starts and when it ends.

Storage layout, under each stage's prefix (`NN-stage/parser@version`):

    items/<cache key>/<output name>   an item's outputs
    items/<cache key>/item.json       written last: the item is complete
    runs/<run id>/manifest.json       what the stage run did, item by item
    runs/<run id>/notes.parquet       the notes its items carry
    latest.json                       the newest run downstream stages read
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TextIO

from soldera.core import notes as notes_mod
from soldera.core.parser import Artifact, ItemResult, StageContext, WorkItem
from soldera.core.pipeline import Pipeline, Stage
from soldera.core.runlog import RunLog, code_version, host, trigger_context
from soldera.core.storage import LocalStorage

AUTO = "auto"
TRACEBACK_LINES = 20


class RunError(Exception):
    """The run cannot start as asked, such as from a stage with nothing stored before it."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id() -> str:
    """Sorts by time, unique enough for one pipeline's runs."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


@dataclass
class StageOutcome:
    stage: Stage
    status: str
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def count(self, status: str) -> int:
        return sum(1 for item in self.items if item["status"] == status)


class Runner:
    def __init__(self, pipeline: Pipeline, storage: LocalStorage, runlog: RunLog, out: TextIO, err: TextIO):
        self.pipeline = pipeline
        self.storage = storage
        self.runlog = runlog
        self.out = out
        self.err = err

    # --- which stages run -------------------------------------------------------

    def latest(self, stage: Stage) -> dict[str, Any] | None:
        return self.storage.get_json_or_none(f"{stage.prefix}/latest.json")

    def auto_start(self) -> Stage | None:
        """The earliest stage whose pinned parser has no stored run, or whose
        stored run read something other than the newest output before it."""
        previous: dict[str, Any] | None = None
        for stage in self.pipeline.stages:
            latest = self.latest(stage)
            if latest is None:
                return stage
            if previous is not None and latest.get("upstream_run_id") != previous["run_id"]:
                return stage
            previous = latest
        return None

    def plan_stages(self, start: str | None, end: str | None) -> list[Stage]:
        names = self.pipeline.names()
        if start == AUTO:
            first = self.auto_start()
            if first is None:
                return []
            begin = first.index - 1
        else:
            begin = names.index(self.pipeline.stage(start).name) if start else 0
        finish = names.index(self.pipeline.stage(end).name) if end else len(names) - 1
        if finish < begin:
            raise RunError(f"--to {end} comes before the first stage to run, {names[begin]}")
        if begin > 0:
            before = self.pipeline.stages[begin - 1]
            if self.latest(before) is None:
                raise RunError(f"no stored output of stage {before.name} ({before.parser.ref()}): "
                               f"run from {before.name} or earlier first")
        return list(self.pipeline.stages[begin:finish + 1])

    # --- running ----------------------------------------------------------------

    def run(self, *, start: str | None = None, end: str | None = None, force: bool = False,
            run_id: str | None = None, trigger: str = "manual") -> int:
        stages = self.plan_stages(start, end)
        if not stages:
            print(f"{self.pipeline.name}: every stage is up to date; nothing to run", file=self.out)
            return 0
        run_id = run_id or new_run_id()
        context = {
            "run_id": run_id, "trigger": trigger, "force": force,
            "rerun_from_stage": stages[0].name if stages[0].index > 1 else "",
            "requested_from": start or "", "requested_to": end or "",
        }
        print(f"{self.pipeline.name}: run {run_id}, stages {', '.join(s.name for s in stages)}", file=self.out)
        worst = 0
        for stage in stages:
            outcome = self.run_stage(stage, context, force)
            self.report(outcome)
            if outcome.status == "failed":
                return 1
            if outcome.status == "partial":
                worst = 1
        return worst

    def upstream(self, stage: Stage) -> tuple[list[Artifact], dict[str, Any] | None]:
        if stage.index == 1:
            return [], None
        before = self.pipeline.stages[stage.index - 2]
        latest = self.latest(before)
        if latest is None:
            raise RunError(f"no stored output of stage {before.name}")
        manifest = self.storage.get_json(latest["manifest"])
        artifacts = [Artifact.from_dict(o) for item in manifest["items"]
                     if item["status"] in ("built", "cached") for o in item["outputs"]]
        return artifacts, latest

    def row(self, stage: Stage, context: dict[str, Any], **values: Any) -> dict[str, Any]:
        row = {
            "run_id": context["run_id"], "pipeline": self.pipeline.name,
            "stage_name": stage.name, "stage_index": stage.index,
            "parser_name": stage.parser.name, "parser_version": stage.parser.version,
            "parser_code_hash": stage.parser.code_hash(), "code_version": code_version(),
            "trigger": context["trigger"], "rerun_from_stage": context["rerun_from_stage"],
            "host": host(), "trigger_context": trigger_context(),
            "config": {"options": stage.options, "force": context["force"],
                       "requested_from": context["requested_from"], "requested_to": context["requested_to"],
                       "pins": {s.name: s.parser.ref() for s in self.pipeline.stages}},
            "logged_at": now(),
        }
        row.update(values)
        return row

    def run_stage(self, stage: Stage, context: dict[str, Any], force: bool) -> StageOutcome:
        run_id = context["run_id"]
        started = now()
        self.runlog.write(self.row(stage, context, status="running", started_at=started, finished_at=None))
        parser = stage.parser()
        ctx = StageContext(self.storage, stage.options, stage.name)
        try:
            upstream, upstream_latest = self.upstream(stage)
            items = parser.plan(upstream, ctx)
        except Exception as error:  # noqa: BLE001 - any planning failure fails the stage, with its reason logged
            outcome = StageOutcome(stage, "failed", error=f"{type(error).__name__}: {error}")
            self.runlog.write(self.row(
                stage, context, status="failed", started_at=started, finished_at=now(),
                error_class=type(error).__name__, error_message=str(error),
                traceback_tail=tail(traceback.format_exc()), items=[], **counts([])))
            return outcome
        done = [self.run_item(stage, parser, ctx, item, run_id, force) for item in items]
        failed = sum(1 for d in done if d["status"] == "failed")
        status = "failed" if done and failed == len(done) else "partial" if failed else "succeeded"
        manifest_key = f"{stage.prefix}/runs/{run_id}/manifest.json"
        notes_key = f"{stage.prefix}/runs/{run_id}/notes.parquet"
        stage_notes = [n for d in done for n in d.get("notes", [])]
        self.storage.put_bytes(notes_key, notes_mod.to_parquet(stage_notes))
        self.storage.put_json(manifest_key, {
            "pipeline": self.pipeline.name, "stage": stage.name, "stage_index": stage.index,
            "parser": stage.parser.ref(), "run_id": run_id, "status": status,
            "upstream": upstream_latest, "notes": notes_key, "items": done,
        })
        if status != "failed":
            self.storage.put_json(f"{stage.prefix}/latest.json", {
                "run_id": run_id, "manifest": manifest_key, "notes": notes_key, "status": status,
                "upstream_run_id": upstream_latest["run_id"] if upstream_latest else None,
            })
        self.runlog.write(self.row(
            stage, context, status=status, started_at=started, finished_at=now(),
            upstream_manifest_uri=self.storage.uri(upstream_latest["manifest"]) if upstream_latest else None,
            output_manifest_uri=self.storage.uri(manifest_key), notes_uri=self.storage.uri(notes_key),
            notes_count=len(stage_notes), items=[log_item(d) for d in done], **counts(done)))
        return StageOutcome(stage, status, done)

    def run_item(self, stage: Stage, parser: Any, ctx: StageContext, item: WorkItem, run_id: str,
                 force: bool) -> dict[str, Any]:
        key = cache_key(stage, item, run_id)
        base = f"{stage.prefix}/items/{key}"
        started, clock = now(), time.monotonic()
        entry: dict[str, Any] = {"item_key": item.key, "cache_key": key, "started_at": started,
                                 "inputs": [{"key": a.key, "sha256": a.sha256} for a in item.inputs]}
        if not force and stage.parser.cacheable and self.storage.exists(f"{base}/item.json"):
            stored = self.storage.get_json(f"{base}/item.json")
            entry.update(status="cached", outputs=stored["outputs"], notes=stored["notes"],
                         rows_out=stored["rows_out"], produced_by_run=stored["run_id"])
        else:
            try:
                result = parser.transform(item, ctx)
                if not isinstance(result, ItemResult):
                    raise TypeError(f"{stage.parser.ref()} returned {type(result).__name__}, not ItemResult")
                outputs, rows = [], 0
                for output in result.outputs:
                    stored = self.storage.put_bytes(f"{base}/{output.name}", output.data)
                    outputs.append(Artifact(stored.key, stored.sha256, stored.size, output.name,
                                            output.media_type, item.key).to_dict())
                    rows += output.rows or 0
                source = item.inputs[0] if item.inputs else None
                item_notes = [notes_mod.record(
                    n, run_id=run_id, pipeline=self.pipeline.name, stage=stage.name,
                    parser_name=stage.parser.name, parser_version=stage.parser.version, item_key=item.key,
                    source_key=source.key if source else "", source_sha256=source.sha256 if source else "")
                    for n in result.notes]
                record = {"item_key": item.key, "run_id": run_id, "created_at": now(), "outputs": outputs,
                          "notes": item_notes, "rows_out": rows, "inputs": entry["inputs"]}
                self.storage.put_json(f"{base}/item.json", record)
                entry.update(status="built", outputs=outputs, notes=item_notes, rows_out=rows,
                             produced_by_run=run_id)
            except Exception as error:  # noqa: BLE001 - one item's failure is recorded and the rest go on
                entry.update(status="failed", outputs=[], notes=[], rows_out=0,
                             error_class=type(error).__name__, error_message=str(error),
                             traceback_tail=tail(traceback.format_exc()))
        entry["duration_ms"] = round((time.monotonic() - clock) * 1000)
        return entry

    def report(self, outcome: StageOutcome) -> None:
        stage = outcome.stage
        if outcome.error:
            print(f"{stage.name}: {stage.parser.ref()} failed: {outcome.error}", file=self.out)
            print(f"{stage.name}: {outcome.error}", file=self.err)
            return
        print(f"{stage.name}: {stage.parser.ref()} {outcome.status}: {len(outcome.items)} items, "
              f"{outcome.count('built')} built, {outcome.count('cached')} cached, "
              f"{outcome.count('failed')} failed", file=self.out)
        for item in outcome.items:
            if item["status"] == "failed":
                print(f"{stage.name}: {item['item_key']} failed: {item['error_class']}: {item['error_message']}",
                      file=self.err)


def cache_key(stage: Stage, item: WorkItem, run_id: str) -> str:
    """Same parser version, same inputs, same parameters: same key, so the
    stored output is reused. A stage that is not cacheable keys by run."""
    basis: dict[str, Any] = {"parser": stage.parser.ref(), "inputs": [a.sha256 for a in item.inputs],
                             "params": [list(p) for p in item.params]}
    if not stage.parser.cacheable:
        basis["run"] = run_id
        basis["item"] = item.key
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:32]


def tail(text: str) -> str:
    return "\n".join(text.rstrip().splitlines()[-TRACEBACK_LINES:])


def counts(done: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "items_total": len(done),
        "items_succeeded": sum(1 for d in done if d["status"] == "built"),
        "items_cached": sum(1 for d in done if d["status"] == "cached"),
        "items_failed": sum(1 for d in done if d["status"] == "failed"),
        "rows_out": sum(d.get("rows_out", 0) for d in done),
        "bytes_out": sum(o["size"] for d in done for o in d.get("outputs", [])),
    }


def log_item(entry: dict[str, Any]) -> dict[str, Any]:
    first_in = entry["inputs"][0] if entry["inputs"] else {}
    first_out = entry["outputs"][0] if entry["outputs"] else {}
    return {
        "item_key": entry["item_key"], "status": entry["status"],
        "input_key": first_in.get("key"), "input_sha256": first_in.get("sha256"),
        "output_key": first_out.get("key"), "output_sha256": first_out.get("sha256"),
        "rows_out": entry.get("rows_out", 0), "bytes": sum(o["size"] for o in entry["outputs"]),
        "started_at": entry["started_at"], "duration_ms": entry["duration_ms"],
        "produced_by_run": entry.get("produced_by_run"), "notes_count": len(entry.get("notes", [])),
        "error_class": entry.get("error_class"), "error_message": entry.get("error_message"),
        "traceback_tail": entry.get("traceback_tail"),
    }

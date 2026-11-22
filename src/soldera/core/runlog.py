"""The pipeline run log: one row per stage per run, written twice, as
`running` when the stage starts and with its outcome when it ends. Rows are
only ever appended; the newest row of a run and stage is its state.

JsonlRunLog appends rows to a local file. The BigQuery log writes the same
rows to `pipeline_stage_runs`."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any, Protocol


class RunLog(Protocol):
    def write(self, row: dict[str, Any]) -> None: ...


class JsonlRunLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def host() -> str:
    if os.environ.get("CLOUD_RUN_JOB"):
        return "cloud-run"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github-actions"
    return "local"


# Environment variables that tie a run to what started it, by the field
# they fill in trigger_context.
TRIGGER_VARIABLES = {
    "github_repository": "GITHUB_REPOSITORY",
    "github_workflow": "GITHUB_WORKFLOW",
    "github_run_id": "GITHUB_RUN_ID",
    "github_run_attempt": "GITHUB_RUN_ATTEMPT",
    "github_sha": "GITHUB_SHA",
    "github_actor": "GITHUB_ACTOR",
    "cloud_run_job": "CLOUD_RUN_JOB",
    "cloud_run_execution": "CLOUD_RUN_EXECUTION",
    "cloud_run_task_attempt": "CLOUD_RUN_TASK_ATTEMPT",
}


def trigger_context() -> dict[str, str]:
    context = {field: os.environ[var] for field, var in TRIGGER_VARIABLES.items() if os.environ.get(var)}
    if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        context["github_run_url"] = (
            f"{server}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    context["machine"] = platform.node()
    return context


def code_version() -> str:
    return os.environ.get("SOLDERA_COMMIT") or os.environ.get("GITHUB_SHA") or "dev"

"""The pipeline run log: one row per stage per run, written twice, as
`running` when the stage starts and with its outcome when it ends. Rows are
only ever appended; the newest row of a run and stage is its state.

JsonlRunLog appends rows to a local file. BigQueryRunLog streams the same
rows into a BigQuery table, `pipeline_stage_runs`, whose schema is
schemas/pipeline_stage_runs.json beside this module (the Terraform that makes
the table reads the same file). `open_run_log` picks one from --run-log:
`bigquery:PROJECT.DATASET.TABLE`, or else a file path.

A row that cannot be written stops the run, as any failure does: a batch
run nobody can see did not happen as far as anyone knows."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Protocol

from ingest import setting
from ingest.core import http

SCHEMA_PATH = Path(__file__).with_name("schemas") / "pipeline_stage_runs.json"
BIGQUERY = "bigquery:"
TABLE = re.compile(r"^(?P<project>[a-z][a-z0-9-]{4,28}[a-z0-9])\.(?P<dataset>\w{1,1024})\.(?P<table>[\w-]{1,1024})$")
SCOPE = "https://www.googleapis.com/auth/bigquery.insertdata"


class RunLog(Protocol):
    def write(self, row: dict[str, Any]) -> None: ...


class JsonlRunLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


class RunLogError(RuntimeError):
    """A run log row could not be written."""


def schema() -> list[dict[str, Any]]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class BigQueryRunLog:
    """Streams each row into a BigQuery table with insertAll, signed in with
    Google's application default credentials: the job's service account on
    Cloud Run, workload identity on GitHub Actions, `gcloud auth
    application-default login` on a laptop. BIGQUERY_URL points it elsewhere,
    for tests."""

    def __init__(self, target: str):
        match = TABLE.match(target)
        if not match:
            raise RunLogError(f"{target!r} is not PROJECT.DATASET.TABLE")
        self.table = target
        base = os.environ.get("BIGQUERY_URL", "https://bigquery.googleapis.com").rstrip("/")
        self.url = (f"{base}/bigquery/v2/projects/{match['project']}/datasets/{match['dataset']}"
                    f"/tables/{match['table']}/insertAll")
        self.columns = {f["name"]: f for f in schema()}
        self._credentials = None

    def credentials(self):  # noqa: ANN201 - google-auth's own type
        if self._credentials is None:
            import google.auth  # noqa: PLC0415 - only a BigQuery run log needs it
            from google.auth import exceptions  # noqa: PLC0415

            try:
                self._credentials, _ = google.auth.default(scopes=[SCOPE])
            except exceptions.GoogleAuthError as error:
                raise RunLogError(f"cannot sign in to write the run log to {self.table}: {error}") from error
        return self._credentials

    def encode(self, row: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(row) - set(self.columns))
        if unknown:
            raise RunLogError(f"the run log row has fields {self.table}'s schema lacks: {', '.join(unknown)}")
        return {k: json.dumps(v, sort_keys=True, default=str) if self.columns[k]["type"] == "JSON" and v is not None
                else v for k, v in row.items()}

    def write(self, row: dict[str, Any]) -> None:
        from google.auth import exceptions  # noqa: PLC0415

        encoded = self.encode(row)
        # The same row sent twice (a retried request) is kept once.
        insert_id = hashlib.sha256(json.dumps(encoded, sort_keys=True, default=str).encode()).hexdigest()[:32]
        body = json.dumps({"rows": [{"insertId": insert_id, "json": encoded}]}, default=str).encode()
        headers = {"Content-Type": "application/json"}
        try:
            self.credentials().before_request(http.GoogleTransport(), "POST", self.url, headers)
            answer = http.send("POST", self.url, body, headers=headers, timeout=30)
        except (http.HttpError, exceptions.GoogleAuthError) as error:
            raise RunLogError(f"cannot write the run log to {self.table}: {error}") from error
        errors = json.loads(answer.body or b"{}").get("insertErrors")
        if errors:
            reasons = "; ".join(f"{e.get('location') or 'row'}: {e.get('message')}"
                                for entry in errors for e in entry.get("errors", []))
            raise RunLogError(f"{self.table} refused the run log row: {reasons}")


def open_run_log(target: str) -> RunLog:
    if target.startswith(BIGQUERY):
        return BigQueryRunLog(target[len(BIGQUERY):])
    return JsonlRunLog(target)


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
    return setting("COMMIT") or os.environ.get("GITHUB_SHA") or "dev"

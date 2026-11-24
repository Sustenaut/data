"""Notes for readers of the data, written once by the stage that finds them.

Each stage run writes its notes to `notes.parquet` beside its manifest. Every
other view of a note (BigQuery's `stage_notes`, DuckDB's `data_notes`) reads or
copies these rows, never works them out again, so they cannot disagree."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ingest.core.parser import Note

FIELDS = (
    "note_id",
    "run_id",
    "pipeline",
    "stage",
    "parser_name",
    "parser_version",
    "item_key",
    "severity",
    "kind",
    "subject",
    "message",
    "source_key",
    "source_sha256",
)

SCHEMA = pa.schema([(name, pa.string()) for name in FIELDS])

SEVERITIES = ("info", "warning")


def note_id(kind: str, subject: str, source: str) -> str:
    """Stable across runs: the same finding about the same input has the same id."""
    return hashlib.sha256(f"{kind}\x1f{subject}\x1f{source}".encode()).hexdigest()[:16]


def record(  # noqa: PLR0913 - a run log row's columns, all keyword-only
    note: Note,
    *,
    run_id: str,
    pipeline: str,
    stage: str,
    parser_name: str,
    parser_version: str,
    item_key: str,
    source_key: str,
    source_sha256: str,
) -> dict[str, Any]:
    if note.severity not in SEVERITIES:
        raise ValueError(f"note severity must be one of {', '.join(SEVERITIES)}, not {note.severity!r}")
    return {
        "note_id": note_id(note.kind, note.subject, source_sha256 or item_key),
        "run_id": run_id,
        "pipeline": pipeline,
        "stage": stage,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "item_key": item_key,
        "severity": note.severity,
        "kind": note.kind,
        "subject": note.subject,
        "message": note.message,
        "source_key": source_key,
        "source_sha256": source_sha256,
    }


def to_parquet(rows: list[dict[str, Any]]) -> bytes:
    table = pa.Table.from_pylist([{f: row.get(f, "") for f in FIELDS} for row in rows], schema=SCHEMA)
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def from_parquet(data: bytes) -> list[dict[str, Any]]:
    return pq.read_table(io.BytesIO(data)).to_pylist()

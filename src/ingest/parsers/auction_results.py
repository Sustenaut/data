"""The database stage: every auction_results file into the app's DuckDB.

It reads any provider's canonical `auction_results` Parquet files and writes
one DuckDB file holding:

    auction_results       every row, by auction date, auction and source row
    data_notes            every note of every stage before, copied from their
                          notes.parquet, and this stage's own
    build_info            one row: what was built, from what, and when
    auctions              a view: one row per auction, with its totals
    auction_technologies  a view: one row per auction and technology

It fails when two rows describe the same auction, region and technology, or
one auction comes from two files: the app would show both.

Its own notes are about the series of auctions as a whole, which no single
file can show: a gap in the auction numbers, a number used twice, or a
production month with no auction."""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from ingest.canonical import auction_results
from ingest.core import notes as notes_mod
from ingest.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register
from ingest.core.runlog import trigger_context

PARQUET = "application/vnd.apache.parquet"
UNIQUE = ("auction_id", "segment_level", "region", "technology")

VIEWS = {
    "auctions": """
        SELECT provider, market, certificate_type, auction_id, auction_number, auction_date,
               production_period_start, production_period_end,
               count(*) AS segments,
               max(bidders_count) AS bidders_count,
               sum(winners_count) AS winners_count,
               sum(volume_offered_mwh) AS volume_offered_mwh,
               sum(volume_allocated_mwh) AS volume_allocated_mwh,
               sum(volume_allocated_mwh * price_weighted_avg_eur_mwh)
                 / nullif(sum(CASE WHEN price_weighted_avg_eur_mwh IS NOT NULL THEN volume_allocated_mwh END), 0)
                 AS price_weighted_avg_eur_mwh
        FROM auction_results
        GROUP BY ALL
        ORDER BY auction_date, auction_id""",
    "auction_technologies": """
        SELECT provider, market, auction_id, auction_number, auction_date,
               production_period_start, production_period_end, technology,
               count(*) AS regions,
               sum(winners_count) AS winners_count,
               sum(volume_offered_mwh) AS volume_offered_mwh,
               sum(volume_allocated_mwh) AS volume_allocated_mwh,
               sum(volume_allocated_mwh * price_weighted_avg_eur_mwh)
                 / nullif(sum(CASE WHEN price_weighted_avg_eur_mwh IS NOT NULL THEN volume_allocated_mwh END), 0)
                 AS price_weighted_avg_eur_mwh
        FROM auction_results
        GROUP BY ALL
        ORDER BY auction_date, auction_id, technology""",
}


class Duplicate(ValueError):
    pass


def check_unique(rows: list[dict[str, Any]]) -> None:
    files: dict[str, set[str]] = defaultdict(set)
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        files[row["auction_id"]].add(row["source_name"])
        key = tuple(row[k] for k in UNIQUE)
        if key in seen:
            first = seen[key]
            raise Duplicate(f"{row['auction_id']} has {row['region']} {row['technology']} twice: "
                            f"{first['source_name']} row {first['source_row']} and "
                            f"{row['source_name']} row {row['source_row']}")
        seen[key] = row
    for auction, names in sorted(files.items()):
        if len(names) > 1:
            raise Duplicate(f"{auction} comes from {len(names)} files: {', '.join(sorted(names))}")


def auctions_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per auction, by auction date then id."""
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        found.setdefault(row["auction_id"], row)
    return sorted(found.values(), key=lambda r: (r["auction_date"], r["auction_id"]))


def label(auction: dict[str, Any]) -> str:
    return f"{auction['auction_id']} ({auction['auction_date']:%Y-%m-%d})"


def months(first: date, last: date) -> list[date]:
    found, at = [], first.replace(day=1)
    while at <= last:
        found.append(at)
        at = at.replace(year=at.year + 1, month=1) if at.month == 12 else at.replace(month=at.month + 1)
    return found


def series_notes(rows: list[dict[str, Any]]) -> list[Note]:
    """What the series of auctions shows: numbers skipped between two
    auctions in a row, a number used by two auctions of one numbering, and
    production months with no auction. A number less than half the one
    before starts a new numbering (EEX restarted at 6 in 2026); a smaller
    drop is a number used again."""
    auctions = auctions_of(rows)
    notes: list[Note] = []
    numbering, last = 0, None
    by_number: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for auction in auctions:
        number = whole(auction["auction_number"])
        if number is None:
            last = None  # an auction whose file gives no number may be the missing one
            continue
        if last is not None:
            before, previous = last
            if number < previous / 2:
                numbering += 1
            elif number > previous + 1:
                missing = f"{previous + 1}" if number == previous + 2 else f"{previous + 1} to {number - 1}"
                notes.append(Note("auction_number_gap",
                                  f"No results for auction number {missing}: the auctions go from "
                                  f"{label(before)} to {label(auction)}.",
                                  subject=f"{before['auction_id']}..{auction['auction_id']}", severity="info"))
        by_number[(numbering, auction["auction_number"])].append(auction)
        last = (auction, number)
    for (_, number), users in by_number.items():
        if len(users) > 1:
            notes.append(Note("auction_number_repeated",
                              f"Auction number {number} is used by {len(users)} auctions: "
                              f"{', '.join(label(u) for u in users)}.",
                              subject=f"auction number {number}", severity="info"))
    produced = {a["production_period_start"].replace(day=1) for a in auctions}
    if produced:
        for month in months(min(produced), max(produced)):
            if month not in produced:
                notes.append(Note("production_month_missing",
                                  f"No auction results for production in {month:%B %Y}.",
                                  subject=f"{month:%Y-%m}"))
    return notes


def whole(number: str | None) -> int | None:
    """An auction number's main part: 47 for "47-2"."""
    head = (number or "").split("-")[0]
    return int(head) if head.isdigit() else None


def table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)


@register
class Merge(Parser):
    name = "auction-results-duckdb"
    version = "1.1.0"

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        files = sorted((a for a in upstream if a.media_type == PARQUET), key=lambda a: a.item_key)
        if not files:
            raise ValueError("there are no auction_results files to merge")
        name = str(ctx.options.get("database", "auction_results.duckdb"))
        return [WorkItem(key=name, inputs=(*files, *ctx.earlier_notes))]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        import duckdb  # noqa: PLC0415 - only this stage needs it

        earlier = [a for a in item.inputs if a in ctx.earlier_notes]
        files = [a for a in item.inputs if a not in ctx.earlier_notes]
        rows = [r for a in files for r in auction_results.read(ctx.read(a)).to_pylist()]
        rows.sort(key=lambda r: (r["auction_date"], r["auction_id"], r["source_row"]))
        check_unique(rows)
        own = series_notes(rows)
        notes = [n for a in earlier for n in notes_mod.from_parquet(ctx.read(a))]
        notes += ctx.note_records(own, item)
        auctions = auctions_of(rows)
        trigger = trigger_context()
        build = {
            "pipeline": ctx.pipeline, "stage": ctx.stage, "parser": self.ref(), "run_id": ctx.run_id,
            # Where the run can be seen: its GitHub Actions run, or its Cloud Run execution.
            "github_run_url": trigger.get("github_run_url"), "cloud_run_execution": trigger.get("cloud_run_execution"),
            "built_at": datetime.now(UTC).replace(tzinfo=None),
            "files": len(files), "rows": len(rows), "auctions": len(auctions), "notes": len(notes),
            "first_auction_date": auctions[0]["auction_date"] if auctions else None,
            "last_auction_date": auctions[-1]["auction_date"] if auctions else None,
            "inputs": json.dumps([{"name": a.item_key or a.name, "sha256": a.sha256} for a in item.inputs]),
        }
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "merge.duckdb"
            con = duckdb.connect(str(path))
            try:
                results = table(rows, auction_results.SCHEMA)  # noqa: F841 - read by name in the SQL below
                noted = table(notes, notes_mod.SCHEMA)  # noqa: F841
                info = pa.Table.from_pylist([build])  # noqa: F841
                con.execute("CREATE TABLE auction_results AS SELECT * FROM results")
                con.execute("CREATE TABLE data_notes AS SELECT * FROM noted")
                con.execute("CREATE TABLE build_info AS SELECT * FROM info")
                for view, sql in VIEWS.items():
                    con.execute(f"CREATE VIEW {view} AS {sql}")
                con.execute("CHECKPOINT")
            finally:
                con.close()
            data = path.read_bytes()
        return ItemResult([Output(item.key, data, "application/vnd.duckdb", rows=len(rows))], own)

"""auction_results: one row per auction per segment, common to every
provider of certificate auctions (EEX's French GO auctions first; other
countries' GO auctions or I-REC sales later).

A segment is the breakdown a provider publishes; `segment_level` says which,
so totals are never added to the rows they total. Units are in the column
names, so a plot cannot mix MWh and GWh. A provider's columns with no
canonical home go in `extras`, as JSON.

The parse stage writes it with `write`, which refuses a table that does not
match; the database stage creates its DuckDB table from SCHEMA."""

from __future__ import annotations

import io
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

NAME = "auction_results"
VERSION = "1.0.0"

SCHEMA = pa.schema([
    pa.field("provider", pa.string(), nullable=False),
    pa.field("market", pa.string(), nullable=False),
    pa.field("certificate_type", pa.string(), nullable=False),
    pa.field("energy_carrier", pa.string(), nullable=False),
    pa.field("auction_id", pa.string(), nullable=False),
    pa.field("auction_number", pa.string()),
    pa.field("auction_date", pa.date32(), nullable=False),
    pa.field("production_period_start", pa.date32(), nullable=False),
    pa.field("production_period_end", pa.date32(), nullable=False),
    pa.field("segment_level", pa.string(), nullable=False),
    pa.field("region", pa.string()),
    pa.field("technology", pa.string()),
    pa.field("volume_offered_mwh", pa.float64()),
    pa.field("volume_allocated_mwh", pa.float64()),
    pa.field("price_weighted_avg_eur_mwh", pa.float64()),
    pa.field("price_min_eur_mwh", pa.float64()),
    pa.field("price_max_eur_mwh", pa.float64()),
    pa.field("reserve_price_eur_mwh", pa.float64()),
    pa.field("bidders_count", pa.int32()),
    pa.field("winners_count", pa.int32()),
    pa.field("extras", pa.string()),
    pa.field("source_name", pa.string(), nullable=False),
    pa.field("source_sha256", pa.string(), nullable=False),
    pa.field("source_sheet", pa.string()),
    pa.field("source_row", pa.int32(), nullable=False),
    pa.field("parser_name", pa.string(), nullable=False),
    pa.field("parser_version", pa.string(), nullable=False),
], metadata={"schema": f"{NAME}@{VERSION}"})

TECHNOLOGIES = ("wind", "solar", "hydro", "thermal", "other")
SEGMENT_LEVELS = ("region_x_technology", "region", "technology", "total")


def write(rows: list[dict[str, Any]]) -> bytes:
    """The rows as Parquet, in SCHEMA; a missing or extra column, a wrong
    type or a null where none is allowed is refused."""
    names = set(SCHEMA.names)
    for index, row in enumerate(rows):
        if set(row) != names:
            missing, extra = sorted(names - set(row)), sorted(set(row) - names)
            raise ValueError(f"row {index} does not match {NAME}: missing {missing}, extra {extra}")
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    for field in SCHEMA:
        if not field.nullable and table.column(field.name).null_count:
            raise ValueError(f"{NAME}.{field.name} may not be empty")
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def read(data: bytes) -> pa.Table:
    return pq.read_table(io.BytesIO(data))

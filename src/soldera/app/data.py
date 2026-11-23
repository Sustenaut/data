"""What the power-auctions app plots, from the merge stage's DuckDB.

EEX publishes no single bids. For each auction it gives, for each region and
technology, the volume offered and sold and the volume-weighted average price
of what sold. Those region segments are the population every plot here is
drawn from: a "price" is one segment's average price, and a distribution is
of segments (or of the MWh they sold) across regions and auctions.

Everything here is plain Python over the rows DuckDB returns, so it is tested
without Streamlit and gives the same numbers wherever it runs."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

DATABASE = "power-auctions.duckdb"

# Wind, solar, hydro, thermal: the order EEX lists them in, and their colours,
# soft but told apart by anyone (checked for colour-blind separation).
TECHNOLOGIES = ("wind", "solar", "hydro", "thermal")
# The technologies chosen, combined into one: what a segment's technology
# becomes when Filters.combine is set, after them in every order.
ALL = "all"
ORDER = (*TECHNOLOGIES, ALL)
COLOURS = {"wind": "#5A86E0", "solar": "#E09A10", "hydro": "#10A585", "thermal": "#CC5F3A", ALL: "#3E9A4F"}
LABELS = {"wind": "Wind (onshore)", "solar": "Solar", "hydro": "Hydro", "thermal": "Thermal", ALL: "Combined"}

# The statistics a point in time can show, in the order they are offered.
STATISTICS = ("max", "p90", "mean", "median", "p10", "min")
STATISTIC_LABELS = {"max": "Highest", "p90": "90th percentile", "mean": "Mean", "median": "Median",
                    "p10": "10th percentile", "min": "Lowest"}

DATE_BY = {"auction": "auction_date", "production": "production_period_start"}


class DataError(Exception):
    """The store has no database to show, or it is not the one expected."""


@dataclass(frozen=True)
class Filters:
    """Which segments a plot is drawn from. Dates are inclusive; `date_by`
    says whether they are auction dates or production months."""

    start: date | None = None
    end: date | None = None
    date_by: str = "auction"
    technologies: tuple[str, ...] = TECHNOLOGIES
    regions: tuple[str, ...] | None = None
    min_segment_mwh: float = 0.0
    max_segment_mwh: float | None = None
    min_share_sold: float = 0.0
    max_share_sold: float = 1.0
    min_bidders: int = 0
    max_bidders: int | None = None
    auction_numbers: tuple[int, int] | None = None
    # The technologies kept, as one (ALL) rather than each on its own.
    combine: bool = False


@dataclass
class Segment:
    auction_id: str
    auction_number: int | None
    auction_date: date
    production_month: date
    region: str
    technology: str
    offered_mwh: float
    sold_mwh: float
    price: float | None
    winners: int | None
    bidders: int | None
    share_sold: float | None

    def at(self, date_by: str) -> date:
        return self.auction_date if date_by == "auction" else self.production_month


@dataclass
class Choices:
    """What the filters can be set to, from the whole database."""

    first_auction: date
    last_auction: date
    first_production: date
    last_production: date
    regions: list[str]
    lowest_number: int | None
    highest_number: int | None
    most_bidders: int
    largest_segment_mwh: float = 0.0
    built: dict[str, Any] = field(default_factory=dict)


SEGMENTS_SQL = """
    WITH auctions AS (
        SELECT auction_id,
               max(bidders_count) AS bidders,
               sum(volume_allocated_mwh) / nullif(sum(volume_offered_mwh), 0) AS share_sold
        FROM auction_results
        WHERE segment_level = 'region_x_technology'
        GROUP BY auction_id
    )
    SELECT r.auction_id, TRY_CAST(r.auction_number AS INTEGER), r.auction_date, r.production_period_start,
           r.region, r.technology, coalesce(r.volume_offered_mwh, 0), coalesce(r.volume_allocated_mwh, 0),
           r.price_weighted_avg_eur_mwh, r.winners_count, a.bidders, a.share_sold
    FROM auction_results r JOIN auctions a USING (auction_id)
    WHERE r.segment_level = 'region_x_technology'
    ORDER BY r.auction_date, r.auction_id, r.region, r.technology
"""


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)


def all_segments(con: duckdb.DuckDBPyConnection) -> list[Segment]:
    return [Segment(*row) for row in con.execute(SEGMENTS_SQL).fetchall()]


def choices(con: duckdb.DuckDBPyConnection, segments: list[Segment]) -> Choices:
    if not segments:
        raise DataError("the database holds no region and technology results")
    numbers = [s.auction_number for s in segments if s.auction_number is not None]
    built: dict[str, Any] = {}
    try:
        cursor = con.execute("SELECT * FROM build_info")
        row = cursor.fetchone()
        if row is not None:
            built = dict(zip([d[0] for d in cursor.description], row, strict=True))
    except duckdb.CatalogException:
        built = {}
    return Choices(
        first_auction=min(s.auction_date for s in segments),
        last_auction=max(s.auction_date for s in segments),
        first_production=min(s.production_month for s in segments),
        last_production=max(s.production_month for s in segments),
        regions=sorted({s.region for s in segments}),
        lowest_number=min(numbers) if numbers else None,
        highest_number=max(numbers) if numbers else None,
        most_bidders=max((s.bidders or 0) for s in segments),
        largest_segment_mwh=max(s.sold_mwh for s in segments),
        built=built,
    )


def select(segments: list[Segment], filters: Filters) -> list[Segment]:
    """The segments the filters keep, priced or not."""
    kept = []
    for s in segments:
        when = s.at(filters.date_by)
        if filters.start and when < filters.start or filters.end and when > filters.end:
            continue
        if s.technology not in filters.technologies:
            continue
        if filters.regions is not None and s.region not in filters.regions:
            continue
        if s.sold_mwh < filters.min_segment_mwh:
            continue
        if filters.max_segment_mwh is not None and s.sold_mwh > filters.max_segment_mwh:
            continue
        share = s.share_sold if s.share_sold is not None else 0.0
        if not filters.min_share_sold <= share <= filters.max_share_sold:
            continue
        if (s.bidders or 0) < filters.min_bidders:
            continue
        if filters.max_bidders is not None and (s.bidders or 0) > filters.max_bidders:
            continue
        if filters.auction_numbers is not None:
            low, high = filters.auction_numbers
            if s.auction_number is None or not low <= s.auction_number <= high:
                continue
        kept.append(replace(s, technology=ALL) if filters.combine else s)
    return kept


def volume_steps(largest: float) -> list[float]:
    """The volumes a segment cutoff can be set to: 0, then 1, 2 and 5 times
    each power of ten, up to the first that holds the largest segment. A
    slider over these gives small volumes as much room as large ones."""
    steps, scale = [0.0], 1.0
    while True:
        for factor in (1, 2, 5):
            steps.append(factor * scale)
            if factor * scale >= largest:
                return steps
        scale *= 10


def run_link(built: dict[str, Any], execution_url: str | None = None) -> str | None:
    """Where to see the run that built the database: its GitHub Actions run
    when one started it, or else its Cloud Run execution, through
    `execution_url` (with {execution} in it)."""
    if built.get("github_run_url"):
        return str(built["github_run_url"])
    if built.get("cloud_run_execution") and execution_url:
        return execution_url.replace("{execution}", str(built["cloud_run_execution"]))
    return None


def weighted_quantile(pairs: list[tuple[float, float]], q: float) -> float | None:
    """The q quantile of values with weights, [(value, weight)]. Each value
    stands at the middle of its weight, and between two values the quantile
    is interpolated, so with equal weights it is the usual median."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    positions, running = [], 0.0
    for _, w in pairs:
        positions.append((running + w / 2) / total)
        running += w
    if q <= positions[0]:
        return pairs[0][0]
    if q >= positions[-1]:
        return pairs[-1][0]
    for i in range(1, len(pairs)):
        if q <= positions[i]:
            low, high = positions[i - 1], positions[i]
            share = (q - low) / (high - low) if high > low else 0.0
            return pairs[i - 1][0] + share * (pairs[i][0] - pairs[i - 1][0])
    return pairs[-1][0]  # pragma: no cover - the loop always returns


def statistics(priced: list[Segment], weighted: bool) -> dict[str, float | None]:
    """min, p10, median, mean, p90 and max of the segments' prices; the
    percentiles and mean weighted by MWh sold when `weighted`."""
    if not priced:
        return dict.fromkeys(STATISTICS)
    pairs = [(s.price, s.sold_mwh if weighted else 1.0) for s in priced if s.price is not None]
    total = sum(w for _, w in pairs)
    return {
        "min": min(v for v, _ in pairs),
        "p10": weighted_quantile(pairs, 0.10),
        "median": weighted_quantile(pairs, 0.50),
        "mean": sum(v * w for v, w in pairs) / total if total else None,
        "p90": weighted_quantile(pairs, 0.90),
        "max": max(v for v, _ in pairs),
    }


def bin_edges(prices: list[float], bins: int, spacing: str) -> list[float]:
    """`bins` bins over the prices' range, equal in width ("linear") or in
    ratio ("log"), which spreads the many low prices out."""
    if bins < 1:
        raise ValueError("there must be at least one bin")
    low, high = min(prices), max(prices)
    if spacing == "log":
        low = max(low, 0.01)
        if high <= low:
            high = low * 1.01
        return [low * (high / low) ** (i / bins) for i in range(bins)] + [high]
    if high <= low:
        high = low + 0.01
    step = (high - low) / bins
    return [low + i * step for i in range(bins)] + [high]


@dataclass
class Distribution:
    edges: list[float]
    # By technology: what each bin holds, in segments or MWh as asked.
    heights: dict[str, list[float]]
    totals: dict[str, float]
    unit: str


def distribution(selected: list[Segment], bins: int, spacing: str = "linear",
                 weight: str = "mwh") -> Distribution | None:
    """The price distribution of each technology on the same bins. A segment
    adds 1 to its bin, or its MWh sold when `weight` is "mwh". Segments that
    sold nothing have no price and are left out (see `summary`)."""
    priced = [s for s in selected if s.price is not None]
    if not priced:
        return None
    edges = bin_edges([s.price for s in priced], bins, spacing)
    technologies = [t for t in ORDER if any(s.technology == t for s in priced)]
    heights = {t: [0.0] * bins for t in technologies}
    for s in priced:
        heights[s.technology][bin_index(edges, s.price)] += s.sold_mwh if weight == "mwh" else 1.0
    totals = {t: sum(h) for t, h in heights.items()}
    return Distribution(edges, heights, totals, "MWh" if weight == "mwh" else "segments")


def bin_index(edges: list[float], value: float) -> int:
    """The bin `value` falls in: [edge, next edge), the last one closed."""
    last = len(edges) - 2
    if value >= edges[-1]:
        return last
    for i in range(last + 1):
        if value < edges[i + 1]:
            return i
    return last  # pragma: no cover - the comparison above catches it


def summary(selected: list[Segment], weighted: bool) -> list[dict[str, Any]]:
    """One row per technology: what the plot is drawn from, and what it
    leaves out."""
    rows = []
    for technology in ORDER:
        mine = [s for s in selected if s.technology == technology]
        if not mine:
            continue
        priced = [s for s in mine if s.price is not None]
        stats = statistics(priced, weighted)
        rows.append({
            "technology": technology,
            "auctions": len({s.auction_id for s in mine}),
            "segments": len(priced),
            "unsold_segments": len(mine) - len(priced),
            "mwh_sold": sum(s.sold_mwh for s in mine),
            **stats,
        })
    return rows


def over_time(selected: list[Segment], date_by: str, weighted: bool) -> list[dict[str, Any]]:
    """One point per auction and technology: the statistics of its regions'
    prices, by auction date or production month."""
    groups: dict[tuple[str, str], list[Segment]] = {}
    for s in selected:
        groups.setdefault((s.auction_id, s.technology), []).append(s)
    points = []
    for (auction_id, technology), mine in groups.items():
        priced = [s for s in mine if s.price is not None]
        if not priced:
            continue
        first = mine[0]
        points.append({
            "auction_id": auction_id,
            "auction_number": first.auction_number,
            "auction_date": first.auction_date,
            "production_month": first.production_month,
            "at": first.at(date_by),
            "technology": technology,
            "regions": len(priced),
            "unsold_regions": len(mine) - len(priced),
            "mwh_sold": sum(s.sold_mwh for s in mine),
            "share_sold": first.share_sold,
            "bidders": first.bidders,
            **statistics(priced, weighted),
        })
    points.sort(key=lambda p: (p["at"], p["auction_id"], ORDER.index(p["technology"])))
    return points


# Finding the database: the merge stage's newest published output, in the store.

def published_database(store: str | Path, pipeline_file: str | Path, stage_name: str = "merge"
                       ) -> tuple[str, str, Any]:
    """The key and sha256 of the newest power-auctions.duckdb the pipeline's
    merge stage published in the store, and the store to read it from: a
    directory, or gs://BUCKET read over its API."""
    from soldera.core import pipeline as pipeline_mod  # noqa: PLC0415
    from soldera.core.storage import latest_outputs, open_store  # noqa: PLC0415

    stage = pipeline_mod.load(pipeline_file).stage(stage_name)
    storage = open_store(store)
    try:
        latest, outputs = latest_outputs(storage, stage.prefix, DATABASE)
    except LookupError as error:
        raise DataError(f"the {stage_name} stage ({stage.parser.ref()}) has published nothing in {store}") from error
    if len(outputs) != 1:
        raise DataError(f"run {latest['run_id']} of the {stage_name} stage published {len(outputs)} {DATABASE}")
    return outputs[0]["key"], outputs[0]["sha256"], storage


def local_copy(storage: Any, key: str, sha256: str, directory: str | Path | None = None) -> Path:
    """A copy of the database on local disk, named by its hash, so the store
    is read once per version."""
    directory = Path(directory or tempfile.gettempdir()) / "soldera-app"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{sha256}.duckdb"
    if not target.exists():
        partial = target.with_suffix(".partial")
        storage.copy_to(key, partial)
        partial.replace(target)
    return target

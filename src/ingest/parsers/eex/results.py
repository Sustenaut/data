"""Stage 4, parse: one EEX results file into canonical auction_results rows.

eex-french-auction@1.0.0 reads one file the select stage kept, xlsx or csv,
and writes `results.parquet` in ingest.canonical.auction_results. Every era
of EEX's files (2019 to now) has the same layout:

    Aggregated Auction Results
    Number of Participants to the Auction | 37
    Région / Region | Technologie / Technology | Total Volume Auctionned |
        Total Volume Sold | Weighted Average Price (€ / MWh) |
        [My Total Volume | My Weighted Average Price (€ / MWh) |]
        Number of winners per couple region/technology
    one row per region and technology ...

From the file name: the auction date, the production month, and EEX's
auction number (with a round, for a second auction in one month), as in
20230315_November_2022_47_2_GLOBAL_Results_detailedresults.xlsx. From the
sheet: the participants and the rows. Columns are found by their headers.

What it does with what EEX writes:

- text that was UTF-8 read as Windows-1252 ("RÃ©gion", "â‚¬") is repaired;
- csv files use ";" and decimal commas; they are UTF-8, or Windows-1252;
- "-" is nothing: no volume sold is 0 MWh, and no price is no price;
- regions become ISO 3166-2 codes and technologies wind, solar, hydro or
  thermal; EEX's own labels are kept in `extras`.

The file fails, and with it the stage, when it does not hold what is
expected: no participant count, a header or region or technology it does not
know, the same region and technology twice, more sold than offered, a
negative number, or a price with nothing sold.

A mistake in EEX's own file is corrected by a rule in the corrections file
the stage's options name (see ingest.core.corrections): the rule gives the
row as EEX published it and what to do, and the parser applies it to the
rows it read before checking them. A rule that no longer matches fails the
file, so a corrected file from EEX is noticed."""

from __future__ import annotations

import calendar
import csv
import io
import json
import posixpath
import re
from datetime import date
from typing import Any

from ingest.canonical import auction_results
from ingest.core import corrections
from ingest.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register

NAME = re.compile(
    r"^(?P<date>\d{8})_(?P<month>[a-z]+)_(?P<year>\d{4})"
    r"(?:_(?P<number>\d+)(?:_(?P<round>\d+))?)?_global_?results",
    re.IGNORECASE,
)
MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}

REGIONS = {
    "auvergne-rhône-alpes": "FR-ARA",
    "bourgogne-franche-comté": "FR-BFC",
    "bretagne": "FR-BRE",
    "centre-val de loire": "FR-CVL",
    "grand est": "FR-GES",
    "hauts-de-france": "FR-HDF",
    "haut-de-france": "FR-HDF",
    "île-de-france": "FR-IDF",
    "normandie": "FR-NOR",
    "nouvelle-aquitaine": "FR-NAQ",
    "occitanie": "FR-OCC",
    "pays de la loire": "FR-PDL",
    "provence-alpes-côte d'azur": "FR-PAC",
}
TECHNOLOGIES = {"eolien onshore": "wind", "solaire": "solar", "hydraulique": "hydro", "thermique": "thermal"}

# The order EEX lists the segments in, region by region, which every file
# keeps but seven from 2019, and the 48 segments a full auction has.
REGION_ORDER = (
    "FR-ARA",
    "FR-BFC",
    "FR-BRE",
    "FR-CVL",
    "FR-GES",
    "FR-HDF",
    "FR-IDF",
    "FR-NOR",
    "FR-NAQ",
    "FR-OCC",
    "FR-PDL",
    "FR-PAC",
)
TECHNOLOGY_ORDER = ("eolien onshore", "hydraulique", "solaire", "thermique")
SEGMENTS = tuple((r, t) for r in REGION_ORDER for t in TECHNOLOGY_ORDER)
REGION_NAMES = {
    "FR-ARA": "Auvergne-Rhône-Alpes",
    "FR-BFC": "Bourgogne-Franche-Comté",
    "FR-BRE": "Bretagne",
    "FR-CVL": "Centre-Val de Loire",
    "FR-GES": "Grand Est",
    "FR-HDF": "Haut-de-France",
    "FR-IDF": "Île-de-France",
    "FR-NOR": "Normandie",
    "FR-NAQ": "Nouvelle-Aquitaine",
    "FR-OCC": "Occitanie",
    "FR-PDL": "Pays de la Loire",
    "FR-PAC": "Provence-Alpes-Côte d'Azur",
}
TECHNOLOGY_NAMES = {
    "eolien onshore": "Eolien onshore",
    "hydraulique": "Hydraulique",
    "solaire": "Solaire",
    "thermique": "Thermique",
}

# Each column the parser reads, by how its header starts once repaired and lower-cased.
COLUMNS = {
    "région / region": "region",
    "technologie / technology": "technology",
    "total volume auctionned": "offered",
    "total volume auctioned": "offered",
    "total volume sold": "sold",
    "weighted average price": "price",
    "number of winners": "winners",
}
IGNORED = ("my total volume", "my weighted average price")
NOTHING = ("-", "", None)


class Unexpected(ValueError):
    """The file does not hold what an EEX results file holds."""


def repair(text: str) -> str:
    """Undo UTF-8 read as Windows-1252, which EEX's files often carry."""
    if not any(mark in text for mark in ("Ã", "â€", "â‚")):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def clean(value: Any) -> Any:
    return " ".join(repair(value).split()) if isinstance(value, str) else value


def number(value: Any, what: str, where: str) -> float | None:
    if value in NOTHING or (isinstance(value, str) and value.strip() in NOTHING):
        return None
    if isinstance(value, bool):
        raise Unexpected(f"{where}: {what} is {value!r}, not a number")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip().replace(" ", "").replace(" ", "")
        text = text.replace(",", ".") if text.count(",") == 1 and "." not in text else text.replace(",", "")
        try:
            result = float(text)
        except ValueError:
            raise Unexpected(f"{where}: {what} is {value!r}, not a number") from None
    if result < 0:
        raise Unexpected(f"{where}: {what} is negative ({result})")
    return result


def from_name(name: str) -> dict[str, Any]:
    match = NAME.match(posixpath.basename(name))
    if not match or match.group("month").lower() not in MONTHS:
        raise Unexpected(f"{name} is not named like an EEX results file")
    year, month = int(match.group("year")), MONTHS[match.group("month").lower()]
    held = match.group("date")
    number_, round_ = match.group("number"), match.group("round")
    label = f"{number_}-{round_}" if number_ and round_ else number_
    return {
        "auction_date": date(int(held[:4]), int(held[4:6]), int(held[6:])),
        "production_period_start": date(year, month, 1),
        "production_period_end": date(year, month, calendar.monthrange(year, month)[1]),
        "auction_number": label,
        "auction_id": f"eex-fr-go-{year:04d}-{month:02d}" + (f"-{label}" if label else ""),
    }


def rows_of(name: str, data: bytes) -> tuple[str | None, list[tuple[int, list[Any]]]]:
    """The sheet's name and its rows (numbered from 1), as cells."""
    if name.lower().endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
        return None, list(enumerate(csv.reader(io.StringIO(text), delimiter=";"), start=1))
    import openpyxl  # noqa: PLC0415 - only xlsx files need it

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - openpyxl raises many kinds for a file it cannot read
        raise Unexpected(f"{name} is not a readable xlsx workbook: {type(error).__name__}: {error}") from error
    try:
        sheet = workbook.worksheets[0]
        return sheet.title, [(i, list(r)) for i, r in enumerate(sheet.iter_rows(values_only=True), start=1)]
    finally:
        workbook.close()


def parse(
    name: str, sha256: str, data: bytes, parser: str, version: str, rules: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], list[Note]]:
    auction = from_name(name)
    sheet, rows = rows_of(name, data)
    rows = [(i, [clean(c) for c in cells]) for i, cells in rows]
    participants, header_at, columns = None, None, {}
    for index, cells in rows:
        first = cells[0] if cells else None
        if isinstance(first, str) and first.lower().startswith("number of participants"):
            values = [c for c in cells[1:] if c not in NOTHING]
            participants = number(values[0] if values else None, "the number of participants", f"{name} row {index}")
        if isinstance(first, str) and first.lower().startswith("région / region"):
            header_at = index
            for position, cell in enumerate(cells):
                if cell in NOTHING:
                    continue
                label = str(cell).lower()
                key = next((v for k, v in COLUMNS.items() if label.startswith(k)), None)
                if key is None and not label.startswith(IGNORED):
                    raise Unexpected(f"{name} row {index}: unknown column {cell!r}")
                if key:
                    columns[key] = position
            break
    if header_at is None:
        raise Unexpected(f"{name} has no header row starting 'Région / Region'")
    missing = sorted(set(COLUMNS.values()) - set(columns))
    if missing:
        raise Unexpected(f"{name}: the header lacks {', '.join(missing)}")
    if participants is None:
        raise Unexpected(f"{name} gives no number of participants")

    # The rows as published, with their numbers read, for the corrections to match.
    published = []
    for index, cells in rows:
        if index <= header_at or all(c in NOTHING for c in cells):
            continue
        where = f"{name} row {index}"
        value = {key: cells[at] if at < len(cells) else None for key, at in columns.items()}
        published.append(
            {
                "row": index,
                "region": value["region"],
                "technology": value["technology"],
                "volume_offered": number(value["offered"], "the volume offered", where),
                "volume_sold": number(value["sold"], "the volume sold", where),
                "price": number(value["price"], "the price", where),
                "winners": number(value["winners"], "the number of winners", where),
            }
        )
    try:
        corrected, notes = corrections.apply(name, published, rules or [])
    except corrections.CorrectionError as error:
        raise Unexpected(str(error)) from error

    out, seen = [], set()
    for record in corrected:
        where = f"{name} row {record['row']}"
        region_label, technology_label = record["region"], record["technology"]
        region = REGIONS.get(str(region_label).lower())
        technology = TECHNOLOGIES.get(str(technology_label).lower())
        if region is None:
            raise Unexpected(f"{where}: unknown region {region_label!r}")
        if technology is None:
            raise Unexpected(f"{where}: unknown technology {technology_label!r}")
        if (region, str(technology_label).lower()) in seen:
            raise Unexpected(f"{where}: {region_label} {technology_label} appears twice")
        seen.add((region, str(technology_label).lower()))
        offered, price, winners = record["volume_offered"], record["price"], record["winners"]
        sold = record["volume_sold"] or 0.0
        if offered is not None and sold > offered:
            raise Unexpected(f"{where}: {sold:g} MWh sold is more than the {offered:g} MWh offered")
        if price is not None and not sold:
            raise Unexpected(f"{where}: a price of {price:g} with nothing sold")
        out.append(
            {
                "provider": "eex",
                "market": "FR",
                "certificate_type": "GO",
                "energy_carrier": "electricity",
                **auction,
                "segment_level": "region_x_technology",
                "region": region,
                "technology": technology,
                "volume_offered_mwh": offered,
                "volume_allocated_mwh": sold,
                "price_weighted_avg_eur_mwh": price,
                "price_min_eur_mwh": None,
                "price_max_eur_mwh": None,
                "reserve_price_eur_mwh": None,
                "bidders_count": int(participants),
                "winners_count": int(winners) if winners is not None else None,
                "extras": json.dumps(
                    {"region_label": region_label, "technology_label": technology_label},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "source_name": name,
                "source_sha256": sha256,
                "source_sheet": sheet,
                "source_row": record["row"],
                "parser_name": parser,
                "parser_version": version,
            }
        )
    if not out:
        raise Unexpected(f"{name} has no result rows")
    notes += check_segments(name, corrected, rules or [])
    return out, notes


def check_segments(name: str, rows: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[Note]:
    """That the file lists every segment, in EEX's usual order, unless a
    rule says otherwise; a rule the file no longer needs fails it."""
    by_kind = {kind: [r for r in rules if r["kind"] == kind] for kind in corrections.KINDS}
    present = [(REGIONS[str(r["region"]).lower()], str(r["technology"]).lower()) for r in rows]
    notes: list[Note] = []

    expected = [s for s in SEGMENTS if s in set(present)]
    in_order = present == expected
    if by_kind["row_order"]:
        if in_order:
            raise Unexpected(
                f"correction {by_kind['row_order'][0]['id']} is no longer needed: "
                f"{name} lists its rows in the usual order"
            )
        notes += [
            Note("data_correction", f"{r['problem']} ({r['id']})", subject=name, severity="info")
            for r in by_kind["row_order"]
        ]
    elif not in_order:
        at = next(i for i, (a, b) in enumerate(zip(present, expected, strict=True)) if a != b)
        wanted = expected[at]
        raise Unexpected(
            f"{name} row {rows[at]['row']}: {rows[at]['region']} {rows[at]['technology']} is out of "
            f"EEX's usual order, where {REGION_NAMES[wanted[0]]} {TECHNOLOGY_NAMES[wanted[1]]} belongs"
        )

    noted = {
        (REGIONS.get(str(r["row"].get("region", "")).lower()), str(r["row"].get("technology", "")).lower())
        for r in by_kind["missing_row"]
    }
    missing = [s for s in SEGMENTS if s not in set(present) and s not in noted]
    if by_kind["partial_auction"]:
        if not missing:
            raise Unexpected(
                f"correction {by_kind['partial_auction'][0]['id']} is no longer needed: {name} lists every segment"
            )
        notes += [
            Note("data_correction", f"{r['problem']} ({r['id']})", subject=name, severity="info")
            for r in by_kind["partial_auction"]
        ]
    elif missing:
        shown = ", ".join(f"{REGION_NAMES[r]} {TECHNOLOGY_NAMES[t]}" for r, t in missing[:5])
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        raise Unexpected(
            f"{name} lacks {len(missing)} of the {len(SEGMENTS)} region and technology segments: {shown}{more}"
        )
    return notes


def check_rules(rules: list[dict[str, Any]]) -> None:
    """That each correction names a results file and a region and technology
    this parser knows, so a typo fails before any file is read."""
    for rule in rules:
        if not NAME.match(posixpath.basename(rule["file"])):
            raise corrections.CorrectionError(
                f"correction {rule['id']}: {rule['file']} is not named like an EEX results file"
            )
        fields = {**(rule.get("row") or {}), **(rule.get("set") or {})}
        unknown = sorted(set(fields) - {"region", "technology", "volume_offered", "volume_sold", "price", "winners"})
        if unknown:
            raise corrections.CorrectionError(f"correction {rule['id']}: unknown fields {', '.join(unknown)}")
        if "region" in fields and str(fields["region"]).lower() not in REGIONS:
            raise corrections.CorrectionError(f"correction {rule['id']}: unknown region {fields['region']!r}")
        if "technology" in fields and str(fields["technology"]).lower() not in TECHNOLOGIES:
            raise corrections.CorrectionError(f"correction {rule['id']}: unknown technology {fields['technology']!r}")


@register
class Results(Parser):
    name = "eex-french-auction"
    version = "1.0.0"

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        path = ctx.options.get("corrections")
        rules = corrections.load(path) if path else []
        check_rules(rules)
        # A file's corrections are parameters of its item, so changing them parses it again.
        return [
            WorkItem(
                key=a.name,
                inputs=(a,),
                params=(
                    (
                        "corrections",
                        json.dumps(corrections.for_file(rules, a.name), sort_keys=True, ensure_ascii=False),
                    ),
                ),
            )
            for a in upstream
        ]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        artifact = item.inputs[0]
        rules = json.loads(dict(item.params)["corrections"])
        rows, notes = parse(artifact.name, artifact.sha256, ctx.read(artifact), self.name, self.version, rules)
        return ItemResult(
            [Output("results.parquet", auction_results.write(rows), "application/vnd.apache.parquet", len(rows))], notes
        )

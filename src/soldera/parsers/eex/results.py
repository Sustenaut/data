"""Stage 4, parse: one EEX results file into canonical auction_results rows.

eex-french-auction@1.0.0 reads one file the select stage kept, xlsx or csv,
and writes `results.parquet` in soldera.canonical.auction_results. Every era
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

A mistake in EEX's own file that has been looked at can be accepted in the
stage's options, so it does not block every run until EEX corrects it:

    accepted_issues:
      - file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.xlsx
        sha256: 599531eb...      # the file as it was looked at
        row: 53
        issue: duplicate_segment
        note: EEX lists Provence-Alpes-Côte d'Azur Thermique twice ...

An accepted duplicate_segment row is kept with its region unknown, so totals
stay right, and gets a warning note with the entry's text, for the app to
show. An entry applies only to the file with that hash: a corrected file is
parsed as it is. An entry whose issue is no longer in its file fails the
file, so the list cannot go stale."""

from __future__ import annotations

import calendar
import csv
import io
import json
import posixpath
import re
from datetime import date
from typing import Any

from soldera.canonical import auction_results
from soldera.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from soldera.core.registry import register

NAME = re.compile(
    r"^(?P<date>\d{8})_(?P<month>[a-z]+)_(?P<year>\d{4})"
    r"(?:_(?P<number>\d+)(?:_(?P<round>\d+))?)?_global_?results", re.IGNORECASE)
MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}

REGIONS = {
    "auvergne-rhône-alpes": "FR-ARA", "bourgogne-franche-comté": "FR-BFC", "bretagne": "FR-BRE",
    "centre-val de loire": "FR-CVL", "corse": "FR-20R", "grand est": "FR-GES",
    "hauts-de-france": "FR-HDF", "haut-de-france": "FR-HDF", "île-de-france": "FR-IDF",
    "normandie": "FR-NOR", "nouvelle-aquitaine": "FR-NAQ", "occitanie": "FR-OCC",
    "pays de la loire": "FR-PDL", "provence-alpes-côte d'azur": "FR-PAC",
}
TECHNOLOGIES = {"eolien onshore": "wind", "eolien offshore": "wind", "solaire": "solar",
                "hydraulique": "hydro", "thermique": "thermal"}

# Each column the parser reads, by how its header starts once repaired and lower-cased.
COLUMNS = {
    "région / region": "region", "technologie / technology": "technology",
    "total volume auctionned": "offered", "total volume auctioned": "offered",
    "total volume sold": "sold", "weighted average price": "price",
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


ISSUES = ("duplicate_segment",)


def parse(name: str, sha256: str, data: bytes, parser: str, version: str,
          accepted: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[Note]]:
    accepted_at = {int(a["row"]): a for a in accepted or []}
    used: set[int] = set()
    notes: list[Note] = []
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
    out, seen = [], set()
    for index, cells in rows:
        if index <= header_at or all(c in NOTHING for c in cells):
            continue
        where = f"{name} row {index}"
        cell = lambda key: cells[columns[key]] if columns[key] < len(cells) else None  # noqa: E731
        region_label, technology_label = cell("region"), cell("technology")
        region = REGIONS.get(str(region_label).lower())
        technology = TECHNOLOGIES.get(str(technology_label).lower())
        if region is None:
            raise Unexpected(f"{where}: unknown region {region_label!r}")
        if technology is None:
            raise Unexpected(f"{where}: unknown technology {technology_label!r}")
        region_unknown = False
        if (region, str(technology_label).lower()) in seen:
            issue = accepted_at.get(index)
            if not issue or issue["issue"] != "duplicate_segment":
                raise Unexpected(f"{where}: {region_label} {technology_label} appears twice")
            used.add(index)
            region, region_unknown = None, True
            notes.append(Note("accepted_issue", str(issue["note"]), subject=f"{name} row {index}"))
        else:
            seen.add((region, str(technology_label).lower()))
        offered = number(cell("offered"), "the volume offered", where)
        sold = number(cell("sold"), "the volume sold", where) or 0.0
        price = number(cell("price"), "the price", where)
        winners = number(cell("winners"), "the number of winners", where)
        if offered is not None and sold > offered:
            raise Unexpected(f"{where}: {sold:g} MWh sold is more than the {offered:g} MWh offered")
        if price is not None and not sold:
            raise Unexpected(f"{where}: a price of {price:g} with nothing sold")
        out.append({
            "provider": "eex", "market": "FR", "certificate_type": "GO", "energy_carrier": "electricity",
            **auction, "segment_level": "region_x_technology", "region": region, "technology": technology,
            "volume_offered_mwh": offered, "volume_allocated_mwh": sold, "price_weighted_avg_eur_mwh": price,
            "price_min_eur_mwh": None, "price_max_eur_mwh": None, "reserve_price_eur_mwh": None,
            "bidders_count": int(participants), "winners_count": int(winners) if winners is not None else None,
            "extras": json.dumps({"region_label": region_label, "technology_label": technology_label,
                                  **({"region_unknown": True} if region_unknown else {})},
                                 ensure_ascii=False, sort_keys=True),
            "source_name": name, "source_sha256": sha256, "source_sheet": sheet, "source_row": index,
            "parser_name": parser, "parser_version": version,
        })
    if not out:
        raise Unexpected(f"{name} has no result rows")
    stale = sorted(set(accepted_at) - used)
    if stale:
        raise Unexpected(f"{name}: the accepted issue at row {', '.join(map(str, stale))} is no longer in the file")
    return out, notes


def accepted_for(artifact: Artifact, options: dict[str, Any]) -> list[dict[str, Any]]:
    """The accepted issues of this file as it is, checked for shape."""
    entries = options.get("accepted_issues") or []
    if not isinstance(entries, list):
        raise ValueError("options.accepted_issues must be a list")
    found = []
    for entry in entries:
        if not isinstance(entry, dict) or not {"file", "sha256", "row", "issue", "note"} <= set(entry):
            raise ValueError(f"an accepted issue needs file, sha256, row, issue and note: {entry!r}")
        if entry["issue"] not in ISSUES:
            raise ValueError(f"accepted issue {entry['issue']!r} is not one of {', '.join(ISSUES)}")
        if entry["file"] == artifact.name and entry["sha256"] == artifact.sha256:
            found.append({k: entry[k] for k in ("row", "issue", "note")})
    return found


@register
class Results(Parser):
    name = "eex-french-auction"
    version = "1.0.0"

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        # The accepted issues are parameters, so changing them parses the file again.
        return [WorkItem(key=a.name, inputs=(a,),
                         params=(("accepted", json.dumps(accepted_for(a, ctx.options), sort_keys=True)),))
                for a in upstream]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        artifact = item.inputs[0]
        accepted = json.loads(dict(item.params)["accepted"])
        rows, notes = parse(artifact.name, artifact.sha256, ctx.read(artifact), self.name, self.version, accepted)
        return ItemResult([Output("results.parquet", auction_results.write(rows), "application/vnd.apache.parquet",
                                  len(rows))], notes)

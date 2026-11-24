"""Stage 3, select: keep the monthly GO Global Results files, once each.

eex-go-global-results-select@1.0.0 reads every file stage 2 stored, loose
or from an archive, and keeps the files of one auction's results each, named
like EEX names them:

    20261118_July_2026_21_GLOBAL_Results_detailedresults.xlsx
    20190918_April_2019_global_results.xlsx
    20210120_October_2020_Global_Results.csv

that is: the publishing date, the production month and year, optionally the
auction number (and a round, for a second auction in a month), then "global
results", in xlsx or csv. Archives and PDFs are not data and are passed over
without a note.

Each spreadsheet or csv the stage sees becomes one item:

- a results file is kept, stored under its own name without the archive's
  folders, so stage 4 parses it;
- a file stored twice with the same content (the latest monthly file is also
  in the yearly archive) is kept once, from the archive, and the other copy
  gets an info note;
- any other spreadsheet or csv (such as the yearly summary
  Resultats_encheres_20.xlsx) is left out with an info note, so a new kind of
  file EEX starts publishing is seen rather than dropped quietly.

Two different files that would be kept under the same name fail the stage."""

from __future__ import annotations

import posixpath
import re

from ingest.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register

DATA = (".xlsx", ".xls", ".csv")
RESULTS = re.compile(
    r"^(?P<published>\d{8})_(?P<month>[a-z]+)_(?P<year>\d{4})"
    r"(?:_(?P<number>\d+)(?:_(?P<round>\d+))?)?_global_?results.*\.(?:xlsx|csv)$",
    re.IGNORECASE,
)
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def is_results(name: str) -> bool:
    match = RESULTS.match(posixpath.basename(name))
    return bool(match) and match.group("month").lower() in MONTHS


def origin(artifact: Artifact) -> str:
    """Where a file came from, as people would say it."""
    if artifact.item_key and artifact.item_key != artifact.name:
        return f"{artifact.item_key}/{artifact.name}"
    return artifact.name


@register
class SelectGlobalResults(Parser):
    name = "eex-go-global-results-select"
    version = "1.0.0"

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        data = [a for a in upstream if a.name.lower().endswith(DATA)]
        # The copy kept of a file stored twice is the one from an archive, then
        # the first by where it came from, so the choice does not change between runs.
        data.sort(key=lambda a: (a.item_key == a.name, origin(a)))
        kept: dict[str, Artifact] = {}
        names: dict[str, Artifact] = {}
        items = []
        for artifact in data:
            if not is_results(artifact.name):
                decision = "other"
            elif artifact.sha256 in kept:
                decision = "duplicate:" + origin(kept[artifact.sha256])
            else:
                decision = "keep"
                name = posixpath.basename(artifact.name)
                if name in names:
                    raise ValueError(f"{origin(artifact)} and {origin(names[name])} would both be kept as {name}")
                kept[artifact.sha256], names[name] = artifact, artifact
            items.append(WorkItem(key=origin(artifact), inputs=(artifact,), params=(("decision", decision),)))
        return sorted(items, key=lambda i: i.key)

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        artifact = item.inputs[0]
        decision = dict(item.params)["decision"]
        if decision == "keep":
            name = posixpath.basename(artifact.name)
            return ItemResult([Output(name, ctx.read(artifact), artifact.media_type)])
        if decision.startswith("duplicate:"):
            kept = decision.partition(":")[2]
            return ItemResult(
                notes=[
                    Note(
                        "file_duplicate",
                        f"{item.key} is the same file as {kept}; it is used once",
                        subject=item.key,
                        severity="info",
                    )
                ]
            )
        return ItemResult(
            notes=[
                Note(
                    "file_not_results",
                    f"{item.key} is not a monthly GO Global Results file; it is left out",
                    subject=item.key,
                    severity="info",
                )
            ]
        )

"""Data corrections: mistakes found in a provider's published files, and what
to do about each, kept as data so the list can be reviewed, and sent to the
provider for them to fix at the source.

A corrections file is YAML:

    corrections:
      - id: eex-2025-10-paca-thermique-repeated
        file: 20260121_October_2025_7_GLOBAL_Results_detailedresults.xlsx
        kind: wrong_row            # a row that should not be as it is
        row:                       # the row exactly as the provider published it
          region: Provence-Alpes-Côte d'Azur
          technology: Thermique
          volume_offered: 2959
        action: drop               # drop it, or `set` fields (with `set: {...}`)
        problem: Provence-Alpes-Côte d'Azur Thermique is listed twice.
        evidence: The second row's figures are September 2025's for that segment.
        reported_to_provider: "no"

      - id: ...
        kind: missing_row          # a row the provider left out; noted, not invented
        row: {region: Île-de-France, technology: Hydraulique}

      - id: ...
        kind: row_order            # the file's rows are not in the usual order
      - id: ...
        kind: partial_auction      # the auction offered only some segments

A parser hands `apply` the rows it read from one file; `apply` handles the
row rules, and the parser the rules about a whole file (row_order,
partial_auction), which it must also find still needed. Each rule must still
be needed: a wrong_row rule must match exactly one row, and a missing_row
rule must match none. A rule that no longer matches fails the file, so a new
version of the file in which the provider fixed the mistake is noticed, and
the rule removed. Every rule applied leaves a note for the reader of the
data: a warning for a corrected row, an info note for a missing one.

A row rule also keeps the evidence: `source_sha256`, the hash of the file as
it was found, and `excerpt`, the rows around the mistake as published (each
with its `row` number). `check` tries every rule on its excerpt, so a rule
that would not match is caught in CI, even after the provider has corrected
or removed the file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from soldera.core.parser import Note

ROW_KINDS = ("wrong_row", "missing_row")
# Rules about a whole file, which the parser that checks the file applies.
FILE_KINDS = ("row_order", "partial_auction")
KINDS = ROW_KINDS + FILE_KINDS
ACTIONS = ("drop", "set")
REQUIRED = ("id", "file", "kind", "problem", "evidence", "reported_to_provider")


class CorrectionError(ValueError):
    pass


def load(path: str | Path) -> list[dict[str, Any]]:
    """The rules of a corrections file, checked for shape."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise CorrectionError(f"cannot read the corrections file {path}: {error}") from error
    rules = data.get("corrections") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise CorrectionError(f"{path} must hold a list under `corrections`")
    seen: set[str] = set()
    for rule in rules:
        where = f"{path}: correction {rule.get('id', '?') if isinstance(rule, dict) else rule!r}"
        if not isinstance(rule, dict):
            raise CorrectionError(f"{where} must be a mapping")
        missing = [k for k in REQUIRED if k not in rule]
        if missing:
            raise CorrectionError(f"{where} lacks {', '.join(missing)}")
        if rule["id"] in seen:
            raise CorrectionError(f"{where} appears twice")
        seen.add(rule["id"])
        if rule["kind"] not in KINDS:
            raise CorrectionError(f"{where}: kind must be one of {', '.join(KINDS)}")
        if rule["kind"] in ROW_KINDS and (not isinstance(rule.get("row"), dict) or not rule["row"]):
            raise CorrectionError(f"{where}: row must give the fields of the row as published")
        if rule["kind"] == "wrong_row":
            if rule.get("action") not in ACTIONS:
                raise CorrectionError(f"{where}: action must be one of {', '.join(ACTIONS)}")
            if rule["action"] == "set" and not isinstance(rule.get("set"), dict):
                raise CorrectionError(f"{where}: action set needs `set`, the fields to change")
        if rule["kind"] in ROW_KINDS:
            excerpt = rule.get("excerpt")
            if not rule.get("source_sha256") or not isinstance(excerpt, list) or not excerpt:
                raise CorrectionError(f"{where} needs source_sha256 and an excerpt of the rows as published")
            if not all(isinstance(r, dict) and isinstance(r.get("row"), int) for r in excerpt):
                raise CorrectionError(f"{where}: each excerpt row needs its row number, `row`")
    return rules


def for_file(rules: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [r for r in rules if r["file"] == name]


def same(actual: Any, wanted: Any) -> bool:
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and float(actual) == float(wanted)
    return actual == wanted


def describe(rule: dict[str, Any]) -> str:
    if rule["kind"] == "missing_row":
        return "nothing was added"
    if rule["action"] == "drop":
        return "the row was left out"
    return "set " + ", ".join(f"{k} to {v}" for k, v in rule["set"].items())


def apply(name: str, rows: list[dict[str, Any]], rules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[Note]]:
    """The rows with the file's corrections applied, and a note for each.
    Each row is a mapping with "row" (its number in the file) and its fields."""
    rows = [dict(r) for r in rows]
    notes: list[Note] = []
    for rule in rules:
        if rule["kind"] not in ROW_KINDS:
            continue
        matches = [r for r in rows if all(same(r.get(k), v) for k, v in rule["row"].items())]
        if rule["kind"] == "missing_row":
            if matches:
                raise CorrectionError(f"correction {rule['id']} is no longer needed: {name} now has the row "
                                      f"(row {matches[0]['row']})")
            notes.append(Note("data_correction", f"{rule['problem']} ({rule['id']})", subject=name, severity="info"))
            continue
        if len(matches) != 1:
            found = "no row" if not matches else f"{len(matches)} rows"
            raise CorrectionError(f"correction {rule['id']} is no longer needed as written: {found} of {name} "
                                  f"match {rule['row']}")
        target = matches[0]
        if rule["action"] == "drop":
            rows.remove(target)
        else:
            target.update(rule["set"])
        notes.append(Note("data_correction", f"{rule['problem']} Corrected: {describe(rule)}. ({rule['id']})",
                          subject=f"{name} row {target['row']}"))
    return rows, notes


def check(rules: list[dict[str, Any]]) -> list[str]:
    """Each row rule tried on its own excerpt: what would not apply, if anything."""
    problems = []
    for rule in rules:
        if rule["kind"] not in ROW_KINDS:
            continue
        try:
            apply(rule["file"], rule["excerpt"], [rule])
        except CorrectionError as error:
            problems.append(f"{rule['id']}: on its excerpt, {error}")
    return problems

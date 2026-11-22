"""soldera's own steps, beside pubtest's: what the store, the run log and the
notes hold after `soldera run`. Every path is in the scenario's scratch
directory, where `soldera run` keeps its store (store/) and run log
(runs.jsonl) by default."""

from __future__ import annotations

import io
import json
import zipfile
import re
import shlex
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pubtest.core import dig, same
from pubtest.plugin import run_program
from pytest_bdd import given, parsers, scenarios, then

scenarios("runner.feature", "run_log.feature", "discover.feature", "download.feature", "select.feature", "parse.feature")

REPOSITORY = Path(__file__).resolve().parents[2]


def scratch(ctx) -> Path:
    assert ctx.directory is not None, "these steps need a scratch directory"
    return ctx.directory


def stage_dir(ctx, stage: str) -> Path:
    found = sorted((scratch(ctx) / "store").glob(f"[0-9][0-9]-{stage}"))
    assert found, f"the store has no stage {stage}"
    return found[0]


def rows(ctx) -> list[dict]:
    path = scratch(ctx) / "runs.jsonl"
    assert path.exists(), "nothing wrote the run log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def final_row(ctx, stage: str, run_id: str) -> dict:
    found = [r for r in rows(ctx) if r["run_id"] == run_id and r["stage_name"] == stage and r["status"] != "running"]
    assert found, f"the run log has no final row for {stage} in run {run_id}"
    return found[-1]


def stage_notes(ctx, stage: str, run_id: str) -> list[dict]:
    paths = list(stage_dir(ctx, stage).glob(f"*/runs/{run_id}/notes.parquet"))
    assert len(paths) == 1, f"expected one notes.parquet for {stage} in run {run_id}, found {len(paths)}"
    return pq.read_table(paths[0]).to_pylist()


@given(parsers.parse('I ran "{command}"'))
def ran(ctx, command):
    argv = shlex.split(command)
    argv[0] = getattr(ctx, "programs", {}).get(argv[0], argv[0])
    done = run_program(argv, None, scratch(ctx), {}, 120)
    if done.code != 0:
        pytest.fail(f"{command} failed: exit {done.code}\n{done.stdout}\n{done.stderr}")


@given(parsers.parse('the file "{path}" now pins "{pin}"'))
def now_pins(ctx, path, pin):
    file = scratch(ctx) / path
    name = pin.partition("@")[0]
    text, count = re.subn(rf"{re.escape(name)}@[0-9A-Za-z.\-]+", pin, file.read_text(encoding="utf-8"))
    assert count == 1, f"{path} pins {name} {count} times"
    file.write_text(text, encoding="utf-8")


def published(ctx, stage: str, name: str) -> bytes:
    """An output of the stage's published run, by its name."""
    latest = list(stage_dir(ctx, stage).glob("*/latest.json"))
    assert len(latest) == 1, f"{stage} has {len(latest)} published parser versions"
    store = scratch(ctx) / "store"
    manifest = json.loads((store / json.loads(latest[0].read_text())["manifest"]).read_text())
    found = [o for item in manifest["items"] if item["status"] != "failed" for o in item["outputs"] if o["name"] == name]
    assert len(found) == 1, f"{stage} published {len(found)} outputs named {name}"
    return (store / found[0]["key"]).read_bytes()


def listed(ctx, stage: str, name: str) -> dict[str, dict]:
    return {entry["name"]: entry for entry in json.loads(published(ctx, stage, name))}


@given(parsers.parse('the repository\'s pipeline "{name}"'))
def repository_pipeline(ctx, name):
    source = REPOSITORY / "pipelines" / f"{name}.yaml"
    (scratch(ctx) / "pipeline.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(REPOSITORY / "corrections", scratch(ctx) / "corrections")


class Raw(str):
    """A fake service's answer body that is bytes, not text: pubtest's fake
    encodes the body it is given, and this one encodes to itself."""

    def __new__(cls, data: bytes):
        made = super().__new__(cls, "")
        made.data = data
        return made

    def encode(self, *args, **kwargs) -> bytes:  # noqa: ARG002 - the bytes are already made
        return self.data


@given(parsers.parse('the "{name}" service answers "{request}" with a zip holding:'))
def answers_with_zip(pubtest_ctx, monkeypatch, name, request, datatable):
    from pubtest.steps.fakes import fake  # noqa: PLC0415

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in datatable[1:]:
            archive.writestr(path.strip(), content.strip())
    fake(pubtest_ctx, monkeypatch, name).answer(request, 200, Raw(buffer.getvalue()))


@given(parsers.parse('the "{name}" service answers "{request}" with a zip whose "{path}" is corrupt'))
def answers_with_corrupt_zip(pubtest_ctx, monkeypatch, name, request, path):
    from pubtest.steps.fakes import fake  # noqa: PLC0415

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("fine.csv", "fine")
        archive.writestr(path, "the original content")
    data = buffer.getvalue().replace(b"the original content", b"the altered! content")
    fake(pubtest_ctx, monkeypatch, name).answer(request, 200, Raw(data))


def cell(text: str):
    """A workbook cell from a table: a number when it reads as one."""
    text = text.strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


@given(parsers.parse('the "{name}" service answers "{request}" with a workbook:'))
def answers_with_workbook(pubtest_ctx, monkeypatch, name, request, datatable):
    import openpyxl  # noqa: PLC0415
    from pubtest.steps.fakes import fake  # noqa: PLC0415

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "results"
    for line in datatable:
        sheet.append([cell(c) for c in line])
    buffer = io.BytesIO()
    workbook.save(buffer)
    fake(pubtest_ctx, monkeypatch, name).answer(request, 200, Raw(buffer.getvalue()))


REGION_LABELS = ("Auvergne-Rhône-Alpes", "Bourgogne-Franche-Comté", "Bretagne", "Centre-Val de Loire", "Grand Est",
                 "Haut-de-France", "Île-de-France", "Normandie", "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire",
                 "Provence-Alpes-Côte d'Azur")
TECHNOLOGY_LABELS = ("Eolien onshore", "Hydraulique", "Solaire", "Thermique")


def full_rows(datatable) -> list[list[str]]:
    """EEX's 48 rows, in its usual order, each 100 MWh offered and sold at
    0.5 by 1 winner, changed as the table says. A row for a region and
    technology replaces that one, and "absent" as the volume offered leaves
    it out. A row with an `after` ("Region / Technology") is an extra row,
    put after the one named, whatever its own labels."""
    header, *body = datatable
    changes = [dict(zip(header, (c.strip() for c in line), strict=True)) for line in body]
    fields = ("region", "technology", "offered", "sold", "price", "winners")
    rows = []
    for region in REGION_LABELS:
        for technology in TECHNOLOGY_LABELS:
            row = [region, technology, "100", "100", "0.5", "1"]
            for change in changes:
                if not change.get("after") and (change["region"], change["technology"]) == (region, technology):
                    row = [change[f] for f in fields]
            if row[2] != "absent":
                rows.append(row)
            rows += [[change[f] for f in fields] for change in changes
                     if change.get("after") == f"{region} / {technology}"]
    return rows


@given(parsers.parse('the "{name}" service answers "{request}" with a full results csv for {participants:d} participants, where:'))
def answers_with_full_csv(pubtest_ctx, monkeypatch, name, request, participants, datatable):
    from pubtest.steps.fakes import fake  # noqa: PLC0415

    lines = ["Aggregated Auction Results;;;;;", f"Number of Participants to the Auction;{participants};;;;",
             "Région / Region;Technologie / Technology;Total Volume Auctionned;Total Volume Sold;"
             "Weighted Average Price (€ / MWh);Number of winners per couple region/technology"]
    lines += [";".join(c.replace(".", ",") for c in row) for row in full_rows(datatable)]
    fake(pubtest_ctx, monkeypatch, name).answer(request, 200, "\n".join(lines) + "\n")


@given(parsers.parse('the "{name}" service answers "{request}" with a full results workbook for {participants:d} participants, garbled like EEX\'s, where:'))
def answers_with_full_workbook(pubtest_ctx, monkeypatch, name, request, participants, datatable):
    import openpyxl  # noqa: PLC0415
    from pubtest.steps.fakes import fake  # noqa: PLC0415

    def garble(text: str) -> str:
        return text.encode("utf-8").decode("cp1252", "replace")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Aggregated Auction Results"])
    sheet.append(["Number of Participants to the Auction", participants])
    sheet.append([garble(h) for h in ("Région / Region", "Technologie / Technology", "Total Volume Auctionned",
                                      "Total Volume Sold", "Weighted Average Price (€ / MWh)", "My Total Volume",
                                      "My Weighted Average Price (€ / MWh)",
                                      "Number of winners per couple region/technology")])
    for region, technology, offered, sold, price, winners in full_rows(datatable):
        sheet.append([garble(region), technology, cell(offered), cell(sold), cell(price), "-", "-", cell(winners)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    fake(pubtest_ctx, monkeypatch, name).answer(request, 200, Raw(buffer.getvalue()))


@then(parsers.parse('the parse stage wrote {count:d} rows'))
def parsed_count(ctx, count):
    store = scratch(ctx) / "store"
    total = sum(pq.read_table(store / o["key"]).num_rows
                for item in latest_manifest(ctx, "parse")["items"] for o in item["outputs"])
    assert total == count, f"the parse stage wrote {total} rows"


@then(parsers.parse('the parsed rows of "{stage}" include, in order:'))
def parsed_rows_include(ctx, stage, datatable):
    store = scratch(ctx) / "store"
    header, *body = datatable
    actual = [{k: "" if row[k] is None else str(row[k]) for k in header}
              for item in latest_manifest(ctx, stage)["items"] for output in item["outputs"]
              for row in pq.read_table(store / output["key"]).to_pylist()]
    wanted = [{k: v.strip() for k, v in zip(header, line, strict=True)} for line in body]
    found = [r for r in actual if r in wanted]
    assert found == wanted, f"of the rows wanted, these were found: {found}"


@given("the corrections file holds:")
def corrections_file(ctx, docstring):
    path = scratch(ctx) / "corrections" / "eex-french-power-auctions.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(docstring + "\n", encoding="utf-8")


@then(parsers.parse('the parsed rows of "{stage}" are:'))
def parsed_rows(ctx, stage, datatable):
    store = scratch(ctx) / "store"
    header, *body = datatable
    actual = []
    for item in latest_manifest(ctx, stage)["items"]:
        for output in item["outputs"]:
            for row in pq.read_table(store / output["key"]).to_pylist():
                actual.append({k: "" if row[k] is None else str(row[k]) for k in header})
    wanted = [{k: v.strip() for k, v in zip(header, line, strict=True)} for line in body]
    assert actual == wanted, "the rows are:\n" + "\n".join(str(r) for r in actual)


def latest_manifest(ctx, stage: str) -> dict:
    latest = list(stage_dir(ctx, stage).glob("*/latest.json"))
    assert len(latest) == 1, f"{stage} has {len(latest)} published parser versions"
    store = scratch(ctx) / "store"
    return json.loads((store / json.loads(latest[0].read_text())["manifest"]).read_text())


@then(parsers.parse('the published outputs of "{stage}" are:'))
def published_outputs(ctx, stage, datatable):
    store = scratch(ctx) / "store"
    actual = []
    for item in latest_manifest(ctx, stage)["items"]:
        for output in item["outputs"]:
            data = (store / output["key"]).read_bytes()
            holds = "" if output["name"].endswith(".zip") else data.decode("utf-8", "replace").strip()
            actual.append({"item": item["item_key"], "name": output["name"], "holds": holds})
    wanted = [{"item": a.strip(), "name": b.strip(), "holds": c.strip()} for a, b, c in datatable[1:]]
    assert sorted(actual, key=str) == sorted(wanted, key=str), f"the outputs are {actual}"


@then(parsers.parse('the notes of "{stage}" in the latest run are:'))
def latest_notes_are(ctx, stage, datatable):
    run_id = latest_manifest(ctx, stage)["run_id"]
    notes_are(ctx, stage, run_id, datatable)


@then(parsers.parse('the stage "{stage}" stores {count:d} objects'))
def stores_objects(ctx, stage, count):
    found = [p for p in stage_dir(ctx, stage).glob("*/objects/*/*") if p.is_file()]
    assert len(found) == count, f"{stage} stores {len(found)} objects"


@then(parsers.parse('the published "{name}" of "{stage}" lists:'))
def published_lists(ctx, name, stage, datatable):
    header, *body = datatable
    actual = [{k: str(entry[k]) for k in header} for entry in json.loads(published(ctx, stage, name))]
    wanted = [{k: v.strip() for k, v in zip(header, line, strict=True)} for line in body]
    assert actual == wanted, f"{name} lists {actual}"


@then(parsers.parse('the published "{name}" of "{stage}" gives "{entry}" the url "{url}"'))
def published_url(ctx, name, stage, entry, url):
    actual = listed(ctx, stage, name)[entry]["url"]
    assert actual == url, f"{entry}'s url is {actual}"


@then(parsers.parse('the published "{name}" of "{stage}" gives "{entry}" a url on the "{service}" service ending "{path}"'))
def published_url_on(ctx, name, stage, entry, service, path):
    actual = listed(ctx, stage, name)[entry]["url"]
    wanted = ctx.fakes[service].url + path
    assert actual == wanted, f"{entry}'s url is {actual}, not {wanted}"


@then(parsers.parse('the published "{name}" of "{stage}" includes "{text}"'))
def published_includes(ctx, name, stage, text):
    assert text in published(ctx, stage, name).decode("utf-8"), f"{name} does not include {text}"


@then(parsers.parse('the published output of "{stage}" holds:'))
def published_output(ctx, stage, docstring):
    latest = list(stage_dir(ctx, stage).glob("*/latest.json"))
    assert len(latest) == 1, f"{stage} has {len(latest)} published parser versions"
    store = scratch(ctx) / "store"
    manifest = json.loads((store / json.loads(latest[0].read_text())["manifest"]).read_text())
    outputs = [o for item in manifest["items"] if item["status"] != "failed" for o in item["outputs"]]
    assert len(outputs) == 1, f"{stage} published {len(outputs)} outputs"
    assert (store / outputs[0]["key"]).read_text(encoding="utf-8") == docstring + "\n"


@then(parsers.parse('the stored outputs of "{pin}" are still there'))
def still_there(ctx, pin):
    store = scratch(ctx) / "store"
    found = list(store.glob(f"*/{pin}/latest.json"))
    assert len(found) == 1, f"no stored run of {pin}"
    manifest = json.loads((store / json.loads(found[0].read_text())["manifest"]).read_text())
    for item in manifest["items"]:
        for output in item["outputs"]:
            assert (store / output["key"]).is_file(), f"{output['key']} is gone"


@then(parsers.parse('the run log\'s final row for "{stage}" in run "{run_id}" has "{key}" equal to "{wanted}"'))
def final_row_has(ctx, stage, run_id, key, wanted):
    actual = dig(final_row(ctx, stage, run_id), key)
    assert same(actual, wanted), f"{key} is {actual!r}, not {wanted!r}"


@then("the run log has the rows:")
def run_log_rows(ctx, datatable):
    header, *body = datatable
    actual = [{k: str(r[k]) for k in header} for r in rows(ctx)]
    wanted = [dict(zip(header, line, strict=True)) for line in body]
    assert actual == wanted, f"the run log holds {actual}"


@then(parsers.parse('the notes of "{stage}" in run "{run_id}" are:'))
def notes_are(ctx, stage, run_id, datatable):
    header, *body = datatable
    actual = [{k: str(n[k]) for k in header} for n in stage_notes(ctx, stage, run_id)]
    wanted = [{k: v.strip() for k, v in zip(header, line, strict=True)} for line in body]
    assert actual == wanted, f"the notes are {actual}"


@then(parsers.parse('the note ids of "{stage}" are the same in runs "{first}" and "{second}"'))
def same_note_ids(ctx, stage, first, second):
    one = [n["note_id"] for n in stage_notes(ctx, stage, first)]
    two = [n["note_id"] for n in stage_notes(ctx, stage, second)]
    assert one and one == two, f"{first}: {one}, {second}: {two}"


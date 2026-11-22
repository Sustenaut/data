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
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pubtest.core import dig, same
from pubtest.plugin import run_program
from pytest_bdd import given, parsers, scenarios, then

scenarios("runner.feature", "run_log.feature", "discover.feature", "download.feature", "select.feature")

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


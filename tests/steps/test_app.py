"""The go-auctions app's steps: a small merged database in the scenario's
scratch directory, the numbers src/app/data.py draws from it, and
the app itself, run by Streamlit's own test harness."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app import data
from ingest.canonical import auction_results

scenarios("app.feature")

REPOSITORY = Path(__file__).resolve().parents[2]
APP = REPOSITORY / "src" / "app" / "streamlit_app.py"


@pytest.fixture
def app():
    """What a scenario's steps hand each other."""
    return {}


def database(ctx) -> Path:
    assert ctx.directory is not None, "these steps need a scratch directory"
    return ctx.directory / "go-auctions.duckdb"


def number(text: str) -> float | None:
    return float(text) if text.strip() else None


@given("a merged database holding:")
def merged_database(ctx, app, datatable):
    header, *body = datatable
    rows = []
    for line in body:
        r = dict(zip(header, (v.strip() for v in line), strict=True))
        rows.append(
            {
                "provider": "eex",
                "market": "fr",
                "certificate_type": "go",
                "energy_carrier": "electricity",
                "auction_id": r["auction"],
                "auction_number": r["number"] or None,
                "auction_date": date.fromisoformat(r["date"]),
                "production_period_start": date.fromisoformat(r["production"]),
                "production_period_end": date.fromisoformat(r["production"]),
                "segment_level": "region_x_technology",
                "region": r["region"],
                "technology": r["technology"],
                "volume_offered_mwh": number(r["offered"]),
                "volume_allocated_mwh": number(r["sold"]),
                "price_weighted_avg_eur_mwh": number(r["price"]),
                "price_min_eur_mwh": None,
                "price_max_eur_mwh": None,
                "reserve_price_eur_mwh": None,
                "bidders_count": int(r["bidders"]),
                "winners_count": None,
                "extras": None,
                "source_name": "test.xlsx",
                "source_sha256": "0" * 64,
                "source_sheet": None,
                "source_row": len(rows) + 1,
                "parser_name": "test",
                "parser_version": "1.0.0",
            }
        )
    results = pa.Table.from_pylist(rows, schema=auction_results.SCHEMA)  # noqa: F841 - DuckDB reads it by name
    con = duckdb.connect(str(database(ctx)))
    con.execute("CREATE TABLE auction_results AS SELECT * FROM results")
    con.execute("CREATE TABLE build_info AS SELECT 'r1' AS run_id, TIMESTAMP '2025-03-01 06:00:00' AS built_at")
    con.close()
    con = data.connect(database(ctx))
    app["segments"] = data.all_segments(con)
    app["choices"] = data.choices(con, app["segments"])
    con.close()


def formatted(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def compare(actual: list[dict], datatable) -> None:
    header, *body = datatable
    wanted = [dict(zip(header, (v.strip() for v in line), strict=True)) for line in body]
    shown = [{k: formatted(row[k]) for k in header} for row in actual]
    assert shown == wanted, f"got {shown}"


@when(parsers.parse('the price distribution is drawn with {bins:d} bins spaced "{spacing}", counting "{weight}"'))
def draw_distribution(app, bins, spacing, weight):
    app["distribution"] = data.distribution(app["segments"], bins, spacing, weight)


@then(parsers.parse('the bin edges are "{edges}"'))
def bin_edges(app, edges):
    assert ", ".join(f"{e:.2f}" for e in app["distribution"].edges) == edges


@then("the bins hold:")
def bins_hold(app, datatable):
    _, *body = datatable
    wanted = {line[0].strip(): line[1].strip() for line in body}
    shown = {t: ", ".join(f"{h:g}" for h in heights) for t, heights in app["distribution"].heights.items()}
    assert shown == wanted, f"got {shown}"


@when("the summary is made, weighted by MWh")
def make_summary(app):
    app["rows"] = data.summary(app["segments"], weighted=True)


@then("the summary is:")
def summary_is(app, datatable):
    compare([{**r, "mwh_sold": int(r["mwh_sold"])} for r in app["rows"]], datatable)


@when(parsers.parse('the points over time are made by "{date_by}" date, weighted by MWh'))
def points_weighted(app, date_by):
    app["rows"] = data.over_time(app["segments"], date_by, weighted=True)


@when(parsers.parse('the points over time are made by "{date_by}" date, not weighted'))
def points_unweighted(app, date_by):
    app["rows"] = data.over_time(app["segments"], date_by, weighted=False)


@when("the regions' statistics are made, weighted by MWh")
def make_regions(app):
    app["rows"] = data.by_region(app["segments"], weighted=True)


@then("the regions' statistics are:")
def regions_are(app, datatable):
    compare([{**r, "mwh_sold": int(r["mwh_sold"])} for r in app["rows"]], datatable)


@then("the points are:")
def points_are(app, datatable):
    compare([{**p, "auction": p["auction_id"]} for p in app["rows"]], datatable)


FILTERS = {
    "dates": lambda v: data.Filters(start=date.fromisoformat(v)),
    "production from": lambda v: data.Filters(start=date.fromisoformat(v), date_by="production"),
    "regions": lambda v: data.Filters(regions=tuple(v.split(", "))),
    "technologies": lambda v: data.Filters(technologies=tuple(v.split(", "))),
    "min_share_sold": lambda v: data.Filters(min_share_sold=float(v)),
    "min_bidders": lambda v: data.Filters(min_bidders=int(v)),
    "max_bidders": lambda v: data.Filters(max_bidders=int(v)),
    "min_segment_mwh": lambda v: data.Filters(min_segment_mwh=float(v)),
    "max_segment_mwh": lambda v: data.Filters(max_segment_mwh=float(v)),
    "auction_numbers": lambda v: data.Filters(auction_numbers=(int(v), int(v))),
    "combine": lambda v: data.Filters(technologies=tuple(v.split(", ")), combine=True),
}


@when(parsers.parse('the segments are filtered with {name} set to "{value}"'))
def filtered(app, name, value):
    app["kept"] = data.select(app["segments"], FILTERS[name](value))


@then(parsers.parse('every segment kept is "{technology}"'))
def kept_as(app, technology):
    assert {s.technology for s in app["kept"]} == {technology}


@when(
    parsers.parse('the price distribution of those is drawn with {bins:d} bins spaced "{spacing}", counting "{weight}"')
)
def draw_kept_distribution(app, bins, spacing, weight):
    app["distribution"] = data.distribution(app["kept"], bins, spacing, weight)


@when(parsers.parse('the points over time of those are made by "{date_by}" date, weighted by MWh'))
def kept_points(app, date_by):
    app["rows"] = data.over_time(app["kept"], date_by, weighted=True)


@when(parsers.parse("the volume steps are made for a largest segment of {largest:g} MWh"))
def make_volume_steps(app, largest):
    app["steps"] = data.volume_steps(largest)


@then(parsers.parse('the volume steps are "{steps}"'))
def volume_steps(app, steps):
    assert ", ".join(f"{v:g}" for v in app["steps"]) == steps


@when(parsers.parse('the run link is made for a database built by a run with {field} "{value}"'))
def make_run_link(app, field, value):
    built = {field: value} if value != "-" else {}
    app["link"] = data.run_link(built, "https://console.example/executions/{execution}")


@then(parsers.parse('the run link is "{link}"'))
def run_link_is(app, link):
    assert (app["link"] or "none") == link, app["link"]


@then(parsers.parse('{count:d} segments are kept, from the auctions "{auctions}"'))
def kept(app, count, auctions):
    assert len(app["kept"]) == count, f"kept {len(app['kept'])}"
    assert ", ".join(sorted({s.auction_id for s in app["kept"]})) == auctions


def go_auctions() -> None:
    """The GO auctions page on its own, as AppTest runs a function."""
    from app.page import main  # noqa: PLC0415

    main()


def run_app(app, monkeypatch, env: dict[str, str], landing: bool = False) -> None:
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415 - only these scenarios need Streamlit

    for name in ("DATA_DATABASE", "DATA_STORE", "DATA_PIPELINE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(REPOSITORY)  # where the pipeline file is
    if landing:
        test = AppTest.from_file(str(APP), default_timeout=60)
    else:
        test = AppTest.from_function(go_auctions, default_timeout=60)
    test.run()
    app["test"] = test


@when("the app is opened on the database")
def open_app(ctx, app, monkeypatch):
    run_app(app, monkeypatch, {"DATA_DATABASE": str(database(ctx))})


@when("the site's landing page is opened")
def open_landing(ctx, app, monkeypatch):
    run_app(app, monkeypatch, {"DATA_DATABASE": str(database(ctx))}, landing=True)


@then(parsers.parse('the landing page links to "{page}" as "{label}"'))
def links_to(app, page, label):
    links = [(link.proto.page, link.proto.label) for link in app["test"].get("page_link")]
    assert (page, label) in links, links
    assert not app["test"].exception, [e.value for e in app["test"].exception]


@when(parsers.parse('the site is opened at "{path}"'))
def open_site_at(ctx, app, monkeypatch, path):
    from streamlit.navigation.page import calc_hash  # noqa: PLC0415 - how st.Page names a page's address

    run_app(app, monkeypatch, {"DATA_DATABASE": str(database(ctx))}, landing=True)
    # A browser opening data.sustenaut.eu/PATH asks for the page whose
    # address that is, by the same hash.
    app["test"]._page_hash = calc_hash(path)  # noqa: SLF001 - AppTest switches pages only by file
    app["test"].run()


@then(parsers.parse('the page\'s title is "{title}"'))
def page_title(app, title):
    assert [t.value for t in app["test"].title] == [title]


@when("the app is opened on an empty store")
def open_app_empty(ctx, app, monkeypatch):
    (ctx.directory / "store").mkdir()
    run_app(app, monkeypatch, {"DATA_STORE": str(ctx.directory / "store")})


def widget(test, control: str, label: str):
    kinds = {
        "radio": test.radio,
        "slider": test.slider,
        "multiselect": test.multiselect,
        "toggle": test.toggle,
        "number": test.number_input,
        "range": test.select_slider,
    }
    found = [w for w in kinds[control] if (w.key == label[1:] if label.startswith("#") else w.label == label)]
    assert found, f"the app has no {control} {label!r}"
    return found[0]


def value(control: str, text: str, current):
    if control == "multiselect":
        return text.split(", ")
    if control == "toggle":
        return text == "true"
    if control in ("slider", "number", "range"):
        parts = [type(current[0] if isinstance(current, (list, tuple)) else current)(p) for p in text.split(", ")]
        return tuple(parts) if len(parts) > 1 else parts[0]
    return text


@when("each control is set in turn:")
def set_controls(app, datatable):
    test = app["test"]
    _, *body = datatable
    for control, label, text in ([c.strip() for c in line] for line in body):
        found = widget(test, control, label)
        found.set_value(value(control, text, found.value)).run()
        assert not test.exception, f"after {label} = {text}: {[e.value for e in test.exception]}"


@then(parsers.parse('the app says "{text}"'))
def app_says(app, text):
    shown = [i.value for i in app["test"].info]
    assert text in shown, shown


@then("the app shows no error")
def no_error(app):
    test = app["test"]
    assert not test.exception, [e.value for e in test.exception]
    assert not test.error, [e.value for e in test.error]


@then(parsers.parse('the app has the tabs "{tabs}"'))
def has_tabs(app, tabs):
    assert ", ".join(t.label for t in app["test"].tabs) == tabs


@then(parsers.parse('the app\'s distribution page describes "{text}"'))
def describes(app, text):
    shown = " ".join(m.value for m in app["test"].tabs[0].markdown)
    assert text in shown, shown


@then(parsers.parse('the app shows the error "{text}"'))
def shows_error(app, text):
    errors = [e.value for e in app["test"].error]
    assert any(text in e for e in errors), errors

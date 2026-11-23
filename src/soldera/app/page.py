"""data.sustenaut.eu/power-auctions: the prices of France's guarantees of
origin auctions, from the merge stage's DuckDB. streamlit_app.py runs `main`
on every rerun; the page is here, in a module, so it is imported (and its
coverage measured) like the rest of soldera.

It reads the database named by SOLDERA_DATABASE, or else the newest one the
merge stage of SOLDERA_PIPELINE published in SOLDERA_STORE (a directory, or
gs://BUCKET read over its API), and looks for a newer one every ten minutes."""

from __future__ import annotations

import os
from datetime import date

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from soldera.app import data
from soldera.parsers.eex.results import REGION_NAMES

INK, MUTED, GRID = "#2b2b2a", "#6b6a66", "#e6e5e1"
FONT = dict(family="Inter, system-ui, sans-serif", size=13, color=INK)


@st.cache_data(ttl=600, show_spinner=False)
def database_path(named: str | None, store: str, pipeline: str) -> tuple[str, str]:
    """The database to read, and a key that changes with its content: the
    file named, or a local copy of the newest one published in the store."""
    if named:
        return named, f"{named}:{os.stat(named).st_mtime_ns}"
    key, sha256, storage = data.published_database(store, pipeline)
    return str(data.local_copy(storage, key, sha256)), sha256


@st.cache_resource(show_spinner="Reading the auction results…")
def load(path: str, version: str) -> tuple[list[data.Segment], data.Choices]:
    del version  # only part of the cache key
    con = data.connect(path)
    try:
        segments = data.all_segments(con)
        return segments, data.choices(con, segments)
    finally:
        con.close()


def region_name(code: str) -> str:
    return REGION_NAMES.get(code, code)


def euro(value: float | None) -> str:
    return "–" if value is None else f"€{value:,.2f}"


def mwh(value: float) -> str:
    if value >= 1e6:
        return f"{value / 1e6:,.1f} TWh"
    if value >= 1e3:
        return f"{value / 1e3:,.1f} GWh"
    return f"{value:,.0f} MWh"


def style(figure: go.Figure, height: int, legend_below: bool = False) -> go.Figure:
    figure.update_layout(
        height=height, font=FONT, plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=8, r=8, t=36, b=8), bargap=0.04, hoverlabel=dict(font=FONT, bgcolor="white"),
    )
    if legend_below:
        figure.update_layout(margin=dict(l=8, r=8, t=36, b=100))
    else:
        figure.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    figure.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID, zeroline=False)
    figure.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return figure


def sidebar(choices: data.Choices) -> data.Filters:
    side = st.sidebar
    side.header("Which auctions")
    date_by = side.radio("Date by", ["auction", "production"], horizontal=True,
                         format_func={"auction": "Auction date", "production": "Production month"}.get,
                         help="An auction sells the guarantees of one production month, usually two or three "
                              "months earlier. Choose which date the range and the time axis use.")
    first, last = ((choices.first_auction, choices.last_auction) if date_by == "auction"
                   else (choices.first_production, choices.last_production))
    start, end = side.slider("Dates", min_value=first, max_value=last, value=(first, last), format="MMM YYYY")
    technologies = side.multiselect("Technologies", data.TECHNOLOGIES, default=list(data.TECHNOLOGIES),
                                    format_func=data.LABELS.get)
    regions = side.multiselect("Regions", choices.regions, default=[], format_func=region_name,
                               placeholder="All regions",
                               help="Leave empty for every region. A few regions can pull a distribution; "
                                    "pick them to see which.")
    numbers = None
    with side.expander("Auction conditions"):
        if choices.lowest_number is not None and choices.highest_number is not None:
            low, high = st.slider("Auction numbers", choices.lowest_number, choices.highest_number,
                                  (choices.lowest_number, choices.highest_number),
                                  help="EEX's own numbering, which restarts each year. The first 2019 "
                                       "auctions have none, and are left out when this is narrowed.")
            if (low, high) != (choices.lowest_number, choices.highest_number):
                numbers = (low, high)
        share_low, share_high = st.slider(
            "Share of offered volume sold", 0, 100, (0, 100), format="%d%%",
            help="Of all the volume an auction offered, how much sold. An auction that sold nearly "
                 "everything was undersubscribed; one that sold little had more supply than bids.")
        bidders = st.slider("At least this many bidders", 0, choices.most_bidders, 0)
        min_mwh = st.number_input("Segments that sold at least (MWh)", min_value=0, value=0, step=100,
                                  help="Leave out a region's segment that sold less than this: a small "
                                       "segment's price rests on few certificates.")
    return data.Filters(start=start, end=end, date_by=date_by, technologies=tuple(technologies),
                        regions=tuple(regions) or None, min_segment_mwh=float(min_mwh),
                        min_share_sold=share_low / 100, max_share_sold=share_high / 100,
                        min_bidders=bidders, auction_numbers=numbers)


def describe(filters: data.Filters, selected: list[data.Segment]) -> str:
    auctions = len({s.auction_id for s in selected})
    where = ", ".join(region_name(r) for r in filters.regions) if filters.regions else "every region"
    by = "auction date" if filters.date_by == "auction" else "production month"
    return (f"{auctions} auction{'' if auctions == 1 else 's'} by {by} from {filters.start:%B %Y} to {filters.end:%B %Y}, in {where}.")


def summary_table(selected: list[data.Segment], weighted: bool) -> None:
    rows = data.summary(selected, weighted)
    st.dataframe(
        [{"Technology": data.LABELS[r["technology"]], "Auctions": r["auctions"], "Priced segments": r["segments"],
          "Sold nothing": r["unsold_segments"], "Sold": mwh(r["mwh_sold"]), "Lowest": euro(r["min"]),
          "Median": euro(r["median"]), "Mean": euro(r["mean"]), "Highest": euro(r["max"])} for r in rows],
        hide_index=True, width="stretch")


def distribution_tab(filters: data.Filters, selected: list[data.Segment]) -> None:
    left, middle, right = st.columns(3)
    bins = left.slider("Bins", 5, 120, 30,
                       help="Fewer bins smooth a sparse period; more show the detail of a busy one.")
    spacing = left.radio("Bin spacing", ["linear", "log"], horizontal=True,
                         format_func={"linear": "Equal width", "log": "Logarithmic"}.get,
                         help="Prices run from a few cents to several euros. Logarithmic bins give the many "
                              "low prices room, and the price axis becomes logarithmic too.")
    weight = middle.radio("Each segment counts", ["mwh", "segments"],
                          format_func={"mwh": "By the MWh it sold", "segments": "Once"}.get,
                          help="By MWh, the plot shows at what price the volume sold. Once, a small "
                               "segment counts as much as a big one.")
    share = middle.radio("Bar height", ["share", "absolute"], horizontal=True,
                         format_func={"share": "% of technology", "absolute": "Absolute"}.get,
                         help="As a share of each technology's total, technologies of different size "
                              "compare; absolute shows how much each sold.")
    layout = right.radio("Layout", ["panels", "overlay"], horizontal=True,
                         format_func={"panels": "One panel each", "overlay": "Overlaid"}.get)

    result = data.distribution(selected, bins, spacing, weight)
    if result is None:
        st.info("No segment sold anything with these filters.")
        return
    unit = "MWh sold" if weight == "mwh" else "segments"
    st.markdown(
        f"**Price distribution by technology.** {describe(filters, selected)} Each bar is a price range of "
        f"the guarantees' price in €/MWh. Its height is the {unit} whose region's volume-weighted average "
        f"price falls in that range"
        + (", as a share of the technology's total." if share == "share" else ".")
        + " EEX publishes one price per region, technology and auction, not single bids, so these are "
          "regional averages. Segments that sold nothing have no price and are left out; the table counts them.")

    technologies = list(result.heights)
    panels = layout == "panels"
    figure = (make_subplots(rows=len(technologies), cols=1, shared_xaxes=True, vertical_spacing=0.09,
                            subplot_titles=[data.LABELS[t] for t in technologies])
              if panels else go.Figure())
    centres = [(a + b) / 2 for a, b in zip(result.edges, result.edges[1:], strict=False)]
    widths = [b - a for a, b in zip(result.edges, result.edges[1:], strict=False)]
    ranges = [f"€{a:,.2f} – €{b:,.2f}" for a, b in zip(result.edges, result.edges[1:], strict=False)]
    for row, technology in enumerate(technologies, start=1):
        heights = result.heights[technology]
        total = result.totals[technology] or 1
        values = [h / total * 100 for h in heights] if share == "share" else heights
        shown = [f"{h / total:.1%} of {data.LABELS[technology].lower()}" for h in heights]
        amount = [mwh(h) if weight == "mwh" else f"{h:,.0f} segments" for h in heights]
        bar = go.Bar(
            x=centres, y=values, width=widths if spacing == "linear" else None, name=data.LABELS[technology],
            marker=dict(color=data.COLOURS[technology], opacity=0.85 if panels else 0.55,
                        line=dict(color="white", width=1)),
            customdata=list(zip(ranges, amount, shown, strict=True)),
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}<extra>"
                          + data.LABELS[technology] + "</extra>",
            showlegend=not panels, legendgroup=technology)
        if panels:
            figure.add_trace(bar, row=row, col=1)
        else:
            figure.add_trace(bar)
    if not panels:
        figure.update_layout(barmode="overlay")
    y_title = "% of technology" if share == "share" else unit
    figure.update_yaxes(title_text=y_title, title_font=dict(color=MUTED, size=12))
    figure.update_xaxes(type="log" if spacing == "log" else "linear")
    figure.update_xaxes(title_text="Price, €/MWh (each region's volume-weighted average)",
                        title_font=dict(color=MUTED, size=12), row=len(technologies) if panels else None, col=1
                        if panels else None)
    height = 170 * len(technologies) + 90 if panels else 440
    st.plotly_chart(style(figure, height), width="stretch", config={"displaylogo": False})
    summary_table(selected, weight == "mwh")


STAT_STYLE = {
    "max": dict(dash="dot", symbol="triangle-up"), "p90": dict(dash="dash", symbol="triangle-up-open"),
    "mean": dict(dash="solid", symbol="diamond"), "median": dict(dash="solid", symbol="circle"),
    "p10": dict(dash="dash", symbol="triangle-down-open"), "min": dict(dash="dot", symbol="triangle-down"),
}


def over_time_tab(filters: data.Filters, selected: list[data.Segment]) -> None:
    left, middle, right = st.columns([2, 1, 1])
    shown = left.multiselect("Statistics", data.STATISTICS, default=["median", "p10", "p90"],
                             format_func=data.STATISTIC_LABELS.get)
    weighted = middle.toggle("Weight by MWh sold", value=True,
                             help="Weighted, the mean is the price the technology's volume sold at, and the "
                                  "percentiles are of MWh. Unweighted, each region counts once.")
    band = middle.toggle("Shade 10th to 90th percentile", value=True,
                         help="The middle 80%: shaded when both percentiles are shown.")
    hover = right.radio("Hover shows", ["one", "all"], horizontal=True,
                        format_func={"one": "That technology", "all": "Every technology"}.get,
                        help="Every technology lists them all at the auction under the pointer.")
    layout = right.radio("Layout", ["panels", "overlay"], horizontal=True, key="time_layout",
                         format_func={"panels": "One panel each", "overlay": "Overlaid"}.get,
                         help="The technologies' prices are often close; one panel each keeps them apart.")
    points = data.over_time(selected, filters.date_by, weighted)
    if not points:
        st.info("No segment sold anything with these filters.")
        return
    by = "auction date" if filters.date_by == "auction" else "production month"
    st.markdown(
        f"**Prices over time, by technology.** {describe(filters, selected)} Each point is one auction and "
        f"technology, placed at its {by}. Its statistics are of that auction's regional prices: the "
        "volume-weighted average price of each region that sold something, "
        + ("weighted by the MWh each sold." if weighted else "each region counted once.")
        + " Lowest and highest are the lowest and highest regional average, not single bids.")

    technologies = [t for t in data.TECHNOLOGIES if any(p["technology"] == t for p in points)]
    panels = layout == "panels"
    figure = (make_subplots(rows=len(technologies), cols=1, shared_xaxes=True, shared_yaxes=True,
                            vertical_spacing=0.07, subplot_titles=[data.LABELS[t] for t in technologies])
              if panels else go.Figure())
    by_auction: dict[str, list[dict]] = {}
    for p in points:
        by_auction.setdefault(p["auction_id"], []).append(p)
    for row, technology in enumerate(technologies, start=1):
        mine = [p for p in points if p["technology"] == technology]
        colour, label = data.COLOURS[technology], data.LABELS[technology]
        x = [p["at"] for p in mine]
        text = [hover_text(p) if hover == "one" else hover_all(by_auction[p["auction_id"]]) for p in mine]
        place = dict(row=row, col=1) if panels else {}
        if band and "p10" in shown and "p90" in shown:
            figure.add_trace(go.Scatter(x=x + x[::-1], y=[p["p90"] for p in mine] + [p["p10"] for p in mine][::-1],
                                        fill="toself", fillcolor=colour, opacity=0.18, line=dict(width=0),
                                        hoverinfo="skip", showlegend=False, legendgroup=technology), **place)
        for stat in [s for s in data.STATISTICS if s in shown]:
            line_style = STAT_STYLE[stat]
            main = stat in ("median", "mean")
            figure.add_trace(go.Scatter(
                x=x, y=[p[stat] for p in mine], mode="lines+markers", name=label,
                legendgroup=technology, showlegend=False,
                line=dict(color=colour, width=2 if main else 1.2, dash=line_style["dash"]),
                marker=dict(color=colour, size=7 if main else 6, symbol=line_style["symbol"],
                            line=dict(color="white", width=1)),
                text=text, hovertemplate="%{text}<extra></extra>"), **place)
        if not panels:  # the panels' titles name them
            figure.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=label, legendgroup=technology,
                                        line=dict(color=colour, width=3)))
    for stat in [s for s in data.STATISTICS if s in shown]:  # what each line style means
        figure.add_trace(go.Scatter(x=[None], y=[None], mode="lines+markers", name=data.STATISTIC_LABELS[stat],
                                    line=dict(color=MUTED, width=1.5, dash=STAT_STYLE[stat]["dash"]),
                                    marker=dict(color=MUTED, size=7, symbol=STAT_STYLE[stat]["symbol"]),
                                    legendgroup="statistics"))
    figure.update_layout(hovermode="closest", legend=dict(orientation="h", y=-0.12 if not panels else -0.06,
                                                           yanchor="top", x=0, xanchor="left"))
    figure.update_yaxes(title_text="€/MWh", title_font=dict(color=MUTED, size=12))
    figure.update_xaxes(title_text=by.capitalize(), title_font=dict(color=MUTED, size=12),
                        **(dict(row=len(technologies), col=1) if panels else {}))
    height = 200 * len(technologies) + 140 if panels else 560
    st.plotly_chart(style(figure, height, legend_below=True), width="stretch", config={"displaylogo": False})
    summary_table(selected, weighted)


def hover_text(point: dict) -> str:
    number = f" (no. {point['auction_number']})" if point["auction_number"] is not None else ""
    lines = [
        f"<b>{data.LABELS[point['technology']]}</b>, auction of {point['auction_date']:%d %b %Y}{number}",
        f"production month {point['production_month']:%B %Y}",
        f"{point['regions']} regions sold {mwh(point['mwh_sold'])}"
        + (f", {point['unsold_regions']} sold nothing" if point["unsold_regions"] else ""),
    ]
    lines += [f"{data.STATISTIC_LABELS[s]}: {euro(point[s])}" for s in data.STATISTICS]
    if point["share_sold"] is not None:
        lines.append(f"auction sold {point['share_sold']:.0%} of its offer, {point['bidders']} bidders")
    return "<br>".join(lines)


def hover_all(points: list[dict]) -> str:
    """Every technology at one auction: its statistics, one line each."""
    first = points[0]
    number = f" (no. {first['auction_number']})" if first["auction_number"] is not None else ""
    title = (f"<b>Auction of {first['auction_date']:%d %b %Y}{number}</b>, "
             f"production month {first['production_month']:%B %Y}")
    lines = [title, "low · p10 · median · mean · p90 · high"]
    for p in points:
        values = " · ".join("–" if p[s] is None else f"{p[s]:.2f}" for s in ("min", "p10", "median", "mean", "p90", "max"))
        lines.append(f"{data.LABELS[p['technology']]}: €{values}")
    return "<br>".join(lines)


def main() -> None:
    st.set_page_config(page_title="Power auctions · Sustenaut", layout="wide")
    st.title("French guarantees of origin auctions")
    try:
        path, version = database_path(os.environ.get("SOLDERA_DATABASE") or None,
                                      os.environ.get("SOLDERA_STORE", "store"),
                                      os.environ.get("SOLDERA_PIPELINE", "pipelines/eex-french-power-auctions.yaml"))
        segments, choices = load(path, version)
    except (data.DataError, OSError, ValueError) as error:
        st.error(f"The auction results cannot be read: {error}")
        st.stop()
    built = choices.built
    st.caption(
        "Monthly auctions of French renewable power's guarantees of origin, run by EEX for the French state. "
        f"Data from {choices.first_auction:%B %Y} to {choices.last_auction:%B %Y}"
        + (f", built {built['built_at']:%d %b %Y %H:%M} UTC from run {built.get('run_id')}." if
           isinstance(built.get("built_at"), date) else "."))
    filters = sidebar(choices)
    selected = data.select(segments, filters)
    if not filters.technologies or not selected:
        st.info("No auction matches these filters.")
        return
    distribution, over_time = st.tabs(["Price distribution", "Prices over time"])
    with distribution:
        distribution_tab(filters, selected)
    with over_time:
        over_time_tab(filters, selected)

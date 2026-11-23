"""data.sustenaut.eu/power-auctions: the prices of France's guarantees of
origin auctions, from the merge stage's DuckDB, and data.sustenaut.eu's
landing page, which links to it. streamlit_app.py runs `site` on every
rerun, which routes / to `landing` and /power-auctions to `main`; the pages
are here, in a module, so they are imported (and their coverage measured)
like the rest of soldera.

It reads the database named by SOLDERA_DATABASE, or else the newest one the
merge stage of SOLDERA_PIPELINE published in SOLDERA_STORE (a directory, or
gs://BUCKET read over its API), and looks for a newer one every ten minutes."""

from __future__ import annotations

import json
import math
import os
from datetime import date
from functools import cache
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from soldera.app import data
from soldera.parsers.eex.results import REGION_NAMES

# Sustenaut's colours (Sustenaut/theme's tokens.json, v0.1.0), for what the
# plots draw themselves: text, rules and the outline between marks. The page
# around them takes the same tokens from .streamlit/config.toml, in light and
# dark, which the viewer switches between in the menu's Settings.
INKS = {
    "light": dict(ink="#17110c", muted="#5d4d3f", grid="#ddd4bf", surface="#fffdf6"),
    "dark": dict(ink="#f3efe2", muted="#b9ab95", grid="#3a2a1e", surface="#221911"),
}
FONT_FAMILY = '"Nunito Sans", system-ui, -apple-system, "Segoe UI", sans-serif'


def inks() -> dict[str, str]:
    """The plots' colours for the theme the viewer has, light until the
    browser has said."""
    return INKS["dark" if st.context.theme.type == "dark" else "light"]


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
    colours = inks()
    font = dict(family=FONT_FAMILY, size=13, color=colours["ink"])
    figure.update_layout(
        height=height, font=font, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=36, b=8), bargap=0.04,
        hoverlabel=dict(font=font, bgcolor=colours["surface"], bordercolor=colours["grid"]),
    )
    figure.update_annotations(font=dict(family=FONT_FAMILY, size=13, color=colours["ink"]))
    if legend_below:
        figure.update_layout(margin=dict(l=8, r=8, t=36, b=100))
    else:
        figure.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    figure.update_xaxes(showgrid=False, linecolor=colours["grid"], ticks="outside", tickcolor=colours["grid"],
                        zeroline=False, title_font=dict(color=colours["muted"], size=12))
    figure.update_yaxes(gridcolor=colours["grid"], zeroline=False, linecolor=colours["grid"],
                        title_font=dict(color=colours["muted"], size=12))
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
    combine = side.toggle("Combine them", value=False,
                          help="Plot the technologies chosen as one, instead of one each.")
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
        fewest, most = st.slider("Bidders", 0, choices.most_bidders, (0, choices.most_bidders),
                                 help="How many took part in the auction.")
        steps = data.volume_steps(choices.largest_segment_mwh)
        low_mwh, high_mwh = st.select_slider(
            "Segments that sold (MWh)", steps, value=(steps[0], steps[-1]), format_func=mwh,
            help="Leave out a region's segment that sold less, or more, than this. A small segment's "
                 "price rests on few certificates; a large one carries much of an auction's volume.")
    return data.Filters(start=start, end=end, date_by=date_by, technologies=tuple(technologies),
                        regions=tuple(regions) or None, min_segment_mwh=float(low_mwh),
                        max_segment_mwh=None if high_mwh == steps[-1] else float(high_mwh),
                        min_share_sold=share_low / 100, max_share_sold=share_high / 100,
                        min_bidders=fewest, max_bidders=None if most == choices.most_bidders else most,
                        auction_numbers=numbers, combine=combine and len(technologies) > 1)


def describe(filters: data.Filters, selected: list[data.Segment]) -> str:
    auctions = len({s.auction_id for s in selected})
    where = ", ".join(region_name(r) for r in filters.regions) if filters.regions else "every region"
    by = "auction date" if filters.date_by == "auction" else "production month"
    combined = ""
    if filters.combine:
        combined = (" Every technology combined." if len(filters.technologies) == len(data.TECHNOLOGIES) else
                    " Combined: " + ", ".join(data.LABELS[t] for t in filters.technologies) + ".")
    return (f"{auctions} auction{'' if auctions == 1 else 's'} by {by} from {filters.start:%B %Y} to "
            f"{filters.end:%B %Y}, in {where}.{combined}")


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
    widths = [b - a for a, b in zip(result.edges, result.edges[1:], strict=False)]
    ranges = [f"€{a:,.2f} – €{b:,.2f}" for a, b in zip(result.edges, result.edges[1:], strict=False)]
    for row, technology in enumerate(technologies, start=1):
        heights = result.heights[technology]
        total = result.totals[technology] or 1
        values = [h / total * 100 for h in heights] if share == "share" else heights
        shown = [f"{h / total:.1%} of {data.LABELS[technology].lower()}" for h in heights]
        amount = [mwh(h) if weight == "mwh" else f"{h:,.0f} segments" for h in heights]
        # Each bar starts at its bin's lower edge and is as wide as the bin, so
        # it fills the bin on a logarithmic axis too (left to Plotly, every
        # bar there would be as narrow as the lowest bin).
        bar = go.Bar(
            x=result.edges[:-1], y=values, width=widths, offset=0, name=data.LABELS[technology],
            marker=dict(color=data.COLOURS[technology], opacity=0.85 if panels else 0.55,
                        line=dict(color=inks()["surface"], width=1)),
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
    figure.update_yaxes(title_text=y_title)
    figure.update_xaxes(type="log" if spacing == "log" else "linear")
    figure.update_xaxes(title_text="Price, €/MWh (each region's volume-weighted average)",
                        row=len(technologies) if panels else None, col=1 if panels else None)
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

    technologies = [t for t in data.ORDER if any(p["technology"] == t for p in points)]
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
                            line=dict(color=inks()["surface"], width=1)),
                text=text, hovertemplate="%{text}<extra></extra>"), **place)
        if not panels:  # the panels' titles name them
            figure.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=label, legendgroup=technology,
                                        line=dict(color=colour, width=3)))
    for stat in [s for s in data.STATISTICS if s in shown]:  # what each line style means
        figure.add_trace(go.Scatter(x=[None], y=[None], mode="lines+markers", name=data.STATISTIC_LABELS[stat],
                                    line=dict(color=inks()["muted"], width=1.5, dash=STAT_STYLE[stat]["dash"]),
                                    marker=dict(color=inks()["muted"], size=7, symbol=STAT_STYLE[stat]["symbol"]),
                                    legendgroup="statistics"))
    figure.update_layout(hovermode="closest", legend=dict(orientation="h", y=-0.12 if not panels else -0.06,
                                                           yanchor="top", x=0, xanchor="left"))
    figure.update_yaxes(title_text="€/MWh")
    figure.update_xaxes(title_text=by.capitalize(), **(dict(row=len(technologies), col=1) if panels else {}))
    height = 200 * len(technologies) + 140 if panels else 560
    st.plotly_chart(style(figure, height, legend_below=True), width="stretch", config={"displaylogo": False})
    summary_table(selected, weighted)


# France's regions, simplified from France GeoJSON (gregoiredavid/france-geojson,
# from IGN's Admin Express, Licence Ouverte), each named by its ISO code as
# EEX's regions are. Corsica is in it, though EEX auctions none of its power.
REGIONS_GEOJSON = Path(__file__).with_name("france-regions.geojson")
MAP_MEASURES = {
    "mean": ("Mean price", "€/MWh"), "median": ("Median price", "€/MWh"),
    "min": ("Lowest price", "€/MWh"), "max": ("Highest price", "€/MWh"), "mwh_sold": ("Volume sold", "MWh"),
}
# One hue, light to dark, for a magnitude: Sustenaut's greens on each theme.
MAP_SCALES = {"light": [[0, "#eef2e2"], [0.5, "#7fae6a"], [1, "#1f5a2e"]],
              "dark": [[0, "#2e3523"], [0.5, "#5f8f3f"], [1, "#b9e27a"]]}


@cache
def region_outlines() -> dict[str, tuple[list, list]]:
    """Each region's outline as x and y to draw: longitude narrowed by the
    cosine of France's middle latitude, so the map keeps its shape on plain
    axes (Plotly's own maps fetch a world map from its CDN, which a page
    should not need), its rings apart by a None."""
    features = json.loads(REGIONS_GEOJSON.read_text(encoding="utf-8"))["features"]
    narrow = math.cos(math.radians(46.5))
    outlines = {}
    for feature in features:
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        x: list[float | None] = []
        y: list[float | None] = []
        for ring in (ring for polygon in polygons for ring in polygon):
            x += [lon * narrow for lon, _ in ring] + [None]
            y += [lat for _, lat in ring] + [None]
        outlines[feature["id"]] = (x, y)
    return outlines


def map_tab(filters: data.Filters, selected: list[data.Segment]) -> None:
    left, right = st.columns([2, 1])
    measure = left.radio("Colour by", list(MAP_MEASURES), horizontal=True, key="map_measure",
                         format_func=lambda m: MAP_MEASURES[m][0],
                         help="A region's prices are of its segments across every auction kept.")
    weighted = right.toggle("Weight by MWh sold", value=True, key="map_weighted",
                            help="Weighted, the mean is the price the region's volume sold at, and the "
                                 "median is of MWh. Unweighted, each auction's segment counts once.")
    rows = data.by_region(selected, weighted)
    shown = [r for r in rows if r[measure] is not None]
    if not shown:
        st.info("No segment sold anything with these filters.")
        return
    name, unit = MAP_MEASURES[measure]
    st.markdown(
        f"**{name} by region.** {describe(filters, selected)} Each region is coloured by the {name.lower()} "
        "of its segments across the auctions kept"
        + ((", weighted by the MWh each sold." if weighted else ", each counted once.") if measure in ("mean", "median")
           else ".")
        + " The colour scale is shared, so the maps compare. EEX auctions no power from Corsica, which is left grey.")

    technologies = [t for t in data.ORDER if any(r["technology"] == t for r in shown)]
    columns = 1 if len(technologies) == 1 else 2
    rows_needed = -(-len(technologies) // columns)
    figure = make_subplots(rows=rows_needed, cols=columns, subplot_titles=[data.LABELS[t] for t in technologies],
                           horizontal_spacing=0.03, vertical_spacing=0.06)
    colours = inks()
    scale = MAP_SCALES["dark" if colours is INKS["dark"] else "light"]
    low, high = min(r[measure] for r in shown), max(r[measure] for r in shown)
    for index, technology in enumerate(technologies):
        place = dict(row=index // columns + 1, col=index % columns + 1)
        mine = {r["region"]: r for r in shown if r["technology"] == technology}
        for region, (x, y) in region_outlines().items():
            row = mine.get(region)
            share = 0.5 if high == low or row is None else (row[measure] - low) / (high - low)
            figure.add_trace(go.Scatter(
                x=x, y=y, mode="lines", fill="toself", hoveron="fills", showlegend=False,
                fillcolor=sample_colorscale(scale, share)[0] if row else colours["grid"],
                line=dict(color=colours["surface"], width=1),
                text=region_hover(row, technology) if row else f"<b>{region_name(region)}</b>: nothing kept",
                hoverinfo="text"), **place)
    # The colour scale's key: one invisible point carries it.
    figure.add_trace(go.Scatter(x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip", marker=dict(
        color=[low], cmin=low, cmax=high, colorscale=scale, showscale=True,
        colorbar=dict(title=dict(text=unit, font=dict(color=colours["muted"], size=12)), thickness=12, len=0.6))))
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    for index in range(len(technologies)):  # France in its own proportions, in every panel
        suffix = "" if index == 0 else str(index + 1)
        figure.update_layout({f"yaxis{suffix}": dict(scaleanchor=f"x{suffix}", scaleratio=1)})
    st.plotly_chart(style(figure, 400 * rows_needed + 40), width="stretch", config={"displaylogo": False})
    st.dataframe(
        [{"Region": region_name(r["region"]), "Technology": data.LABELS[r["technology"]], "Auctions": r["auctions"],
          "Priced segments": r["segments"], "Sold nothing": r["unsold_segments"], "Sold": mwh(r["mwh_sold"]),
          "Lowest": euro(r["min"]), "Median": euro(r["median"]), "Mean": euro(r["mean"]), "Highest": euro(r["max"])}
         for r in rows], hide_index=True, width="stretch")


def region_hover(row: dict, technology: str) -> str:
    return "<br>".join([
        f"<b>{region_name(row['region'])}</b>, {data.LABELS[technology].lower()}",
        f"{row['auctions']} auctions, {row['segments']} priced segments, {mwh(row['mwh_sold'])} sold",
        f"mean {euro(row['mean'])}, median {euro(row['median'])}",
        f"lowest {euro(row['min'])}, highest {euro(row['max'])}",
    ])


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


def landing() -> None:
    """data.sustenaut.eu itself: what the site is, and a block per kind of data."""
    st.set_page_config(page_title="Sustenaut data", layout="wide")
    st.title("Sustenaut data")
    st.markdown("Data on renewable energy markets, collected from their publishers, checked, "
                "and kept with a record of where each figure came from.")
    st.subheader("Auction results")
    with st.container(border=True):
        st.page_link(power_auctions_page(), label="French guarantees of origin auctions", icon=":material/bar_chart:")
        st.markdown(
            "The monthly auctions in which the French state sells the guarantees of origin of the "
            "renewable power it supports, run by EEX. Prices by technology and region since the first "
            "auction: how they are distributed, and how they moved from one auction to the next.")


def power_auctions_page() -> st.Page:
    return st.Page(main, title="Power auctions", url_path="power-auctions")


def site() -> None:
    """Every address of data.sustenaut.eu: the landing page at /, the app at /power-auctions."""
    st.navigation([st.Page(landing, title="Sustenaut data", default=True), power_auctions_page()],
                  position="hidden").run()


def built_from(built: dict) -> str:
    """When the database was built and by which run, linked to where that
    run can be seen."""
    if not isinstance(built.get("built_at"), date):
        return "."
    run = str(built.get("run_id"))
    link = data.run_link(built, os.environ.get("SOLDERA_EXECUTION_URL") or None)
    return f", built {built['built_at']:%d %b %Y %H:%M} UTC from run " + (f"[{run}]({link})." if link else f"{run}.")


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
    st.caption(
        "Monthly auctions of French renewable power's guarantees of origin, run by EEX for the French state. "
        f"Data from {choices.first_auction:%B %Y} to {choices.last_auction:%B %Y}{built_from(choices.built)}")
    filters = sidebar(choices)
    selected = data.select(segments, filters)
    if not filters.technologies or not selected:
        st.info("No auction matches these filters.")
        return
    distribution, over_time, by_region = st.tabs(["Price distribution", "Prices over time", "By region"])
    with distribution:
        distribution_tab(filters, selected)
    with over_time:
        over_time_tab(filters, selected)
    with by_region:
        map_tab(filters, selected)

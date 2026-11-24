"""Stage 1, discover: read the EEX French auctions page and list every file
it links to.

eex-french-auction-page@1.0.0 fetches the page (`options.url`) and stores
two outputs:

- `page.html`, the page as fetched, so a later stage can cross-check the
  results the page shows against the files;
- `files.json`, one entry per linked file, in page order:

      {"url": "https://www.eex.com/fileadmin/.../20261119_GO_2026_GLOBAL_Results.zip",
       "name": "20261119_GO_2026_GLOBAL_Results.zip", "extension": "zip",
       "section": "Guarantees of Origin Data", "title": "GO 2026 Global Results",
       "published": "2026-11-19", "label": "zip (692 KB)"}

The page lists files in download tables (publishing date, title, file) under
an h2 heading, and in teaser boxes (a title and a button). A file linked more
than once is listed once, with what its download-table row says when it has
one. The stage lists every file; choosing the ones to use is stage 3's job.

The page changes when EEX publishes, so the stage is never cached. A page
with no linked files fails the item: the layout has most likely changed."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from ingest.core import http
from ingest.core.parser import Artifact, ItemResult, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register

# What counts as a file: a link whose path ends in one of these.
EXTENSIONS = ("zip", "xlsx", "xls", "csv", "pdf")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _Links(HTMLParser):
    """Collects file links with the heading, teaser or table row around them."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.found: list[dict[str, str]] = []
        self.section = ""
        self.capture: str | None = None  # "h2", "teaser" or a td data-field
        self.text: list[str] = []
        self.row: dict[str, str] | None = None
        self.link: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        if tag == "h2":
            self.begin("h2")
        elif tag == "p" and "teaserTitle" in attr.get("class", "").split():
            self.begin("teaser")
        elif tag == "tr":
            self.row = {}
        elif tag == "td" and self.row is not None and attr.get("data-field"):
            field = attr["data-field"]
            if field == "publishing_date" and attr.get("data-date"):
                self.row["published"] = attr["data-date"]
            self.begin(field)
        elif tag == "a" and attr.get("href"):
            self.open_link(attr)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.link is not None:
            self.link["label"] = clean(self.link["label"]) or self.link.pop("link_title", "")
            self.link.pop("link_title", None)
            self.found.append(self.link)
            self.link = None
        if self.capture and tag in ("h2", "p", "td"):
            text = clean("".join(self.text))
            if self.capture == "h2" or self.capture == "teaser":
                self.section = text
            elif self.row is not None and self.capture == "title":
                self.row["title"] = text
            elif self.row is not None and self.capture == "publishing_date":
                self.row.setdefault("published", text)
            self.capture = None
        if tag == "tr":
            self.row = None

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.text.append(data)
        if self.link is not None:
            self.link["label"] += data

    def begin(self, what: str) -> None:
        self.capture = what
        self.text = []

    def open_link(self, attr: dict[str, str]) -> None:
        url = urljoin(self.base, attr["href"])
        name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension not in EXTENSIONS:
            return
        row = self.row or {}
        self.link = {
            "url": url,
            "name": name,
            "extension": extension,
            "section": self.section,
            "title": row.get("title", "") or clean(attr.get("title", "")),
            "published": row.get("published", ""),
            "label": "",
            "link_title": clean(attr.get("title", "")),
            "in_table": "1" if self.row is not None else "",
        }


def files_on(page: str, base: str) -> list[dict[str, str]]:
    """Every file the page links to, once each, in page order."""
    links = _Links(base)
    links.feed(page)
    links.close()
    files: dict[str, dict[str, str]] = {}
    for link in links.found:
        in_table = link.pop("in_table")
        if link["url"] not in files or (in_table and not files[link["url"]]["_table"]):
            files[link["url"]] = {**link, "_table": in_table}
    return [{k: v for k, v in f.items() if k != "_table"} for f in files.values()]


@register
class Page(Parser):
    name = "eex-french-auction-page"
    version = "1.0.0"
    cacheable = False

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        url = ctx.options.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("the discover stage needs options.url, the EEX page to read")
        return [WorkItem(key="page", params=(("url", url),))]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        url = dict(item.params)["url"]
        answer = http.get(url)
        page = answer.body.decode("utf-8", "replace")
        files = files_on(page, answer.url)
        if not files:
            raise ValueError(f"{url} links to no files ({', '.join(EXTENSIONS)}); has the page layout changed?")
        listing = (json.dumps(files, indent=2, ensure_ascii=False) + "\n").encode()
        return ItemResult(
            [
                Output("page.html", answer.body, "text/html", None),
                Output("files.json", listing, "application/json", len(files)),
            ]
        )

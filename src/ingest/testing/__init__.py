"""Small parsers for exercising the stage runner without any real source:
a pipeline that lists `ingest.testing` in its plugins can use them. The
suite runs them through `data run`, as a person would.

- testing-files@1.0.0 reads the files of a directory (`options.dir`): a
  first stage, not cacheable, like a download from a page that can change.
- testing-upper@1.0.0 upper-cases each file. A file holding FAIL fails, and
  one holding NOTE gets a warning note. 2.0.0 also adds "!" to each line.
- testing-join@1.0.0 joins every file before it into one, in name order.
"""

from __future__ import annotations

from pathlib import Path

from ingest.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register


@register
class Files(Parser):
    name = "testing-files"
    version = "1.0.0"
    cacheable = False

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        root = Path(ctx.options["dir"])
        return [WorkItem(key=p.name, params=(("path", str(p)),)) for p in sorted(root.iterdir()) if p.is_file()]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        path = Path(dict(item.params)["path"])
        return ItemResult([Output(path.name, path.read_bytes(), "text/plain")])


@register
class Upper(Parser):
    name = "testing-upper"
    version = "1.0.0"

    def line(self, text: str) -> str:
        return text.upper()

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        text = ctx.read(item.inputs[0]).decode()
        if "FAIL" in text:
            raise ValueError(f"{item.key} asks to fail")
        notes = [Note("testing_note", f"{item.key} holds a note", subject=item.key)] if "NOTE" in text else []
        lines = [self.line(line) for line in text.splitlines()]
        return ItemResult([Output(item.key, ("\n".join(lines) + "\n").encode(), "text/plain", len(lines))], notes)


@register
class UpperLoud(Upper):
    version = "2.0.0"

    def line(self, text: str) -> str:
        return text.upper() + "!"


@register
class Join(Parser):
    name = "testing-join"
    version = "1.0.0"

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        return [WorkItem(key="joined", inputs=tuple(sorted(upstream, key=lambda a: a.name)))] if upstream else []

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        text = "".join(ctx.read(a).decode() for a in item.inputs)
        return ItemResult([Output("joined.txt", text.encode(), "text/plain", text.count("\n"))])

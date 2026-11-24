"""What a parser is: a named, versioned transformation that a stage runs.

A parser says what work a stage has (`plan`) and does one piece of it
(`transform`). It never touches storage, the run log or other items: the
runner does all of that, the same way for every parser."""

from __future__ import annotations

import hashlib
import inspect
import sys
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ingest.core.storage import LocalStorage


@dataclass(frozen=True)
class Artifact:
    """A stored output a parser reads: where it is, its hash, its name and type."""

    key: str
    sha256: str
    size: int
    name: str
    media_type: str = "application/octet-stream"
    item_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "sha256": self.sha256,
            "size": self.size,
            "name": self.name,
            "media_type": self.media_type,
            "item_key": self.item_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        return cls(
            data["key"],
            data["sha256"],
            data["size"],
            data["name"],
            data.get("media_type", "application/octet-stream"),
            data.get("item_key", ""),
        )


@dataclass(frozen=True)
class WorkItem:
    """One sub-stage: a key people recognise, the artifacts it reads, and any
    parameters that change its output (a URL, for a stage with no input)."""

    key: str
    inputs: tuple[Artifact, ...] = ()
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Output:
    name: str
    data: bytes
    media_type: str = "application/octet-stream"
    rows: int | None = None


@dataclass(frozen=True)
class Note:
    """Something a reader of the data should know, found while transforming:
    a missing auction, a file left out, a total that does not match."""

    kind: str
    message: str
    subject: str = ""
    severity: str = "warning"


@dataclass
class ItemResult:
    outputs: list[Output] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


class StageContext:
    """What a parser may use: the stage's options, read access to inputs, and
    the run it is part of.

    `earlier_notes` are the notes.parquet files of every stage before this
    one, from the very runs whose output this stage reads, as artifacts: a
    stage that publishes the notes (a merge into the app's database) copies
    them, so they say the same everywhere."""

    def __init__(  # noqa: PLR0913 - what a stage gives its parser; past stage, keyword-only
        self,
        storage: LocalStorage,
        options: dict[str, Any],
        stage: str,
        *,
        run_id: str = "",
        pipeline: str = "",
        parser: type[Parser] | None = None,
        earlier_notes: tuple[Artifact, ...] = (),
    ):
        self._storage = storage
        self.options = options
        self.stage = stage
        self.run_id = run_id
        self.pipeline = pipeline
        self.parser = parser
        self.earlier_notes = earlier_notes

    def read(self, artifact: Artifact) -> bytes:
        return self._storage.get_bytes(artifact.key)

    def note_records(self, notes: list[Note], item: WorkItem, run_id: str | None = None) -> list[dict[str, Any]]:
        """The notes as the runner stores them for this item, so a parser
        that also publishes its own notes writes the very same rows."""
        from ingest.core import notes as notes_mod  # noqa: PLC0415 - notes imports this module

        source = item.inputs[0] if item.inputs else None
        return [
            notes_mod.record(
                n,
                run_id=run_id or self.run_id,
                pipeline=self.pipeline,
                stage=self.stage,
                parser_name=self.parser.name if self.parser else "",
                parser_version=self.parser.version if self.parser else "",
                item_key=item.key,
                source_key=source.key if source else "",
                source_sha256=source.sha256 if source else "",
            )
            for n in notes
        ]


class Parser:
    """Subclass, set `name` and `version`, and implement `transform`.

    The default `plan` makes one work item per output of the stage before.
    A first stage, which has no stage before it, overrides `plan`. A stage
    whose output depends on more than its inputs and parameters (a web page
    that changes) sets `cacheable = False`."""

    name: ClassVar[str]
    version: ClassVar[str]
    cacheable: ClassVar[bool] = True

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        return [WorkItem(key=a.name, inputs=(a,)) for a in upstream]

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        raise NotImplementedError

    @classmethod
    def ref(cls) -> str:
        return f"{cls.name}@{cls.version}"

    @classmethod
    def code_hash(cls) -> str:
        """The hash of the module the parser is defined in, so an edit made
        without a version bump still shows in the run log."""
        module = sys.modules[cls.__module__]
        try:
            source = inspect.getsource(module)
        except (OSError, TypeError):
            source = cls.__qualname__
        return hashlib.sha256(source.encode()).hexdigest()[:16]

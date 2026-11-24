"""Stage 2, download: fetch every file stage 1 listed, one item each.

eex-french-auction-download@1.0.0 reads `files.json` from the discover stage
and makes one item per file, keyed by its name. Each item fetches the file
and stores it as fetched. An archive (zip) also has each of its files stored
as an output of its own, named by its path inside the archive, so the stages
after this one see every file EEX publishes, whether it came loose or in an
archive.

Only files on the EEX site (`options.site`) are fetched; a link elsewhere
fails its item. Outputs are stored by their content, so a file that has not
changed since the last run costs no space, and the stages after this one,
which are keyed by their inputs' hashes, reuse what they stored for it.

The stage fetches on every run, since EEX can replace a file under the same
name."""

from __future__ import annotations

import io
import json
import mimetypes
import posixpath
import zipfile
import zlib

from ingest.core import http
from ingest.core.parser import Artifact, ItemResult, Note, Output, Parser, StageContext, WorkItem
from ingest.core.registry import register

LISTING = "files.json"
MAX_FILE = 200 * 1024 * 1024      # what one download may be
MAX_UNPACKED = 500 * 1024 * 1024  # what one archive may unpack to
MAX_MEMBERS = 2000


def media_type(name: str) -> str:
    known = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             ".csv": "text/csv", ".zip": "application/zip", ".pdf": "application/pdf"}
    extension = posixpath.splitext(name)[1].lower()
    return known.get(extension) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def unpack(name: str, data: bytes) -> tuple[list[Output], list[Note]]:
    """Each file in the archive, by its path inside it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError(f"{name} is not a readable zip archive: {error}") from error
    members = [m for m in archive.infolist() if not m.is_dir()]
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"{name} holds {len(members)} files, more than {MAX_MEMBERS}")
    if sum(m.file_size for m in members) > MAX_UNPACKED:
        raise ValueError(f"{name} unpacks to more than {MAX_UNPACKED // (1024 * 1024)} MB")
    outputs, notes, total = [], [], 0
    for member in members:
        path = posixpath.normpath(member.filename.replace("\\", "/")).lstrip("/")
        if path.startswith("../") or path in ("", ".", ".."):
            raise ValueError(f"{name} holds a file with an unsafe path: {member.filename!r}")
        if posixpath.basename(path).startswith(".") or path.startswith("__MACOSX/"):
            notes.append(Note("archive_member_skipped", f"{name}: {path} is an operating system file, left out",
                              subject=f"{name}/{path}", severity="info"))
            continue
        try:
            content = archive.read(member)
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as error:
            raise ValueError(f"{name}: cannot read {path}: {error}") from error
        total += len(content)
        if total > MAX_UNPACKED:
            raise ValueError(f"{name} unpacks to more than {MAX_UNPACKED // (1024 * 1024)} MB")
        outputs.append(Output(path, content, media_type(path)))
    return outputs, notes


@register
class Download(Parser):
    name = "eex-french-auction-download"
    version = "1.0.0"
    cacheable = False

    def plan(self, upstream: list[Artifact], ctx: StageContext) -> list[WorkItem]:
        listings = [a for a in upstream if a.name == LISTING]
        if len(listings) != 1:
            raise ValueError(f"the stage before download must publish one {LISTING}; it published {len(listings)}")
        items = []
        for entry in json.loads(ctx.read(listings[0])):
            items.append(WorkItem(key=entry["name"], params=(("url", entry["url"]),)))
        keys = [i.key for i in items]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{LISTING} names a file twice")
        return items

    def transform(self, item: WorkItem, ctx: StageContext) -> ItemResult:
        url = dict(item.params)["url"]
        site = str(ctx.options.get("site") or "").rstrip("/")
        if not site or not url.startswith(site + "/"):
            raise ValueError(f"{url} is not on {site or 'the site (options.site is not set)'}; only its files are fetched")
        answer = http.get(url)
        if len(answer.body) > MAX_FILE:
            raise ValueError(f"{url} is {len(answer.body)} bytes, more than {MAX_FILE}")
        outputs = [Output(item.key, answer.body, media_type(item.key))]
        notes: list[Note] = []
        if item.key.lower().endswith(".zip"):
            members, notes = unpack(item.key, answer.body)
            names = {o.name for o in outputs}
            for member in members:
                if member.name in names:
                    raise ValueError(f"{item.key} holds a file named like the archive itself: {member.name}")
                outputs.append(member)
        return ItemResult(outputs, notes)

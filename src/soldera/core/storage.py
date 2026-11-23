"""Where stage outputs live. Keys are relative paths such as
`02-download/eex-french-auction-download@1.0.0/objects/ab/ab12…`. Every write is atomic:
a reader sees the whole object or none of it.

LocalStorage keeps them under a directory. In the Cloud Run job that
directory is a Cloud Storage bucket, mounted with Cloud Storage FUSE, and
`uri_base` (gs://BUCKET) makes the run log name each object by its gs:// URI,
which BigQuery's stage_notes table reads."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Stored:
    """An object as written: its key, content hash and size."""

    key: str
    sha256: str
    size: int


class LocalStorage:
    def __init__(self, root: str | Path, uri_base: str | None = None):
        self.root = Path(root).resolve()
        self.uri_base = uri_base.rstrip("/") if uri_base else None

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"key {key!r} is outside the store")
        return path

    def path(self, key: str) -> Path:
        """Where the object is on disk, for a person to open."""
        return self._path(key)

    def uri(self, key: str) -> str:
        path = self._path(key)
        if self.uri_base:
            return f"{self.uri_base}/{path.relative_to(self.root).as_posix()}"
        return path.as_uri()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put_bytes(self, key: str, data: bytes) -> Stored:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return Stored(key, hashlib.sha256(data).hexdigest(), len(data))

    def put_object(self, prefix: str, data: bytes) -> Stored:
        """Store bytes by their hash under `prefix/objects/`, once: the same
        content stored again, by any item or run, is the same object."""
        digest = hashlib.sha256(data).hexdigest()
        key = f"{prefix}/objects/{digest[:2]}/{digest}"
        if self.exists(key):
            return Stored(key, digest, len(data))
        return self.put_bytes(key, data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def put_json(self, key: str, data: Any) -> Stored:
        return self.put_bytes(key, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_bytes(key))

    def get_json_or_none(self, key: str) -> Any:
        return self.get_json(key) if self.exists(key) else None

"""Where stage outputs live. Keys are relative paths such as
`02-download/eex-french-auction-download@1.0.0/objects/ab/ab12…`. Every write is atomic:
a reader sees the whole object or none of it.

LocalStorage keeps them under a directory. In the Cloud Run job that
directory is a Cloud Storage bucket, mounted with Cloud Storage FUSE, and
`uri_base` (gs://BUCKET) makes the run log name each object by its gs:// URI,
which BigQuery's stage_notes table reads.

GcsReader reads the same keys from the bucket over its API, for what reads
the store without mounting it: the app, and `data output --store gs://`."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingest.core import http

GS = "gs://"
READ_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"


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

    def copy_to(self, key: str, target: str | Path) -> None:
        shutil.copyfile(self._path(key), target)


class GcsReader:
    """A store in a Cloud Storage bucket, read over its JSON API as Google's
    default credentials (the service's account on Cloud Run): what the app
    reads, where no bucket is mounted. STORAGE_URL points it elsewhere."""

    def __init__(self, uri: str):
        bucket, _, prefix = uri.removeprefix(GS).partition("/")
        if not uri.startswith(GS) or not bucket:
            raise ValueError(f"{uri!r} is not gs://BUCKET")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        self.base = os.environ.get("STORAGE_URL", "https://storage.googleapis.com").rstrip("/")
        self._credentials = None

    def _name(self, key: str) -> str:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"key {key!r} is outside the store")
        return f"{self.prefix}/{key}" if self.prefix else key

    def path(self, key: str) -> str:
        return f"{GS}{self.bucket}/{self._name(key)}"

    def _get(self, key: str) -> bytes | None:
        import google.auth  # noqa: PLC0415 - only a store in a bucket needs it
        from google.auth import exceptions  # noqa: PLC0415

        url = f"{self.base}/storage/v1/b/{self.bucket}/o/{urllib.parse.quote(self._name(key), safe='')}?alt=media"
        headers: dict[str, str] = {}
        try:
            if self._credentials is None:
                self._credentials, _ = google.auth.default(scopes=[READ_SCOPE])
            self._credentials.before_request(http.GoogleTransport(), "GET", url, headers)
            answer = http.send("GET", url, headers=headers, timeout=120, raise_for_status=False)
        except (http.HttpError, exceptions.GoogleAuthError) as error:
            raise OSError(f"cannot read {self.path(key)}: {error}") from error
        if answer.status == 404:
            return None
        if answer.status != 200:
            detail = answer.body.decode("utf-8", "replace").strip()[:300]
            raise OSError(f"cannot read {self.path(key)}: {answer.status} {detail}")
        return answer.body

    def exists(self, key: str) -> bool:
        return self._get(key) is not None

    def get_bytes(self, key: str) -> bytes:
        data = self._get(key)
        if data is None:
            raise FileNotFoundError(self.path(key))
        return data

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_bytes(key))

    def get_json_or_none(self, key: str) -> Any:
        data = self._get(key)
        return None if data is None else json.loads(data)

    def copy_to(self, key: str, target: str | Path) -> None:
        Path(target).write_bytes(self.get_bytes(key))


def open_store(spec: str | Path, uri_base: str | None = None) -> LocalStorage | GcsReader:
    """A directory, or gs://BUCKET to read a bucket over its API."""
    if str(spec).startswith(GS):
        return GcsReader(str(spec))
    return LocalStorage(spec, uri_base)


def latest_outputs(
    storage: LocalStorage | GcsReader, prefix: str, name: str | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The newest published run of the stage stored under `prefix` (its
    latest.json), and its outputs, those named `name` only when given."""
    latest = storage.get_json_or_none(f"{prefix}/latest.json")
    if latest is None:
        raise LookupError(f"{prefix} has published nothing")
    manifest = storage.get_json(latest["manifest"])
    return latest, [o for item in manifest["items"] for o in item["outputs"] if name in (None, o["name"])]

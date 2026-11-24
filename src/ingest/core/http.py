"""The one way the ingest pipeline talks to the web: a request with a timeout, a plain
User-Agent, and an error that says which URL answered what. It honours the
usual proxy variables (HTTPS_PROXY, NO_PROXY). `GoogleTransport` lets
google-auth sign in over the same code, so no other HTTP library is needed."""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from ingest import __version__, setting

USER_AGENT = f"sustenaut-data/{__version__} (+https://data.sustenaut.eu)"
TRIES = 3
# Answers worth asking again for: the server is busy or briefly broken.
RETRY_STATUSES = (429, 500, 502, 503, 504)


class HttpError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)


def get(url: str, timeout: float = 60, headers: dict[str, str] | None = None) -> Response:
    return send("GET", url, timeout=timeout, headers=headers)


def send(  # noqa: PLR0913 - one HTTP call: method, url and body, the rest keyword-only
    method: str,
    url: str,
    body: bytes | None = None,
    *,
    timeout: float = 60,
    headers: dict[str, str] | None = None,
    raise_for_status: bool = True,
) -> Response:
    """One request, tried up to TRIES times when the transfer is cut off,
    the connection drops or times out, or the server answers 429 or 5xx.
    Waits 1 s, then 2 s, between tries (DATA_HTTP_RETRY_DELAY sets the
    first wait). Any other answer is final."""
    if not url.startswith(("https://", "http://")):
        raise HttpError(f"{url} is not an http(s) URL")
    delay = float(setting("HTTP_RETRY_DELAY", "1"))
    for attempt in range(1, TRIES + 1):
        last = attempt == TRIES
        after = f" after {TRIES} tries" if attempt > 1 else ""
        request = urllib.request.Request(
            url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 (scheme checked above)
                return Response(answer.geturl(), answer.status, dict(answer.headers.items()), answer.read())
        except urllib.error.HTTPError as error:
            if error.code in RETRY_STATUSES and not last:
                time.sleep(delay * attempt)
                continue
            if not raise_for_status:
                return Response(url, error.code, dict(error.headers.items()), error.read())
            detail = error.read().decode("utf-8", "replace").strip()[:500]
            raise HttpError(
                f"{method} {url} answered {error.code} {error.reason}{after}" + (f": {detail}" if detail else "")
            ) from error
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
            if not last:
                time.sleep(delay * attempt)
                continue
            raise HttpError(f"{method} {url} failed{after}: {describe(error)}") from error
    raise AssertionError("unreachable")  # pragma: no cover


def describe(error: Exception) -> str:
    if isinstance(error, http.client.IncompleteRead):
        return f"the transfer was cut off after {len(error.partial)} bytes, {error.expected} short"
    return str(getattr(error, "reason", error))


class GoogleTransport:
    """google.auth.transport.Request, over `send`: what google-auth calls to
    fetch a token."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=60, **kwargs):  # noqa: ANN001, ARG002
        from google.auth import exceptions  # noqa: PLC0415

        if isinstance(body, str):
            body = body.encode()
        try:
            answer = send(method, url, body, timeout=timeout or 60, headers=headers, raise_for_status=False)
        except HttpError as error:
            raise exceptions.TransportError(str(error)) from error
        return GoogleResponse(answer)


class GoogleResponse:
    def __init__(self, answer: Response):
        self.status = answer.status
        self.headers = {k.lower(): v for k, v in answer.headers.items()}
        self.data = answer.body

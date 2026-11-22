"""The one way soldera fetches from the web: a GET with a timeout, a plain
User-Agent, and an error that says which URL answered what. It honours the
usual proxy variables (HTTPS_PROXY, NO_PROXY)."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from soldera import __version__

USER_AGENT = f"soldera/{__version__} (+https://data.sustenaut.eu)"


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
    if not url.startswith(("https://", "http://")):
        raise HttpError(f"{url} is not an http(s) URL")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 (scheme checked above)
            return Response(answer.geturl(), answer.status, dict(answer.headers.items()), answer.read())
    except urllib.error.HTTPError as error:
        raise HttpError(f"GET {url} answered {error.code} {error.reason}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HttpError(f"GET {url} failed: {getattr(error, 'reason', error)}") from error

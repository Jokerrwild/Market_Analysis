from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FetchError(RuntimeError):
    pass


def fetch_json(url: str, timeout_seconds: int = 8) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MarketPulse/0.1 (+local analysis app)",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise FetchError(f"Network error for {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"Invalid JSON from {url}") from exc

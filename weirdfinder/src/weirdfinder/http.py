"""A small polite HTTP client: one request at a time, backs off, never hammers.

This runs unattended on a schedule against someone else's store, so the
defaults are deliberately slow rather than fast.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    """A request failed after exhausting retries."""


class Client:
    """Rate-limited, retrying HTTP client with a per-host delay."""

    def __init__(
        self,
        user_agent: str,
        timeout: float = 20.0,
        delay: float = 1.5,
        retries: int = 4,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            last = self._last_hit.get(host)
            now = time.monotonic()
            if last is not None:
                remaining = self.delay - (now - last)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_hit[host] = time.monotonic()

    def get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        """GET with retries. Raises FetchError once the budget is spent."""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_turn(url)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("GET %s failed (%s), attempt %d", url, exc, attempt + 1)
            else:
                if resp.status_code in RETRY_STATUS:
                    last_error = FetchError(f"HTTP {resp.status_code} from {url}")
                    log.warning(
                        "GET %s returned %d, attempt %d",
                        url,
                        resp.status_code,
                        attempt + 1,
                    )
                    # Honour Retry-After when the server bothers to send one.
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 120))
                        continue
                elif resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} from {url}")
                else:
                    return resp
            if attempt < self.retries:
                backoff = (2**attempt) + random.uniform(0, 0.5)
                time.sleep(backoff)
        raise FetchError(f"giving up on {url}: {last_error}")

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET and decode JSON, tolerating stores that mislabel content types."""
        resp = self.get(url, params=params)
        try:
            return resp.json()
        except ValueError as exc:
            raise FetchError(f"non-JSON response from {url}: {exc}") from None

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return self.get(url, params=params).text

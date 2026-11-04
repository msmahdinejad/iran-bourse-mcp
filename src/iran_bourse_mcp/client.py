"""Async HTTP client with retries, a small TTL cache and a concurrency limit."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlsplit

import httpx

# httpx logs every request at INFO, which would drown MCP/stdio and CLI output.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

RETRY_STATUS = {403, 408, 425, 429, 502, 503, 504}
RATE_LIMIT_COOLDOWN = 60.0  # seconds a host that answered HTTP 429 is left alone, so optional calls fail fast instead of piling up

NETWORK_HINT = (
    "TSETMC and Codal mostly serve Iranian IP addresses. Run this server on a machine in Iran "
    "(not behind a foreign VPN), or set IRAN_BOURSE_PROXY to an in-Iran proxy."
)


class UpstreamError(RuntimeError):
    """The upstream server could not give us usable data."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class NotAvailable(UpstreamError):
    """The endpoint answered with a structural error (HTTP 500/404) for this input."""


class Http:
    def __init__(
        self,
        *,
        timeout: float | None = None,
        concurrency: int = 6,
        proxy: str | None = None,
        max_cache_entries: int = 96,
        max_cache_bytes: int = 48 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout or float(os.environ.get("IRAN_BOURSE_TIMEOUT", "45"))
        self._proxy = proxy or os.environ.get("IRAN_BOURSE_PROXY") or None
        self._sem = asyncio.Semaphore(concurrency)
        self._cache: OrderedDict[str, tuple[float, Any, int]] = OrderedDict()
        self._cache_bytes = 0
        self._cooldown: dict[str, float] = {}  # host -> monotonic time until which it is rate-limiting us
        self._max_cache = max_cache_entries
        self._max_cache_bytes = max_cache_bytes
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "headers": {
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.5",
                },
                "timeout": httpx.Timeout(self._timeout, connect=15.0),
                "follow_redirects": True,
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            elif self._proxy:
                kwargs["proxy"] = self._proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _cache_get(self, key: str) -> Any | None:
        hit = self._cache.get(key)
        if hit is None:
            return None
        expires, data, _size = hit
        if expires < time.monotonic():
            self._evict(key)
            return None
        self._cache.move_to_end(key)
        return data

    def _evict(self, key: str) -> None:
        entry = self._cache.pop(key, None)
        if entry is not None:
            self._cache_bytes -= entry[2]

    def _cache_put(self, key: str, data: Any, ttl: float, size: int = 0) -> None:
        """Cache with both an entry cap and a byte budget (a day of ticks is megabytes of JSON)."""
        if ttl <= 0 or size > self._max_cache_bytes // 2:
            return
        self._evict(key)
        self._cache[key] = (time.monotonic() + ttl, data, size)
        self._cache_bytes += size
        while len(self._cache) > self._max_cache or self._cache_bytes > self._max_cache_bytes:
            oldest = next(iter(self._cache))
            self._evict(oldest)

    async def get(self, url: str, *, ttl: float = 0.0, retries: int = 4, as_json: bool = True) -> Any:
        key = f"{'j' if as_json else 't'}:{url}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        host = urlsplit(url).netloc
        waiting = self._cooldown.get(host, 0.0) - time.monotonic()
        if waiting > 0:
            raise UpstreamError(
                f"{host} is rate-limiting this client (HTTP 429). Not asking again for about {int(waiting) + 1} s; "
                "retry later and avoid parallel requests.",
                status=429,
                url=url,
            )

        client = self._get_client()
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                async with self._sem:
                    response = await client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            status = response.status_code
            if status == 200:
                data = self._decode(response, as_json, url)
                self._cache_put(key, data, ttl, len(response.content))
                return data
            if status == 204:
                self._cache_put(key, None, ttl)
                return None
            if status in RETRY_STATUS:
                last_error = UpstreamError(f"HTTP {status}", status=status, url=url)
                await asyncio.sleep(0.6 * (2**attempt))
                continue
            if status in (400, 404, 500):
                if status == 500 and attempt == 0 and retries > 1:
                    await asyncio.sleep(0.4)
                    continue
                raise NotAvailable(
                    f"HTTP {status} from {url} (usually: not applicable to this instrument type "
                    "or date, or the endpoint changed)",
                    status=status,
                    url=url,
                )
            raise UpstreamError(f"HTTP {status} from {url}", status=status, url=url)

        if isinstance(last_error, UpstreamError) and last_error.status == 429:
            self._cooldown[host] = time.monotonic() + RATE_LIMIT_COOLDOWN
            raise UpstreamError(
                f"Rate-limited by {host} (HTTP 429) after {retries} tries. Wait a minute or two and avoid parallel requests; "
                "this is a request-rate limit, not an Iranian-IP problem.",
                status=429,
                url=url,
            )
        if isinstance(last_error, UpstreamError) and last_error.status == 403:
            raise UpstreamError(f"HTTP 403 from {url}. {NETWORK_HINT}", status=403, url=url)
        if isinstance(last_error, UpstreamError) and last_error.status and last_error.status >= 500:
            raise UpstreamError(
                f"The exchange server answered HTTP {last_error.status} for {url} after {retries} tries. "
                "It is sometimes overloaded; try again in a few seconds.",
                status=last_error.status,
                url=url,
            )
        raise UpstreamError(
            f"Could not reach {url}: {last_error!s}. {NETWORK_HINT}",
            status=getattr(last_error, "status", None),
            url=url,
        )

    @staticmethod
    def _decode(response: httpx.Response, as_json: bool, url: str) -> Any:
        if not as_json:
            return response.text
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            snippet = response.text[:120].replace("\n", " ")
            raise UpstreamError(
                f"Expected JSON from {url} but got: {snippet!r}", status=200, url=url
            ) from exc

    async def get_json(self, url: str, *, ttl: float = 0.0, retries: int = 4) -> Any:
        return await self.get(url, ttl=ttl, retries=retries, as_json=True)

    async def get_text(self, url: str, *, ttl: float = 0.0, retries: int = 4) -> str:
        return await self.get(url, ttl=ttl, retries=retries, as_json=False)

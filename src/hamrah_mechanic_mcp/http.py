"""Shared async HTTP client for the public API and Next.js data behind hamrah-mechanic.com.

Every tool goes through `fetch` (JSON API) or `next_data` (the site's page data), which cap concurrency, cache
answers briefly and turn HTTP failures into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import copy
import json as json_lib
import os
import random
import re
import time
from typing import Any

import httpx
from curl_cffi.const import CurlOpt
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

SITE = "https://www.hamrah-mechanic.com"
API = f"{SITE}/api/v1"

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

MAX_CONCURRENCY = 3
JITTER = (0.1, 0.4)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
CACHE_TTL = 120  # seconds; prices change at most daily, listings by the minute
CACHE_MAX = 128
RETRY_DELAY = 0.5  # seconds, doubled per retry
MAX_BODY = 5_000_000  # bytes; the all-brands price list is ~700 KB
# As the site's own scripts send them (checked in Chrome 2026-11-01): the app's /api/v1 calls ask for plain JSON,
# Next.js data fetches send */*, and a page load is a navigation (no Referer when typed in).
JSON = "application/json"
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "priority": "u=0, i",
}
HOSTS = {"www.hamrah-mechanic.com"}  # host allowlist

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_cache: dict[tuple, tuple[float, Any]] = {}
_build: tuple[float, str] | None = None  # Next.js buildId and when it was read


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them on XHR calls."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        # The parent drops "accept: */*" as an httpx default; curl would then send Chrome's page Accept instead.
        accept = req.headers.get("accept")
        p = super()._create_request_params(req)
        extra = [(b"cache-control", None)]  # Chrome sends max-age=0 only on a reload
        if req.headers.get("sec-fetch-mode") != "navigate":
            extra += [(b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        p["headers"] = [*p["headers"], *extra, *([(b"accept", b"*/*")] if accept == "*/*" else [])]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index, _build
    _transport, _client, _limit, _proxy_index, _build = transport, None, None, 0, None
    _cache.clear()


def _proxies() -> list[str]:
    """HAMRAH_MECHANIC_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("HAMRAH_MECHANIC_MCP_PROXY", "").split(",") if p.strip()]


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate. The old client is closed late because other requests may still use it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the 20 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # System proxy settings are ignored; the proxy only comes from HAMRAH_MECHANIC_MCP_PROXY. curl_cffi
        # presents Chrome's TLS/HTTP2 fingerprint and default headers. The proxy goes to the transport.
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                curl_options={
                    CurlOpt.NOPROXY: "*"
                },  # httpx-curl-cffi drops its own NOPROXY unless this dict is non-empty
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=httpx.Timeout(20, connect=5),
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=False,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def _get(url: str, query: dict[str, Any], headers: dict[str, str]) -> tuple[httpx.Response, bytes]:
    """GET with retries on timeout, network error, 5xx and 429; 403 is never retried."""
    host = httpx.URL(url).host
    if host not in HOSTS:
        raise ApiError(f"Refusing to call unexpected host {host}.")
    for attempt in range(MAX_RETRIES + 1):
        last = attempt == MAX_RETRIES
        wait = RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
        try:
            r, content = await _request(url, query, headers, host)
        except ApiError as e:
            if last or e.status is not None:
                raise
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
            continue
        if (r.status_code == 429 or r.status_code >= 500) and not last:
            await asyncio.sleep(min(_retry_after(r) or wait, MAX_RETRY_WAIT))
            continue
        return r, content
    raise AssertionError("unreachable")


def _json(r: httpx.Response, content: bytes) -> Any:
    if r.status_code >= 400:
        raise ApiError(_status_message(r), r.status_code)
    try:
        return json_lib.loads(content)
    except ValueError as e:
        raise ApiError(
            f"hamrah-mechanic.com returned a non-JSON response (HTTP {r.status_code}).", r.status_code
        ) from e


async def fetch(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET `/api/v1<path>` the way the site's own scripts do and return the parsed JSON body."""
    query = dict(params or {})
    key = (path, tuple(sorted(query.items())))
    if (hit := _cache.get(key)) and time.monotonic() - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1])
    r, content = await _get(API + path, query, {"Accept": JSON, "Referer": f"{SITE}/"})
    body = _json(r, content)
    _store(key, body)
    return body


async def wp(path: str, params: dict[str, Any] | None = None) -> tuple[Any, int]:
    """GET the magazine's WordPress REST API (`/mag/wp-json/wp/v2<path>`); returns the JSON and X-WP-Total."""
    query = dict(params or {})
    key = ("wp", path, tuple(sorted(query.items())))
    if (hit := _cache.get(key)) and time.monotonic() - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1])
    r, content = await _get(f"{SITE}/mag/wp-json/wp/v2{path}", query, {"Accept": "*/*", "Referer": f"{SITE}/mag/"})
    if r.status_code == 400:  # WordPress answers 400 for a page past the last one
        return [], 0
    out = (_json(r, content), int(r.headers.get("x-wp-total", 0)))
    _store(key, out)
    return out


async def _build_id() -> str:
    """The Next.js buildId, read from the home page's __NEXT_DATA__ and kept for an hour."""
    global _build
    if _build and time.monotonic() - _build[0] < 3600:
        return _build[1]
    r, content = await _get(SITE + "/", {}, PAGE_HEADERS)
    if r.status_code >= 400:
        raise ApiError(_status_message(r), r.status_code)
    m = re.search(rb'"buildId":"([^"]+)"', content)
    if not m:
        raise ApiError("Could not read the site's page-data version (home page changed).")
    _build = (time.monotonic(), m.group(1).decode())
    return _build[1]


async def next_data(page: str) -> dict[str, Any]:
    """The `pageProps` the site renders a page from, e.g. page "carprice/kia" (no leading or trailing slash)."""
    key = ("next", page)
    if (hit := _cache.get(key)) and time.monotonic() - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1])
    for attempt in (0, 1):
        url = f"{SITE}/_next/data/{await _build_id()}/{page}.json"
        r, content = await _get(url, {}, {"Accept": "*/*", "Referer": f"{SITE}/", "x-nextjs-data": "1"})
        if r.status_code == 404 and attempt == 0:  # a new deploy changed the buildId
            global _build
            _build = None
            continue
        break
    if r.status_code == 404:
        raise ApiError("hamrah-mechanic.com has no such page. Check the brand, model and year spelling.", 404)
    body = _json(r, content).get("pageProps", {})
    _store(key, body)
    return body


def _store(key: tuple, body: Any) -> None:
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic(), copy.deepcopy(body))


async def _send(client, limit, url, query, headers, host) -> tuple[httpx.Response, bytes]:
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            async with client.stream("GET", url, params=query, headers=headers) as r:
                return r, await _read_capped(r, host)
    except httpx.TimeoutException as e:
        raise ApiError(f"{host} did not answer in time. Try again in a moment.") from e
    except httpx.RequestError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach {host} ({type(e).__name__}). Check the internet connection "
            "(or the HAMRAH_MECHANIC_MCP_PROXY setting if you use one)."
        ) from e


async def _request(url, query, headers, host) -> tuple[httpx.Response, bytes]:
    client, limit = _get_client()
    r, content = await _send(client, limit, url, query, headers, host)
    if r.status_code in (403, 429):
        _next_proxy(client)  # blocked: try the next proxy on the following call
    return r, content


async def _read_capped(r: httpx.Response, host: str) -> bytes:
    """Read the body, refusing anything over MAX_BODY so one huge answer cannot flood memory or context."""
    buf = bytearray()
    async for chunk in r.aiter_bytes():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise ApiError(f"{host} sent a response over {MAX_BODY // 1_000_000} MB; refused.", r.status_code)
    return bytes(buf)


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


def _status_message(r: httpx.Response) -> str:
    code = r.status_code
    if code == 403:
        return (
            "hamrah-mechanic.com blocked the request (HTTP 403). Try another network or set HAMRAH_MECHANIC_MCP_PROXY."
        )
    if code == 404:
        return "hamrah-mechanic.com found nothing at that address (HTTP 404). Check the id."
    if code == 429:
        return "hamrah-mechanic.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"hamrah-mechanic.com had a server error (HTTP {code}). The id or year may not exist; try again later."
    return f"hamrah-mechanic.com rejected the request (HTTP {code})."

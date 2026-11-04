"""Replay engine of the contract tests: recorded upstream responses served through respx.

A *scenario* calls one MCP tool the way a client would. Its *recordings* are the real upstream
responses the tool needed, stored once per request under ``tests/fixtures/recorded``:

    requests/<id>.json    one upstream request and its (possibly trimmed) response
    scenarios/<id>.json   which requests a scenario needs, and the Tehran time it was recorded at

``scripts/record_contract.py`` writes these files from the live servers; the tests only read them.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib
import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote

import httpx
import respx

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
REQUESTS = RECORDED / "requests"
MANIFESTS = RECORDED / "scenarios"
SCENARIO_MODULES = (
    "contract_scenarios_market",
    "contract_scenarios_symbol",
    "contract_scenarios_other",
)
HOSTS = {"cdn.tsetmc.com": "cdn", "webgw.tse.ir": "webgw", "search.codal.ir": "codal"}
RESPONSE_KEYS = {
    "status",
    "content_type",
    "json",
    "text",
}  # nothing else is stored: no headers or cookies


# ------------------------------------------------------------------------------ request identity
def request_key(method: str, url: str) -> str:
    """Method + host + path + query, ignoring query order: the identity under which a response is recorded."""
    parsed = httpx.URL(url)
    query = "&".join(
        f"{k}={v}" for k, v in sorted(parse_qsl(parsed.query.decode(), keep_blank_values=True))
    )
    return f"{method.upper()} {parsed.scheme}://{parsed.host}{parsed.path}" + (
        f"?{query}" if query else ""
    )


def request_id(method: str, url: str) -> str:
    """File name stem of a recording: readable prefix plus a hash that tells apart queries and Persian path parts."""
    parsed = httpx.URL(url)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", unquote(parsed.path)).strip("_")[:56]
    digest = hashlib.sha1(request_key(method, url).encode("utf-8")).hexdigest()[:8]
    return f"{HOSTS.get(parsed.host, parsed.host)}__{slug}-{digest}"


# ------------------------------------------------------------------------------ recordings
@dataclass
class Recorded:
    """One upstream exchange. ``json`` is the parsed body (``text`` for non-JSON bodies); ``trimmed`` says what was cut."""

    method: str
    url: str
    status: int
    content_type: str | None
    json: Any = None
    text: str | None = None
    trimmed: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return request_id(self.method, self.url)

    @property
    def body(self) -> Any:
        return self.text if self.text is not None else self.json

    def content(self) -> bytes:
        return (
            self.text if self.text is not None else json.dumps(self.json, ensure_ascii=False)
        ).encode("utf-8")

    def to_response(self, request: httpx.Request) -> httpx.Response:
        headers = {"content-type": self.content_type} if self.content_type else {}
        return httpx.Response(self.status, headers=headers, content=self.content(), request=request)

    def to_file(self) -> str:
        response: dict[str, Any] = {"status": self.status, "content_type": self.content_type}
        response.update({"text": self.text} if self.text is not None else {"json": self.json})
        doc = {
            "request": {"method": self.method, "url": self.url},
            "response": response,
            "trimmed": self.trimmed,
        }
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"

    @classmethod
    def from_file(cls, text: str) -> Recorded:
        doc = json.loads(text)
        response = doc["response"]
        return cls(
            doc["request"]["method"],
            doc["request"]["url"],
            response["status"],
            response.get("content_type"),
            response.get("json"),
            response.get("text"),
            doc.get("trimmed", []),
        )


def save_recorded(rec: Recorded, directory: Path = REQUESTS) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec.id}.json").write_bytes(rec.to_file().encode("utf-8"))


def load_recorded(rec_id: str, directory: Path = REQUESTS) -> Recorded:
    return Recorded.from_file((directory / f"{rec_id}.json").read_text(encoding="utf-8"))


def save_manifest(
    scenario_id: str,
    tool: str,
    recorded_at: dt.datetime,
    request_ids: list[str],
    directory: Path = MANIFESTS,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    doc = {
        "scenario": scenario_id,
        "tool": tool,
        "recorded_at": recorded_at.isoformat(timespec="seconds"),
        "requests": sorted(set(request_ids)),
    }
    (directory / f"{scenario_id}.json").write_bytes(
        (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    )


def load_manifest(scenario_id: str, directory: Path = MANIFESTS) -> dict | None:
    path = directory / f"{scenario_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Recordings:
    """Read access to the raw recorded payloads of a scenario, for assertions that compare output with input."""

    def __init__(self, items: list[Recorded]) -> None:
        self.items = items

    def find(self, fragment: str) -> list[Recorded]:
        return [r for r in self.items if fragment in r.url]

    def get(self, fragment: str) -> Recorded:
        found = self.find(fragment)
        if len(found) != 1:
            raise AssertionError(
                f"expected one recording with {fragment!r} in its URL, found {len(found)}: {[r.url for r in found]}"
            )
        return found[0]

    def body(self, fragment: str) -> Any:
        return self.get(fragment).body


# ------------------------------------------------------------------------------ serving through respx
class UnmatchedRequest(AssertionError):
    """The code under test made a request that has no recording."""


class Replay:
    """Serves a scenario's recordings through a respx router. A request without a recording raises, naming its URL."""

    def __init__(self, recordings: list[Recorded]) -> None:
        self.recordings = recordings
        self.unmatched: list[str] = []
        self.router = respx.Router(assert_all_called=False, assert_all_mocked=False)
        self._routes = []
        for rec in recordings:
            # respx matches a URL's query exactly; a URL without one must not match the same path with a query
            lookups = {} if httpx.URL(rec.url).query else {"params__eq": ""}
            route = self.router.route(method=rec.method, url=rec.url, **lookups)
            route.mock(side_effect=lambda request, rec=rec: rec.to_response(request))
            self._routes.append(route)
        self.router.route().mock(side_effect=self._missing)  # last: everything not recorded
        self.transport = httpx.MockTransport(self.router.async_handler)

    def _missing(self, request: httpx.Request) -> httpx.Response:
        line = f"{request.method} {request.url}"
        self.unmatched.append(line)
        raise UnmatchedRequest(
            f"no recording for {line} (re-record with scripts/record_contract.py --record --only <scenario>)"
        )

    def unused(self) -> list[str]:
        """URLs of recordings the scenario never requested: the code stopped asking for them, so they are stale."""
        return [
            rec.url
            for rec, route in zip(self.recordings, self._routes, strict=True)
            if not route.called
        ]


# ------------------------------------------------------------------------------ the clock
@contextlib.contextmanager
def frozen_clock(now: dt.datetime) -> Iterator[None]:
    """Pin ``tehran_now()`` (naive Tehran time) in every package module that imported it by name."""
    from iran_bourse_mcp import dates

    original = dates.tehran_now

    def pinned(now_utc: dt.datetime | None = None) -> dt.datetime:
        return original(now_utc) if now_utc is not None else now

    patched = [
        module
        for name, module in list(sys.modules.items())
        if name.split(".")[0] == "iran_bourse_mcp"
        and getattr(module, "tehran_now", None) is original
    ]
    for module in patched:
        module.tehran_now = pinned
    try:
        yield
    finally:
        for module in patched:
            module.tehran_now = original


# ------------------------------------------------------------------------------ calling a tool like a client
def unwrap(result: Any) -> dict:
    """The tool's JSON object from ``mcp.call_tool``: SDK 1.x returns content blocks (or a tuple or dict), 2.x a CallToolResult."""
    if isinstance(result, tuple) and len(result) == 2:
        result = result[0]
    if isinstance(result, dict):
        return result
    for block in getattr(result, "content", result):
        text = getattr(block, "text", None)
        if text is not None:
            return json.loads(text)
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict):
        return structured
    raise AssertionError(f"tool result has no JSON text content: {result!r}")


async def call_tool(
    tool: str, args: dict, transport: httpx.AsyncBaseTransport, now: dt.datetime
) -> dict:
    """Run ``tool`` through the MCP server object (argument validation, error mapping) on top of the real service stack."""
    from iran_bourse_mcp import server
    from iran_bourse_mcp.client import Http
    from iran_bourse_mcp.service import Bourse

    bourse = Bourse(Http(transport=transport))
    previous, server._service = server._service, bourse
    try:
        with frozen_clock(now):
            return unwrap(await server.mcp.call_tool(tool, args))
    finally:
        server._service = previous
        await bourse.aclose()


# ------------------------------------------------------------------------------ scenarios
@dataclass
class Run:
    """What a scenario's check sees: the tool output, the recordings it was computed from, the pinned clock."""

    scenario: Scenario
    out: dict
    rec: Recordings
    now: dt.datetime
    replay: Replay


@dataclass(frozen=True)
class Scenario:
    id: str
    tool: str
    args: dict
    check: Callable[[Run], None]
    codal: bool = False  # hits search.codal.ir, which rate-limits: recorded last and slowly


SCENARIOS: dict[str, Scenario] = {}


def scenario(id: str, tool: str, *, codal: bool = False, **args: Any):
    """Register a scenario: ``@scenario("quote", "quote", symbol="فولاد")`` on the function that checks the output."""

    def register(check: Callable[[Run], None]) -> Callable[[Run], None]:
        if id in SCENARIOS:
            raise ValueError(f"duplicate scenario id {id!r}")
        SCENARIOS[id] = Scenario(id, tool, args, check, codal=codal)
        return check

    return register


def load_scenarios() -> dict[str, Scenario]:
    for name in SCENARIO_MODULES:
        importlib.import_module(name)
    return SCENARIOS


async def replay_scenario(sc: Scenario, directory: Path = RECORDED) -> Run:
    """Run a scenario against its stored recordings (no network)."""
    manifest = load_manifest(sc.id, directory / "scenarios")
    if manifest is None:
        raise FileNotFoundError(
            f"scenario {sc.id!r} has no recording: run scripts/record_contract.py --record --only {sc.id}"
        )
    items = [load_recorded(rec_id, directory / "requests") for rec_id in manifest["requests"]]
    replay = Replay(items)
    now = dt.datetime.fromisoformat(manifest["recorded_at"])
    try:
        out = await call_tool(sc.tool, sc.args, replay.transport, now)
    except Exception as exc:
        if replay.unmatched:  # the SDK words an exception from a tool in its own way: name the URLs
            lines = "\n  ".join(replay.unmatched)
            raise UnmatchedRequest(
                f"scenario {sc.id!r} requested URLs that have no recording:\n  {lines}"
            ) from exc
        raise
    return Run(sc, out, Recordings(items), now, replay)

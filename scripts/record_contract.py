"""Record the contract-test fixtures (tests/fixtures/recorded) from the live TSETMC and Codal servers.

    uv run python scripts/record_contract.py                       # list scenarios and their recordings (offline)
    uv run python scripts/record_contract.py --record              # record every scenario, then verify it by replay
    uv run python scripts/record_contract.py --record --only quote,top_movers_real_inflow
    uv run python scripts/record_contract.py --show quote          # replay a recorded scenario, print the output (offline)

Every scenario (tests/contract/contract_scenarios_*.py) calls one MCP tool through the real server stack on top of a
*recording transport*. The transport is gentle on the exchange: one request at a time, a pause between requests (longer
for Codal, which answers HTTP 429 to a shared IP quickly), a long wait before retrying a 429, and scenarios that failed are
retried in later rounds. Responses are trimmed to a bounded size (whole-market feeds to one fixed set of about 150
instruments, long histories to their newest rows; every field of every kept row is kept and what was cut is written into
the file), and only the status, the content type and the body are stored: no request headers, cookies or tokens.

Re-record everything (no --only) when you want a consistent snapshot: scenarios share their requests, so recording one
scenario alone refreshes the requests it uses for the others too.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "contract"))

import contract_replay as cr  # noqa: E402

from iran_bourse_mcp import market, service  # noqa: E402
from iran_bourse_mcp.dates import from_date, tehran_now  # noqa: E402
from iran_bourse_mcp.text import clean  # noqa: E402

MARKET_WATCH = "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0&industrialGroup=&showTraded=false&withBestLimits=true&hEven=0&RefID=0"
DELAYS = {"default": 0.5, "search.codal.ir": 6.0}  # seconds between two requests to a host
RETRY_STATUS = {403, 408, 425, 429, 502, 503, 504}
WAIT_429 = (30, 60, 120, 180, 240)  # seconds before each retry of a rate-limited request
WAIT_OTHER = (3, 10, 30, 60)
MAX_BODY_BYTES = 700_000  # one recording; the pre-commit hook rejects files over 900 KB
BUDGET_BYTES = 6 * 1024 * 1024  # all recordings together

# Instruments the scenarios name, kept in the whole-market feeds besides the busiest ones.
PINNED = ("فولاد", "اهرم", "حتاید")
QUOTA = {  # how many of the busiest instruments of each type the whole-market feeds keep
    "سهام": 90,
    "بازار پایه فرابورس": 10,
    "صندوق سرمایه گذاری": 12,
    "اوراق بدهی": 6,
    "اختیار معامله": 4,
    "آتی": 3,
    "حق تقدم": 4,
    "بورس کالا": 3,
    market.TYPE_TAL: 4,
    market.TYPE_HOUSING: 3,
    market.TYPE_ENERGY: 3,
    market.TYPE_OTHER: 3,
}


class RecordingError(RuntimeError):
    """The upstream server would not give a usable answer (not an httpx error, so the client does not retry it)."""


# ------------------------------------------------------------------------------ the instruments the whole-market feeds keep
@dataclass
class Universe:
    ins_codes: set[str] = field(default_factory=set)
    ins_ids: set[str] = field(default_factory=set)


def build_universe(rows: list[dict]) -> Universe:
    """The busiest instruments of every type, the limit-locked ones (so queues exist), the pinned symbols and a few idle shares."""
    shaped = [(raw, market.shape_market_row(raw)) for raw in rows]
    traded = sorted(
        (p for p in shaped if p[1]["trades"] > 0), key=lambda p: p[1]["value"] or 0, reverse=True
    )
    picked: list[dict] = []
    taken: dict[str, int] = {}
    for raw, row in traded:
        kind = row["security_type"]
        if taken.get(kind, 0) < QUOTA.get(kind, 3):
            taken[kind] = taken.get(kind, 0) + 1
            picked.append(raw)
    picked += [raw for raw, row in traded if row["buy_queue_probable"]][:12]
    picked += [raw for raw, row in traded if row["sell_queue_probable"]][:6]
    pinned = {clean(name) for name in PINNED}
    picked += [raw for raw, row in shaped if row["symbol"] in pinned]
    picked += [raw for raw, row in shaped if row["trades"] == 0 and row["security_type"] == "سهام"][
        :8
    ]
    return Universe(
        {str(raw["insCode"]) for raw in picked},
        {raw["insID"] for raw in picked if raw.get("insID")},
    )


# ------------------------------------------------------------------------------ trimming
@dataclass
class TrimContext:
    universe: Universe | None
    now: Any


def _list(body: Any, key: str) -> list:
    rows = body.get(key) if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise RecordingError(f"expected a list under {key!r} to trim, got {type(rows).__name__}")
    return rows


def keep_newest(body: Any, key: str, n: int, *fields: str) -> list[dict]:
    """Keep the ``n`` rows with the largest ``fields`` (upstream order is preserved)."""
    rows = _list(body, key)
    if len(rows) <= n:
        return []
    best = sorted(
        range(len(rows)), key=lambda i: tuple(rows[i].get(f) or 0 for f in fields), reverse=True
    )[:n]
    body[key] = [rows[i] for i in sorted(best)]
    return [
        {"path": key, "kept": n, "of": len(rows), "rule": f"newest {n} rows by {'/'.join(fields)}"}
    ]


def keep_first(body: Any, key: str, n: int) -> list[dict]:
    rows = _list(body, key)
    if len(rows) <= n:
        return []
    body[key] = rows[:n]
    return [{"path": key, "kept": n, "of": len(rows), "rule": f"first {n} rows"}]


def keep_where(body: Any, key: str, test: Callable[[dict], bool], rule: str) -> list[dict]:
    rows = _list(body, key)
    kept = [row for row in rows if test(row)]
    body[key] = kept
    return (
        [{"path": key, "kept": len(kept), "of": len(rows), "rule": rule}]
        if len(kept) != len(rows)
        else []
    )


def _in_universe(codes: set[str], field_name: str) -> Callable[[dict], bool]:
    return lambda row: str(row.get(field_name)) in codes


def trim_market_watch(body: Any, ctx: TrimContext) -> list[dict]:
    return keep_where(
        body, "marketwatch", _in_universe(ctx.universe.ins_codes, "insCode"), "fixed instrument set"
    )


def trim_gateway(body: Any, ctx: TrimContext) -> list[dict]:
    return keep_where(
        body, "Items", _in_universe(ctx.universe.ins_ids, "instrumentId"), "fixed instrument set"
    )


def trim_client_all(body: Any, ctx: TrimContext) -> list[dict]:
    return keep_where(
        body,
        "clientTypeAllDto",
        _in_universe(ctx.universe.ins_codes, "insCode"),
        "fixed instrument set",
    )


def trim_day_table(body: Any, ctx: TrimContext) -> list[dict]:
    return keep_where(
        body,
        "closingPriceDailyHistoryWithInstDetails",
        _in_universe(ctx.universe.ins_codes, "insCode"),
        "fixed instrument set",
    )


def trim_static_data(body: Any, ctx: TrimContext) -> list[dict]:
    return keep_where(
        body,
        "staticData",
        lambda row: row.get("type") == "IndustrialGroup",
        "IndustrialGroup rows (the only type the server reads)",
    )


def trim_share_changes(body: Any, ctx: TrimContext) -> list[dict]:
    """Share-count changes within 100 days of the recording day (the feed lists years, and ignores its `top` argument)."""
    today = ctx.now.date()
    low, high = from_date(today - dt.timedelta(days=100)), from_date(today + dt.timedelta(days=100))
    return keep_where(
        body,
        "instrumentShareChange",
        lambda row: low <= int(row.get("dEven") or 0) <= high,
        "dEven within 100 days of the recording day",
    )


def trim_options(body: Any, ctx: TrimContext) -> list[dict]:
    """Keep every contract of the three underlyings with the most open interest and of the pinned fund."""
    rows = _list(body, "instrumentOptMarketWatch")
    interest: dict[str, float] = {}
    for row in rows:
        interest[str(row.get("uaInsCode"))] = (
            interest.get(str(row.get("uaInsCode")), 0)
            + (row.get("oP_C") or 0)
            + (row.get("oP_P") or 0)
        )
    wanted = set(sorted(interest, key=interest.get, reverse=True)[:3])
    wanted |= {
        str(row.get("uaInsCode")) for row in rows if clean(row.get("lval30_UA")) == clean(PINNED[1])
    }
    return keep_where(
        body,
        "instrumentOptMarketWatch",
        lambda row: str(row.get("uaInsCode")) in wanted,
        "contracts of the 3 busiest underlyings and the pinned fund",
    )


def cap_rows(key: str, n: int) -> Callable[[Any, TrimContext], list[dict]]:
    return lambda body, ctx: keep_first(body, key, n)


@dataclass(frozen=True)
class Rule:
    pattern: str  # matched against host + path
    trim: Callable[[Any, TrimContext], list[dict]]
    universe: bool = False  # needs the instrument set (fetches the full market feed first)

    def matches(self, url: httpx.URL) -> bool:
        return re.search(self.pattern, f"{url.host}{url.path}") is not None


RULES = (
    Rule(r"/ClosingPrice/GetMarketWatch$", trim_market_watch, universe=True),
    Rule(r"MarketWatch/MarketWatchCash/", trim_gateway, universe=True),
    Rule(r"/ClientType/GetClientTypeAll$", trim_client_all, universe=True),
    Rule(r"/ClosingPrice/GetInstrmentsHistoryInDay/", trim_day_table, universe=True),
    Rule(r"/StaticData/GetStaticData$", trim_static_data),
    Rule(
        r"/ClosingPrice/GetClosingPriceDailyList/",
        lambda body, ctx: keep_newest(body, "closingPriceDaily", 300, "dEven"),
    ),
    Rule(
        r"/ClientType/GetClientTypeHistory/\d+$",
        lambda body, ctx: keep_newest(body, "clientType", 120, "recDate"),
    ),
    Rule(
        r"/Msg/GetMsgByInsCode/", lambda body, ctx: keep_newest(body, "msg", 25, "dEven", "hEven")
    ),
    Rule(
        r"/Index/GetIndexB2History/", lambda body, ctx: keep_newest(body, "indexB2", 600, "dEven")
    ),
    Rule(r"/ClosingPrice/GetIndexCompany/", cap_rows("relatedCompanyThirtyDayHistory", 60)),
    Rule(r"/Instrument/GetInstrumentShareChangeByFlow/", trim_share_changes),
    Rule(r"/Instrument/GetInstrumentOptionMarketWatch/", trim_options),
    Rule(r"/Shareholder/GetShareHolderChanges/", cap_rows("shareHoldersChanges", 40)),
    Rule(
        r"/MarketData/GetInstrumentStateAll/",
        lambda body, ctx: keep_newest(body, "instrumentState", 150, "dEven", "hEven"),
    ),
    Rule(r"/Trade/GetTrade/\d+$", cap_rows("trade", 3000)),
    Rule(r"/Trade/GetTradeHistory/", cap_rows("tradeHistory", 3000)),
    Rule(r"/BestLimits/\d+/\d+$", cap_rows("bestLimitsHistory", 4000)),
)


def trim(url: httpx.URL, body: Any, ctx: TrimContext) -> list[dict]:
    rule = next((r for r in RULES if r.matches(url)), None)
    return rule.trim(body, ctx) if rule and isinstance(body, (dict, list)) else []


# ------------------------------------------------------------------------------ the recording transport
class RecordingTransport(httpx.AsyncBaseTransport):
    """Forwards requests to the real servers one at a time, politely, and keeps trimmed copies of the answers.

    The scenario under test is served the *trimmed* answer, so it makes the same follow-up requests as the replay will.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        now: Any,
        delays: dict[str, float] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda line: None,
    ) -> None:
        self.inner, self.now, self.delays = inner, now, delays or DELAYS
        self.sleep, self.clock, self.log = sleep, clock, log
        self.cache: dict[str, cr.Recorded] = {}
        self.used: dict[str, cr.Recorded] = {}
        self.errors: list[str] = []
        self.upstream_requests = 0
        self._universe: Universe | None = None
        self._raw: dict[
            str, tuple[int, str | None, bytes]
        ] = {}  # untrimmed answers, by request key
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._universe_lock = asyncio.Lock()

    def begin(self) -> None:
        self.used, self.errors = {}, []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = cr.request_key(request.method, str(request.url))
        rec = self.cache.get(key)
        if rec is None:
            try:
                rec = await self._record(request)
            except Exception as exc:
                # kept for the scenario too: the service swallows the errors of its optional sections
                self.errors.append(f"{request.method} {request.url}: {exc}")
                raise
            self.cache[key] = rec
        self.used[key] = rec
        return rec.to_response(request)

    async def _record(self, request: httpx.Request) -> cr.Recorded:
        status, content_type, content = await self._fetch(request)
        text = content.decode("utf-8", errors="replace")
        rec = cr.Recorded(request.method, str(request.url), status, content_type)
        is_json = False
        if text.lstrip()[:1] in ("{", "["):
            try:
                rec.json, is_json = json.loads(text), True
            except ValueError:
                pass
        if not is_json:
            rec.text = text
        elif status == 200:
            rule = next((r for r in RULES if r.matches(request.url)), None)
            if rule and rule.universe:
                await self._ensure_universe()
            rec.trimmed = trim(request.url, rec.json, TrimContext(self._universe, self.now))
        size = len(rec.to_file().encode("utf-8"))
        if size > MAX_BODY_BYTES:
            raise RecordingError(
                f"{request.url} is {size:,} bytes after trimming (limit {MAX_BODY_BYTES:,}): add a rule to RULES in scripts/record_contract.py"
            )
        return rec

    async def _ensure_universe(self) -> None:
        async with self._universe_lock:
            if self._universe is None:
                status, _, content = await self._fetch(httpx.Request("GET", MARKET_WATCH))
                if status != 200:
                    raise RecordingError(
                        f"the market-watch feed answered HTTP {status}: cannot choose the instrument set"
                    )
                self._universe = build_universe(json.loads(content)["marketwatch"])
                self.log(
                    f"  instrument set for the whole-market feeds: {len(self._universe.ins_codes)} instruments"
                )

    async def _fetch(self, request: httpx.Request) -> tuple[int, str | None, bytes]:
        """The upstream answer, untrimmed. Each request goes out once: the market feed is needed twice (instrument set, scenario)."""
        url = str(request.url)
        key = cr.request_key(request.method, url)
        if key in self._raw:
            return self._raw[key]
        host = request.url.host
        async with self._lock:
            if key in self._raw:  # another task asked for the same thing while this one waited
                return self._raw[key]
            for attempt in range(len(WAIT_429) + 1):
                gap = self.delays.get(host, self.delays["default"]) - (
                    self.clock() - self._last.get(host, float("-inf"))
                )
                if gap > 0:
                    await self.sleep(gap)
                self.upstream_requests += 1
                response = await self.inner.handle_async_request(request)
                content = await response.aread()
                await response.aclose()
                self._last[host] = self.clock()
                status = response.status_code
                self.log(f"  {request.method} {url[:150]} -> {status} ({len(content):,} bytes)")
                if status not in RETRY_STATUS:
                    break
                waits = WAIT_429 if status == 429 else WAIT_OTHER
                if attempt >= len(waits):
                    raise RecordingError(
                        f"HTTP {status} from {url} after {attempt + 1} tries: rate-limited or down, record again later"
                    )
                self.log(f"  HTTP {status}: waiting {waits[attempt]} s before asking again")
                await self.sleep(waits[attempt])
            self._raw[key] = (status, response.headers.get("content-type"), content)
            return self._raw[key]


# ------------------------------------------------------------------------------ recording scenarios
def _proxy(explicit: str | None) -> str | None:
    return (
        explicit
        or os.environ.get("IRAN_BOURSE_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or None
    )


def _selected(only: str | None) -> list[cr.Scenario]:
    scenarios = list(cr.load_scenarios().values())
    if only:
        wanted = {name.strip() for name in only.split(",") if name.strip()}
        chosen = [s for s in scenarios if s.id in wanted or s.tool in wanted]
        unknown = wanted - {s.id for s in chosen} - {s.tool for s in chosen}
        if unknown:
            raise SystemExit(f"unknown scenario or tool: {', '.join(sorted(unknown))}")
        scenarios = chosen
    return sorted(scenarios, key=lambda s: s.codal)  # Codal last: it answers HTTP 429 first


async def verify(sc: cr.Scenario) -> None:
    """Replay the freshly written files offline and run the scenario's assertions on them."""
    run = await cr.replay_scenario(sc)
    assert not run.replay.unmatched, f"requests without a recording: {run.replay.unmatched}"
    assert not run.replay.unused(), f"recordings never requested: {run.replay.unused()}"
    sc.check(run)


async def record_one(sc: cr.Scenario, transport: RecordingTransport, now: Any) -> int:
    transport.begin()
    await cr.call_tool(sc.tool, sc.args, transport, now)
    if transport.errors:
        raise RecordingError("; ".join(transport.errors[:3]))
    for rec in transport.used.values():
        cr.save_recorded(rec)
    cr.save_manifest(sc.id, sc.tool, now, [rec.id for rec in transport.used.values()])
    await verify(sc)
    return len(transport.used)


def prune() -> list[str]:
    """Delete request files that no scenario manifest refers to any more."""
    wanted = {
        rid
        for path in cr.MANIFESTS.glob("*.json")
        for rid in json.loads(path.read_text(encoding="utf-8"))["requests"]
    }
    gone = [path.stem for path in cr.REQUESTS.glob("*.json") if path.stem not in wanted]
    for stem in gone:
        (cr.REQUESTS / f"{stem}.json").unlink()
    return gone


def disk_bytes() -> int:
    return sum(path.stat().st_size for path in cr.RECORDED.rglob("*.json"))


async def record(scenarios: list[cr.Scenario], args: argparse.Namespace) -> int:
    now = tehran_now().replace(microsecond=0)
    print(
        f"recording {len(scenarios)} scenarios at {now.isoformat()} Tehran time, one request at a time"
    )
    service.SECTION_TIMEOUT = 600.0  # a throttled recording is slow: let optional sections finish instead of reporting them missing
    delays = {**DELAYS, "default": args.delay, "search.codal.ir": args.codal_delay}
    async with httpx.AsyncHTTPTransport(proxy=_proxy(args.proxy)) as inner:
        transport = RecordingTransport(
            inner, now=now, delays=delays, log=print if args.verbose else (lambda line: None)
        )
        pending, failed = scenarios, {}
        for round_no in range(1, args.rounds + 1):
            failed = {}
            for sc in pending:
                started = time.monotonic()
                try:
                    count = await record_one(sc, transport, now)
                    print(
                        f"  ok      {sc.id:<32} {count:>3} requests  {time.monotonic() - started:5.1f}s"
                    )
                except Exception as exc:
                    root = exc
                    while (
                        root.__cause__ is not None
                    ):  # the SDK wraps what a tool raised: say the original
                        root = root.__cause__
                    failed[sc.id] = f"{type(root).__name__}: {str(root)[:400]}"
                    print(f"  FAILED  {sc.id:<32} {failed[sc.id]}")
            pending = [sc for sc in pending if sc.id in failed]
            if not pending:
                break
            if round_no < args.rounds:
                print(
                    f"{len(pending)} scenario(s) failed; waiting {args.pause:.0f} s before round {round_no + 1}"
                )
                await asyncio.sleep(args.pause)
    gone = prune()
    total = disk_bytes()
    print(
        f"\n{len(scenarios) - len(failed)}/{len(scenarios)} scenarios recorded, {transport.upstream_requests} upstream requests, "
        f"{len(list(cr.REQUESTS.glob('*.json')))} request files, {total / 1024 / 1024:.2f} MB on disk (budget {BUDGET_BYTES / 1024 / 1024:.0f} MB)"
    )
    if gone:
        print(f"pruned {len(gone)} request file(s) no scenario uses any more")
    for sc_id, why in failed.items():
        print(f"FAILED {sc_id}: {why}")
    if total > BUDGET_BYTES:
        print("over budget: tighten a rule in RULES")
        return 2
    return 1 if failed else 0


def list_scenarios(scenarios: list[cr.Scenario]) -> None:
    print(f"{'scenario':<34}{'tool':<22}{'recorded at':<21}{'requests':>8}")
    for sc in scenarios:
        manifest = cr.load_manifest(sc.id)
        print(
            f"{sc.id:<34}{sc.tool:<22}{(manifest or {}).get('recorded_at', '-'):<21}{len(manifest['requests']) if manifest else 0:>8}"
        )
    print(
        f"\n{len(scenarios)} scenarios, {disk_bytes() / 1024:.0f} KB recorded. Use --record to refresh them from the live servers."
    )


async def show(sc: cr.Scenario) -> None:
    run = await cr.replay_scenario(sc)
    print(json.dumps(run.out, ensure_ascii=False, indent=1))
    print(
        f"\n# recorded at {run.now.isoformat()}; unmatched {run.replay.unmatched}; unused {run.replay.unused()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--record", action="store_true", help="hit the live servers and rewrite the recordings"
    )
    parser.add_argument("--only", help="comma-separated scenario ids or tool names")
    parser.add_argument(
        "--show", metavar="ID", help="replay one recorded scenario offline and print its output"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAYS["default"],
        help="seconds between requests to the same host (default %(default)s)",
    )
    parser.add_argument(
        "--codal-delay",
        type=float,
        default=DELAYS["search.codal.ir"],
        help="seconds between Codal requests (default %(default)s)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="passes over scenarios that failed (default %(default)s)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=90.0,
        help="seconds to wait before another round (default %(default)s)",
    )
    parser.add_argument("--proxy", help="HTTP(S) proxy (default: IRAN_BOURSE_PROXY or HTTPS_PROXY)")
    parser.add_argument("--verbose", action="store_true", help="print every upstream request")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.show:
        scenarios = cr.load_scenarios()
        if args.show not in scenarios:
            raise SystemExit(f"unknown scenario {args.show!r}; known: {', '.join(scenarios)}")
        asyncio.run(show(scenarios[args.show]))
        return 0
    scenarios = _selected(args.only)
    if not args.record:
        list_scenarios(scenarios)
        return 0
    return asyncio.run(record(scenarios, args))


if __name__ == "__main__":
    sys.exit(main())

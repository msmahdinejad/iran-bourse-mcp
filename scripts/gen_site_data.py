"""Export everything the website / README graphics need into docs/data.js (and docs/data/*.json).

    uv run python scripts/gen_site_data.py

Live data (needs access to TSETMC) is captured as a labelled snapshot; tools and client install
snippets come straight from the code so the site can never drift from the package.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from tool_groups import FA, GROUPS

from iran_bourse_mcp import __version__, clients
from iran_bourse_mcp.server import mcp
from iran_bourse_mcp.service import Bourse

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def schema_of(tool) -> dict:
    return getattr(tool, "inputSchema", None) or tool.input_schema


async def tools_data() -> list[dict]:
    tools = {t.name: t for t in await mcp.list_tools()}
    out = []
    for group, names in GROUPS.items():
        for name in names:
            t = tools[name]
            schema = schema_of(t)
            out.append({
                "name": name,
                "group": group,
                "description": (t.description or "").strip(),
                "fa": FA[name],
                "params": [
                    {"name": k, "required": k in schema.get("required", []), "description": v.get("description", ""), "default": v.get("default")}
                    for k, v in schema.get("properties", {}).items()
                ],
            })
    return out


def clients_data() -> list[dict]:
    out = []
    for c in clients.all_clients():
        out.append({
            "id": c.id,
            "label": c.label,
            "group": c.group,
            "note": c.note,
            "docs": c.docs,
            "snippet": clients.snippet(c.id),
            "oneclick": {
                "cursor": clients.cursor_deeplink() if c.id == "cursor" else None,
                "vscode": clients.vscode_deeplink() if c.id == "vscode" else None,
                "goose": clients.goose_deeplink() if c.id == "goose" else None,
            },
            "auto": c.auto_install,
        })
    return out


async def snapshot() -> dict:
    b = Bourse()
    try:
        status = await b.market_status()
        overview = await b.market_overview("bourse")
        movers = await b.top_movers("value", limit=16)
        gainers = await b.top_movers("gainers", limit=5)
        queues = await b.top_movers("buy_queue", limit=5)
        inflow = await b.top_movers("real_inflow", limit=5)
        folad = await b.symbol_overview("فولاد")
        rows = (await b.price_history("فولاد", limit=3))["rows"]
        # during the session today's official totals are not published yet, so use the last completed day
        done_day = rows[-2]["date"] if overview["market_state"] == "باز" else rows[-1]["date"]
        summary = await b.trade_summary("فولاد", date=done_day)
        flow = await b.real_legal_flow("فولاد", 5)
        book_hist = await b.order_book_history("فولاد", date="2026-11-02", step_seconds=1800)
    finally:
        await b.aclose()
    return {
        "captured_at_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "tehran_time": status["tehran_time"],
        "market_state": overview["market_state"],
        "index": overview["index"],
        "trades_today": overview["trades"],
        "value_today": overview["value"],
        "tape": [
            {"symbol": r["symbol"], "last": r["last"], "pct": r["last_pct"]}
            for r in movers["rows"]
        ],
        "gainers": gainers["rows"],
        "buy_queues": queues["rows"],
        "real_inflow": inflow["rows"],
        "foolad": {
            "identity": folad["identity"],
            "quote": folad["quote"],
            "order_book": folad["order_book"],
            "real_legal": folad.get("real_legal"),
            "holders": folad.get("major_shareholders"),
            "filings": folad.get("recent_filings"),
            "trade_summary": {
                "summary": summary["summary"],
                "completeness": summary["completeness"],
                "pressure": summary["pressure_estimate"],
                "bars": summary["bars"],
                "biggest": summary["biggest_trades"][:3],
            },
            "flow": flow,
            "book_history": {k: book_hist.get(k) for k in ("date", "events_span", "queue_episodes", "samples")},
        },
    }


async def main() -> None:
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    import re
    import subprocess
    import sys

    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True).stdout
    match = re.search(r"(\d+) tests? collected", collected) or re.search(r"(\d+) tests?", collected)
    data = {
        "tests": int(match.group(1)) if match else None,
        "version": __version__,
        "tools": await tools_data(),
        "clients": clients_data(),
        "frameworks": clients.frameworks(),
        "snapshot": await snapshot(),
    }
    for name in ("data_plane", "agents"):
        path = ROOT / "benchmarks" / "results" / f"{name}.json"
        data[f"bench_{name}"] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    (DOCS / "data" / "site.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (DOCS / "data.js").write_text("window.SITE_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"wrote docs/data.js ({len(json.dumps(data)) // 1024} KB): {len(data['tools'])} tools, {len(data['clients'])} clients")


if __name__ == "__main__":
    asyncio.run(main())

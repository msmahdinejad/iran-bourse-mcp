"""Regenerate docs/SCREENER.md from the filter-language registry so the guide cannot drift from the code.

    uv run python scripts/gen_screener_doc.py
"""

from __future__ import annotations

from pathlib import Path

from iran_bourse_mcp import screener as S

INTRO = """\
# Stock screener

`screen_stocks` is the filter box of tsetmc.com, driven by an AI agent. You describe what you want in plain
language, the agent writes a short condition, and the server returns only the stocks that satisfy it right
now, in one call, with the evidence for each hit.

```text
You:    stocks whose volume today is over twice their 20-day average, that rose more than 1% yesterday,
        are positive today, and trade over 5 billion rial
Agent:  screen_stocks(filter="volume > 2 * avg(volume, 20) and close_pct[1] > 1 and close_pct > 0 and value > 5B")
```

The condition is parsed with Python's `ast` module, checked against a whitelist and compiled to closures. It is
never passed to `eval` or `exec`, cannot import anything, and is limited in size and depth.

## How it works

* **Universe:** every instrument of the exchange's market watch (about 580 ordinary shares on Bourse and Fara
  Bourse by default); narrow it with `market`, `security_type`, `industry`.
* **Today:** live values from the market watch, plus real/legal flow from the exchange's client-type table.
* **Past days:** up to 60 trading days read from the exchange's end-of-day tables (one request per day for the
  whole market, cached). Prices are adjusted for capital increases and dividends by default, so `close[5]` is
  comparable with `close`.
* **Evidence:** besides `symbol`, `last`, `close_pct`, `volume` and `value`, every result shows the fields the
  filter uses and its window terms (for example `avg(volume, 20)`), so a hit explains itself.
* **Missing data is unknown, not false:** a comparison against a missing value is unknown and never matches. A past
  day on which a symbol did not trade counts as zero volume; days before it was listed are unknown.
* **Time:** about 3 seconds the first time a history depth is needed, well under a second afterwards.

## Syntax

"""

TAIL = """
## Reading results

```json
{
  "filter": "(volume > 2 * avg(volume, 20) and close_pct[1] > 1 ...)",
  "as_of": {"date": "2026-11-04", "jdate": "1405/08/13", "session_open": false},
  "history": {"trading_days_loaded": 20, "from": "2026-10-07", "to": "2026-11-03", "adjusted_for_capital_changes": true},
  "matched": 28, "returned": 6,
  "rows": [{"symbol": "...", "yesterday_pct": 2.97, "today_pct": 2.85, "volume_x": 8.42}]
}
```

`matched` is the total number of hits, `returned` how many fit `limit`. While the session is open the response
says so: today's volume, value, trades and real/legal flow are partial then, so ratios against past averages
understate the final ones.

## Limits and honesty

* The expression language is this project's own. It borrows the idea and many field names from the filter box on
  tsetmc.com; filters are not copy-compatible in both directions.
* `buy_queue` / `sell_queue` are inferred from the live snapshot (price at the limit with nothing offered). Use
  `top_movers(kind='buy_queue')` for queue sizes confirmed against each symbol's order book.
* `real_*_value` fields are estimates (net real volume x volume-weighted price); the exchange publishes volumes
  and counts, not values, in its market-wide client-type table.
* History fields exist for prices, volume, value and trade count. P/E, EPS, order-book and flow fields describe
  today only.
* Not investment advice.
"""


def table(rows: list[tuple[str, ...]], header: tuple[str, ...]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return lines


def main() -> None:
    lines = [INTRO.rstrip(), ""]
    lines += [f"* {line}" for line in S.SYNTAX]
    lines += ["", "## Examples", ""]
    lines += table([(goal, f"`{expr}`") for goal, expr in S.EXAMPLES], ("Goal", "Filter"))
    lines += ["", "## Fields", "", "Fields marked **history** also work as `name[k]` and inside the window functions.", ""]
    rows = []
    for f in S.FIELDS:
        names = f"`{f.name}`" + "".join(f", `{a}`" for a in f.aliases)
        rows.append((names, f.label, f.unit, "yes" if f.history else "", f.doc.replace("|", "\\|")))
    lines += table(rows, ("Field (aliases)", "Persian label", "Unit", "History", "Meaning"))
    lines += ["", "## Functions", ""]
    lines += table([(f"`{sig}`", doc) for sig, doc in S.FUNCTION_DOCS.items()], ("Function", "Meaning"))
    lines += ["", f"Windows reach at most {S.MAX_LOOKBACK} trading days back; an expression may be {S.MAX_TEXT} characters long.", ""]
    lines += ["## Ready-made presets", "", "Use `screen_stocks(preset=\"volume_surge\")`, optionally with an extra `filter` that is ANDed.", ""]
    rows = [(f"`{p.name}`", p.title_fa, f"`{p.filter}`", f"`{p.sort}`" + ("" if p.descending else " (ascending)")) for p in S.PRESETS]
    lines += table(rows, ("Preset", "Persian", "Filter", "Sorted by"))
    lines += [TAIL.rstrip(), ""]
    out = Path(__file__).resolve().parent.parent / "docs" / "SCREENER.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

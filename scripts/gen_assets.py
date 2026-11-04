"""Generate the animated SVG artwork used by the README and the website.

    uv run python scripts/gen_assets.py     (after scripts/gen_site_data.py)

Everything is plain SVG (CSS + SMIL animation, no scripts) so GitHub renders it inside <img>.
Every animated element is fully visible in its default state, so viewers without animation
support still see the finished picture.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"
DATA = json.loads((ROOT / "docs" / "data" / "site.json").read_text(encoding="utf-8"))
SNAP = DATA["snapshot"]

BG0, BG1, LINE = "#0A1020", "#101C3F", "#22305A"
INK, MUTED = "#E8EEF9", "#8FA1C7"
TEAL, SAFFRON, RED, LAPIS = "#2EC4B6", "#F5B53D", "#F0556A", "#5B7CFA"
SANS = "'Segoe UI','Inter','Helvetica Neue',Tahoma,Arial,sans-serif"
MONO = "'JetBrains Mono','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def star(cx: float, cy: float, r: float, stroke: str, sw: float = 1.5, opacity: float = 1) -> str:
    """Eight-pointed star (two rotated squares), the khatam motif."""
    return (
        f'<g transform="translate({cx} {cy})" fill="none" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}">'
        f'<rect x="{-r}" y="{-r}" width="{2 * r}" height="{2 * r}"/>'
        f'<rect x="{-r}" y="{-r}" width="{2 * r}" height="{2 * r}" transform="rotate(45)"/></g>'
    )


def tile_pattern(pid: str, size: int = 72, opacity: float = 0.10) -> str:
    r = size * 0.30
    return (
        f'<pattern id="{pid}" width="{size}" height="{size}" patternUnits="userSpaceOnUse">'
        f'{star(size / 2, size / 2, r, TEAL, 1.2, opacity * 10)}'
        f'{star(0, 0, r * 0.7, LAPIS, 1, opacity * 10)}{star(size, 0, r * 0.7, LAPIS, 1, opacity * 10)}'
        f'{star(0, size, r * 0.7, LAPIS, 1, opacity * 10)}{star(size, size, r * 0.7, LAPIS, 1, opacity * 10)}</pattern>'
    )


def logo(x: float, y: float, s: float) -> str:
    return (
        f'<g transform="translate({x} {y}) scale({s})">'
        f'<rect x="-30" y="-30" width="60" height="60" rx="14" fill="{BG1}" stroke="{TEAL}" stroke-width="2"/>'
        f'{star(0, 0, 15, TEAL, 2.4)}{star(0, 0, 8, SAFFRON, 2)}'
        f'<circle r="3" fill="{SAFFRON}"/></g>'
    )


def reveal(cycle: float, start: float, end: float, fade: float = 0.4) -> str:
    """SMIL opacity timeline: hidden until `start`, visible until `end`, hidden again at loop end."""
    k = lambda t: f"{max(0.0, min(1.0, t / cycle)):.4f}"  # noqa: E731
    return (
        f'<animate attributeName="opacity" values="0;0;1;1;0" '
        f'keyTimes="0;{k(start)};{k(start + fade)};{k(end)};1" dur="{cycle}s" repeatCount="indefinite"/>'
    )


# ----------------------------------------------------------------------------- banner
def banner() -> str:
    ob = SNAP["foolad"]["order_book"]
    asks = ob["asks"][:5][::-1]
    bids = ob["bids"][:5]
    import math

    def scale(volume: float) -> float:  # log scale so a single huge queue does not flatten the other levels
        return math.log10(volume + 10) / math.log10(max(a["volume"] for a in asks + bids) + 10)
    q = SNAP["foolad"]["quote"]
    tape = SNAP["tape"][:14]

    rows = []
    row_h, x0, w_max, y0 = 19, 830, 250, 94
    for i, a in enumerate(asks):
        w = max(8, scale(a["volume"]) * w_max)
        y = y0 + i * row_h
        rows.append(
            f'<g><rect x="{x0}" y="{y}" width="{w:.1f}" height="14" rx="3" fill="{RED}" opacity=".85">'
            f'<animate attributeName="width" values="{w:.1f};{w * .72:.1f};{w * 1.05:.1f};{w:.1f}" dur="{3 + i * .7:.1f}s" repeatCount="indefinite"/></rect>'
            f'<text x="{x0 - 10}" y="{y + 12}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">{fmt(a["price"])}</text></g>'
        )
    mid = y0 + 5 * row_h + 6
    rows.append(f'<line x1="{x0 - 70}" x2="{x0 + w_max + 20}" y1="{mid}" y2="{mid}" stroke="{LINE}"/>')
    rows.append(
        f'<text x="{x0 - 10}" y="{mid + 20}" text-anchor="end" font-family="{MONO}" font-size="15" font-weight="700" fill="{INK}">{fmt(q["last"]["price"])}</text>'
        f'<text x="{x0}" y="{mid + 20}" font-family="{MONO}" font-size="13" fill="{TEAL if q["last"]["change_pct"] >= 0 else RED}">{q["last"]["change_pct"]:+.2f}%</text>'
    )
    for i, b in enumerate(bids):
        w = max(8, scale(b["volume"]) * w_max)
        y = mid + 28 + i * row_h
        rows.append(
            f'<g><rect x="{x0}" y="{y}" width="{w:.1f}" height="14" rx="3" fill="{TEAL}" opacity=".85">'
            f'<animate attributeName="width" values="{w:.1f};{w * 1.08:.1f};{w * .8:.1f};{w:.1f}" dur="{2.6 + i * .6:.1f}s" repeatCount="indefinite"/></rect>'
            f'<text x="{x0 - 10}" y="{y + 12}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">{fmt(b["price"])}</text></g>'
        )

    ticker_items, x = [], 0
    for t in tape:
        colour = TEAL if t["pct"] >= 0 else RED
        nums = f'{fmt(t["last"])}  {t["pct"]:+.2f}%'
        ticker_items.append(
            f'<text x="{x}" y="0" font-family="{SANS}" font-size="14" font-weight="700" fill="{INK}">{escape(t["symbol"])}</text>'
            f'<text x="{x + 78}" y="0" font-family="{MONO}" font-size="14" fill="{colour}">{nums}</text>'
        )
        x += 78 + len(nums) * 8.6 + 34
    ticker_w = x
    ticker = "".join(ticker_items)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 400" width="1280" height="400" role="img" aria-label="iran-bourse-mcp: the Tehran Stock Exchange for AI agents">
<title>iran-bourse-mcp: the Tehran Stock Exchange for AI agents</title>
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/><stop offset="1" stop-color="{BG1}"/></linearGradient>
<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".45" stop-color="#fff" stop-opacity=".9"/><stop offset="1" stop-color="#fff"/></linearGradient>
<mask id="m"><rect width="1280" height="400" fill="url(#fade)"/></mask>
<linearGradient id="tfade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".06" stop-color="#fff"/><stop offset=".94" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<mask id="tm"><rect width="1280" height="40" fill="url(#tfade)"/></mask>
{tile_pattern("tiles", 72, .06)}
<clipPath id="ob"><rect x="720" y="40" width="520" height="290" rx="16"/></clipPath>
</defs>
<rect width="1280" height="400" fill="url(#bg)"/>
<rect width="1280" height="400" fill="url(#tiles)" mask="url(#m)"/>
<rect x=".5" y=".5" width="1279" height="399" fill="none" stroke="{LINE}"/>

<!-- brand block -->
{logo(94, 92, 1.15)}
<text x="150" y="86" font-family="{SANS}" font-size="13" font-weight="700" letter-spacing="3" fill="{SAFFRON}">MODEL CONTEXT PROTOCOL SERVER</text>
<text x="146" y="150" font-family="{SANS}" font-size="62" font-weight="800" fill="{INK}" letter-spacing="-1.5">iran-bourse-mcp</text>
<text x="64" y="200" font-family="{SANS}" font-size="26" fill="{INK}">The Tehran Stock Exchange, for AI agents.</text>
<text x="64" y="238" font-family="{SANS}" font-size="22" fill="{MUTED}" unicode-bidi="plaintext">بورس تهران، برای ایجنت‌های هوش مصنوعی</text>

<g font-family="{SANS}" font-size="14" font-weight="600">
<rect x="64" y="268" width="104" height="30" rx="15" fill="none" stroke="{TEAL}"/><text x="116" y="288" text-anchor="middle" fill="{TEAL}">38 tools</text>
<rect x="178" y="268" width="104" height="30" rx="15" fill="none" stroke="{LAPIS}"/><text x="230" y="288" text-anchor="middle" fill="{INK}">read-only</text>
<rect x="292" y="268" width="148" height="30" rx="15" fill="none" stroke="{SAFFRON}"/><text x="366" y="288" text-anchor="middle" fill="{INK}">100% tick coverage</text>
<rect x="450" y="268" width="66" height="30" rx="15" fill="none" stroke="{MUTED}"/><text x="483" y="288" text-anchor="middle" fill="{INK}">MIT</text>
</g>

<!-- animated order book -->
<g clip-path="url(#ob)">
<rect x="720" y="40" width="520" height="290" rx="16" fill="{BG0}" fill-opacity=".72" stroke="{LINE}"/>
<text x="744" y="76" font-family="{SANS}" font-size="15" font-weight="700" fill="{INK}">فولاد</text>
<text x="800" y="76" font-family="{MONO}" font-size="12" fill="{MUTED}">order book · live depth</text>
<circle cx="1210" cy="71" r="5" fill="{TEAL}"><animate attributeName="opacity" values="1;.25;1" dur="1.6s" repeatCount="indefinite"/></circle>
{"".join(rows)}
</g>
<text x="1222" y="322" text-anchor="end" font-family="{MONO}" font-size="10" fill="{MUTED}" opacity=".8">log-scaled depth · snapshot {escape(SNAP["captured_at_utc"])}</text>

<!-- ticker tape -->
<rect x="0" y="360" width="1280" height="40" fill="{BG0}" opacity=".9"/>
<line x1="0" x2="1280" y1="360.5" y2="360.5" stroke="{LINE}"/>
<g mask="url(#tm)" transform="translate(0 360)"><g transform="translate(0 25)">
<g><animateTransform attributeName="transform" type="translate" from="0 0" to="-{ticker_w:.0f} 0" dur="{ticker_w / 55:.0f}s" repeatCount="indefinite"/>
{ticker}<g transform="translate({ticker_w:.0f} 0)">{ticker}</g><g transform="translate({2 * ticker_w:.0f} 0)">{ticker}</g></g>
</g></g>
</svg>'''


# ----------------------------------------------------------------------------- terminal demo
def demo() -> str:
    cycle = 22.0
    q = SNAP["foolad"]["quote"]
    flow = SNAP["foolad"]["real_legal"] or {}
    real = flow.get("real", {})
    comp = SNAP["foolad"]["trade_summary"]["completeness"]
    holders = (SNAP["foolad"]["holders"] or {}).get("top", [])[:2]
    filings = SNAP["foolad"].get("filings") or []
    net = real.get("net_value")
    net_txt = f"{abs(net) / 1e9:,.0f}bn Rial {'in' if net and net > 0 else 'out'}" if net is not None else "n/a"

    lines = [
        # (start, end, y, color, text, size, weight, typed)
        (0.6, 20.5, 118, INK, "> Review Foolad in depth: queue, real-person money flow, major holders.", 17, 500, True),
        (3.4, 20.5, 158, MUTED, "  ● iran-bourse › symbol_overview(symbol=\"فولاد\")", 15, 400, False),
        (4.4, 20.5, 182, MUTED, "  ● iran-bourse › real_legal_flow(symbol=\"فولاد\", days=5)", 15, 400, False),
        (5.4, 20.5, 206, MUTED, "  ● iran-bourse › trade_summary(symbol=\"فولاد\")", 15, 400, False),
        (7.2, 20.5, 252, INK, f"Foolad trades at {fmt(q['last']['price'])} Rial ({q['last']['change_pct']:+.2f}%), "
         f"{'locked at the upper price limit' if q['at_upper_limit'] else 'inside its price band'}.", 16, 700, False),
        (8.6, 20.5, 282, INK, f"• Money flow: real persons net {net_txt} (buyer power {flow.get('real_buyer_power')}).", 15, 400, False),
        (10.0, 20.5, 308, INK, f"• Ticks: {comp['ticks_count']:,} trades, {comp['volume_coverage_pct']}% of official volume. Nothing missing.", 15, 400, False),
        (11.4, 20.5, 334, INK, (f"• Largest holder owns {holders[0]['percent']}%, top five {(SNAP['foolad']['holders'] or {}).get('top5_percent')}%." if holders else "• Major holders listed."), 15, 400, False),
        (12.8, 20.5, 360, INK, (f"• Latest Codal filing: #{filings[0]['tracing_no']}, published {filings[0]['published'][:10]}." if filings else "• Latest Codal filings linked."), 15, 400, False),
        (14.4, 20.5, 400, MUTED, "Numbers marked estimate are derived; everything else is exchange data. Not investment advice.", 13, 400, False),
]
    body = []
    for start, end, y, colour, text, size, weight, typed in lines:
        t = escape(text)
        if typed:
            width = len(text) * size * 0.60
            body.append(
                f'<clipPath id="c{y}"><rect x="40" y="{y - size}" width="{width:.0f}" height="{size + 8}">'
                f'<animate attributeName="width" values="0;0;{width:.0f};{width:.0f};0" keyTimes="0;{start / cycle:.4f};{(start + 2.6) / cycle:.4f};{end / cycle:.4f};1" dur="{cycle}s" repeatCount="indefinite"/></rect></clipPath>'
                f'<text clip-path="url(#c{y})" x="40" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{colour}" xml:space="preserve">{t}</text>'
            )
        else:
            body.append(
                f'<text x="40" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{colour}" xml:space="preserve">{t}{reveal(cycle, start, end)}</text>'
            )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 440" width="1000" height="440" role="img" aria-label="An AI agent answering a Tehran Stock Exchange question through iran-bourse-mcp">
<title>An AI agent answering a Tehran Stock Exchange question through iran-bourse-mcp</title>
<rect width="1000" height="440" rx="14" fill="{BG0}" stroke="{LINE}"/>
<rect width="1000" height="46" rx="14" fill="{BG1}"/><rect y="30" width="1000" height="16" fill="{BG1}"/>
<circle cx="26" cy="23" r="6" fill="#F0556A"/><circle cx="48" cy="23" r="6" fill="#F5B53D"/><circle cx="70" cy="23" r="6" fill="#2EC4B6"/>
<text x="500" y="28" text-anchor="middle" font-family="{SANS}" font-size="13" fill="{MUTED}">agent · iran-bourse-mcp</text>
<line x1="0" x2="1000" y1="46.5" y2="46.5" stroke="{LINE}"/>
{"".join(body)}
<rect x="40" y="100" width="9" height="20" fill="{TEAL}" opacity="0"><animate attributeName="opacity" values="0;1;0" dur="1s" repeatCount="indefinite"/></rect>
</svg>'''


# ----------------------------------------------------------------------------- architecture
def box(x: int, y: int, w: int, h: int, title: str, lines: list[str], colour: str, fill: str = BG1) -> str:
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{colour}" stroke-width="1.5"/>',
           f'<text x="{x + 18}" y="{y + 30}" font-family="{SANS}" font-size="16" font-weight="700" fill="{INK}">{escape(title)}</text>']
    for i, line in enumerate(lines):
        out.append(f'<text x="{x + 18}" y="{y + 56 + i * 20}" font-family="{MONO}" font-size="12.5" fill="{MUTED}">{escape(line)}</text>')
    return "".join(out)


def architecture() -> str:
    flow = lambda x1, y1, x2, y2, colour=TEAL: (  # noqa: E731
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" stroke-width="2" stroke-dasharray="6 6"><animate attributeName="stroke-dashoffset" from="24" to="0" dur="1.2s" repeatCount="indefinite"/></line>'
        f'<path d="M{x2 - 9} {y2 - 6} L{x2} {y2} L{x2 - 9} {y2 + 6}" fill="none" stroke="{colour}" stroke-width="2"/>'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 470" width="1100" height="470" role="img" aria-label="Architecture of iran-bourse-mcp">
<title>Architecture of iran-bourse-mcp</title>
<defs>{tile_pattern("t2", 72, .045)}</defs>
<rect width="1100" height="470" rx="14" fill="{BG0}" stroke="{LINE}"/><rect width="1100" height="470" rx="14" fill="url(#t2)"/>
{box(24, 120, 220, 200, "Your agent", ["Claude · Codex · Gemini", "Cursor · VS Code · Zed", "Goose · OpenCode · Cline", "LangChain · OpenAI SDK", "any shell: `call`"], LAPIS)}
{flow(246, 220, 316, 220, LAPIS)}
<text x="281" y="206" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{MUTED}">MCP</text>
<text x="281" y="250" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{MUTED}">stdio / HTTP</text>
<rect x="318" y="30" width="470" height="410" rx="16" fill="{BG0}" fill-opacity=".6" stroke="{TEAL}" stroke-width="1.5" stroke-dasharray="2 4"/>
<text x="338" y="58" font-family="{SANS}" font-size="13" font-weight="700" letter-spacing="2" fill="{TEAL}">IRAN-BOURSE-MCP</text>
{box(344, 76, 418, 66, "server.py", ["38 read-only tools · 4 prompts · glossary"], TEAL)}
{box(344, 160, 418, 66, "service.py", ["one coroutine per tool · joins sources · validates"], TEAL)}
{box(344, 244, 418, 76, "shape.py  (pure, tested)", ["queues · book rebuild · ticks · flows · adjustment"], SAFFRON)}
{box(344, 338, 200, 82, "resolver.py", ["symbol → insCode", "ی/ي ک/ك safe"], TEAL)}
{box(562, 338, 200, 82, "api + client", ["cache · retry · 6 in flight", "browser UA · proxy"], TEAL)}
{flow(790, 130, 858, 100)}
{flow(790, 230, 858, 230)}
{flow(790, 330, 858, 360)}
{box(860, 56, 216, 90, "TSETMC API", ["cdn.tsetmc.com", "ticks · book · holders"], RED)}
{box(860, 185, 216, 90, "TSE gateway", ["webgw.tse.ir", "market watch · 590 rows"], RED)}
{box(860, 314, 216, 90, "Codal", ["search.codal.ir", "filings · PDF · Excel"], RED)}
<text x="550" y="458" text-anchor="middle" font-family="{SANS}" font-size="12" fill="{MUTED}">Facts are returned as published. Derived numbers are labelled estimate. Nothing can place an order.</text>
</svg>'''


# ----------------------------------------------------------------------------- social preview
def social() -> str:
    tape = SNAP["tape"][:6]
    chips = []
    for i, t in enumerate(tape):
        colour = TEAL if t["pct"] >= 0 else RED
        chips.append(
            f'<g transform="translate({80 + i * 190} 556)"><rect width="172" height="46" rx="10" fill="{BG1}" stroke="{LINE}"/>'
            f'<text x="14" y="29" font-family="{SANS}" font-size="16" font-weight="700" fill="{INK}">{escape(t["symbol"])}</text>'
            f'<text x="158" y="29" text-anchor="end" font-family="{MONO}" font-size="14" fill="{colour}">{t["pct"]:+.2f}%</text></g>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/><stop offset="1" stop-color="{BG1}"/></linearGradient>{tile_pattern("t3", 72, .07)}
<linearGradient id="f" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".1"/><stop offset="1" stop-color="#fff"/></linearGradient><mask id="mm"><rect width="1280" height="640" fill="url(#f)"/></mask></defs>
<rect width="1280" height="640" fill="url(#g)"/><rect width="1280" height="640" fill="url(#t3)" mask="url(#mm)"/>
{logo(120, 120, 1.5)}
<text x="80" y="268" font-family="{SANS}" font-size="104" font-weight="800" fill="{INK}" letter-spacing="-3">iran-bourse-mcp</text>
<text x="80" y="340" font-family="{SANS}" font-size="40" fill="{INK}">The Tehran Stock Exchange, for AI agents.</text>
<text x="80" y="396" font-family="{SANS}" font-size="32" fill="{MUTED}" unicode-bidi="plaintext">بورس تهران، برای ایجنت‌های هوش مصنوعی</text>
<g font-family="{SANS}" font-size="22" font-weight="600" fill="{INK}">
<rect x="80" y="440" width="150" height="46" rx="23" fill="none" stroke="{TEAL}" stroke-width="2"/><text x="155" y="471" text-anchor="middle" fill="{TEAL}">38 tools</text>
<rect x="244" y="440" width="150" height="46" rx="23" fill="none" stroke="{LAPIS}" stroke-width="2"/><text x="319" y="471" text-anchor="middle">read-only</text>
<rect x="408" y="440" width="230" height="46" rx="23" fill="none" stroke="{SAFFRON}" stroke-width="2"/><text x="523" y="471" text-anchor="middle">100% tick coverage</text>
<rect x="652" y="440" width="190" height="46" rx="23" fill="none" stroke="{MUTED}" stroke-width="2"/><text x="747" y="471" text-anchor="middle">works with any agent</text>
</g>
{"".join(chips)}
</svg>'''


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "tiles.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
        f'<g fill="none" stroke="{TEAL}" stroke-width="1" opacity=".5">{star(48, 48, 29, TEAL, 1)}</g>'
        f'<g fill="none" stroke="{LAPIS}" stroke-width="1" opacity=".5">{star(0, 0, 20, LAPIS, 1)}{star(96, 0, 20, LAPIS, 1)}{star(0, 96, 20, LAPIS, 1)}{star(96, 96, 20, LAPIS, 1)}</g></svg>',
        encoding="utf-8",
    )
    (ASSETS / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-34 -34 68 68"><rect x="-32" y="-32" width="64" height="64" rx="15" fill="{BG0}" stroke="{TEAL}" stroke-width="3"/>'
        f'{star(0, 0, 16, TEAL, 3)}{star(0, 0, 8.5, SAFFRON, 2.6)}<circle r="3.4" fill="{SAFFRON}"/></svg>',
        encoding="utf-8",
    )
    for name, svg in (("banner.svg", banner()), ("demo.svg", demo()), ("architecture.svg", architecture()), ("social-preview.svg", social())):
        (ASSETS / name).write_text(svg, encoding="utf-8")
        print("wrote", name, len(svg) // 1024, "KB")


if __name__ == "__main__":
    main()

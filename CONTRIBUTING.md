# Contributing

Thanks for helping. This project lives or dies on **data correctness**, so the bar is: every number must be explainable and tested.

## Setup

```bash
git clone https://github.com/msmahdinejad/iran-bourse-mcp && cd iran-bourse-mcp
uv sync
uv run pytest        # offline, no network needed
uv run ruff check .
```

To exercise the real servers you need a connection that can reach TSETMC (see the README):

```bash
uv run iran-bourse-mcp doctor
uv run python scripts/smoke_live.py
```

## Ground rules

1. **Pure logic goes in `shape.py` with a test.** Prefer recorded fixtures from `tests/fixtures` (refresh them with `scripts/capture_fixtures.py`) plus a small synthetic case that pins the edge you care about.
2. **Facts vs estimates.** If the exchange does not publish it, name it `estimate`/`estimated` and say how it is computed.
3. **Units.** Rial for prices and values, shares for volume. Say so in the docstring or in a `units` key.
4. **Read-only.** No order placement, no logins, no credential handling. PRs adding them will be declined.
5. **Be gentle with upstream.** Reuse the cache, keep concurrency low, never loop over the whole market per symbol.
6. **Tool docstrings are prompts.** The first sentence says what it returns and includes the Persian term people actually type.
7. Run `uv run python scripts/gen_tools_doc.py` when tools or parameters change.
8. **Every tool needs a contract scenario** (recorded real responses, replayed offline). A new tool fails `tests/contract` until it has one; see [tests/README.md](tests/README.md).

## Generated files

Some files are generated so they cannot drift from the code. Regenerate them (needs access to TSETMC for the live ones) and commit the result:

| File | Command |
|---|---|
| `docs/TOOLS.md` | `uv run python scripts/gen_tools_doc.py` (CI fails if it is stale) |
| `docs/EXAMPLES.md` | `uv run python scripts/gen_examples.py` (live) |
| `docs/data.js`, `docs/data/site.json` (website data) | `uv run python scripts/gen_site_data.py` (live) |
| `docs/assets/*.svg` (banner, demo, architecture) | `uv run python scripts/gen_assets.py` |
| `docs/assets/bench-*.svg` | `uv run python scripts/gen_bench_charts.py` (needs Edge or Chrome) |
| install and benchmark blocks of `README.md` | `uv run python scripts/gen_readme.py` |
| `benchmarks/results/*.json` | see [benchmarks/README.md](benchmarks/README.md) |

The install recipes for every agent live in one table, `src/iran_bourse_mcp/clients.py`. To support a new client, add a row there and a test; the CLI, README and website pick it up.

## Reporting a broken endpoint

TSETMC changes without notice. Open an issue with the output of `iran-bourse-mcp doctor`, the tool name and arguments, and (if you can) the raw URL and response snippet. A failing live check in `scripts/smoke_live.py` is the ideal bug report.

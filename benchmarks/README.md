# Benchmarks

Everything here is re-runnable. Numbers are from the live exchange, not from a model of it.

There are two benchmarks, because they answer different questions.

1. **Data plane** (`data_plane.py`): what must a model read, and how many requests must an agent make, to get the data for a task with and without the server? Deterministic, no LLM involved.
2. **Agent trials** (`tasks.json`, `ground_truth.py`, `grade.py`, `aggregate_agents.py`): real LLM agents answer the same questions with three different toolsets, and their answers are graded against independent ground truth.

## 1. Data plane

For eight everyday tasks we measure two routes:

- **Raw route**: the fewest raw TSETMC / TSE gateway / Codal HTTP requests that contain the answer. This is the *best case*: it assumes the agent already knows the hidden endpoints, which a browser-only agent does not.
- **MCP**: one tool call to the in-process server (cold cache).

Metrics: HTTP requests, wall-clock seconds (sequential requests for the raw route), payload bytes, and tokens. Tokens are estimated with tiktoken `o200k_base`, which is a proxy; absolute numbers differ per model, ratios hold. The raw route's token count is the payload a model would have to read if the JSON were pasted into its context; a code-executing agent can avoid that by processing the JSON in a script, which is what the agent trials below measure.

It also checks five **traps**: places where a plausible reading of the raw JSON gives a confidently wrong answer (a change field that says 0 while the price rose, shareholder rows returned twice, a field named differently on two endpoints, queues guessed from market watch, Arabic vs Persian letters).

```bash
uv run python benchmarks/data_plane.py --repeats 3     # writes results/data_plane.json
```

## 2. Agent trials

Six tasks, written in Persian with an English translation (`tasks.json`):

| Id | Task | Why it is hard without the server |
|---|---|---|
| T1 | Quote: last price, close, % change, volume, value | Easy, but the exchange's own change field is wrong |
| T2 | One day of ticks: VWAP, trade count, largest trade and its time | 3 MB of JSON; 15,643 ticks |
| T3 | Net real-person money flow over three days | Value fields only exist on history rows, count keys differ |
| T4 | Market-wide: five biggest genuine buy queues | Needs the whole market plus one order book per limit-up stock |
| T5 | Latest three Codal filings | Codal's site is a JavaScript template |
| T6 | One-year return, adjusted for capital increase and dividend | The exchange's own adjustment list misses the capital increase |

Three arms, same model, same prompt wording, at most 25 tool calls each:

| Arm | Tools |
|---|---|
| **Browser-only** | A page-fetch tool. Cannot run code. What a typical chat agent has. |
| **Shell** | Bash (curl, python), page fetch, web search. A told-to-avoid-the-repo power user; it may use endpoints it remembers from training, and it was given the hint that some sites need a browser-like User-Agent. |
| **MCP** | The same shell, plus the 28 tool descriptions in its prompt, calling tools through `iran-bourse-mcp call` (equivalent to MCP tool calls; the schema cost is included). It is told to use only these tools. |

**Ground truth** (`ground_truth.py`) is recomputed from the raw upstream JSON with the simplest possible code and imports nothing from `iran_bourse_mcp`. **Grading** (`grade.py`) compares field by field with tolerances (price exact, percentages within 0.02, values within 0.1%). T4 is graded on the ranking only (top-1, at least 4 of 5 symbols, exact order), because queue sizes keep changing after the close.

Token counts are the agent harness's totals. Each agent type carries a fixed overhead (system prompt, tool schemas) which we measured with a do-nothing agent (`base_tokens` in `results/agent_runs.json`) and subtract to report **net tokens**.

```bash
uv run python benchmarks/ground_truth.py        # after the 12:30 Tehran close, so data is stable
uv run python benchmarks/aggregate_agents.py    # grades results/agent_runs.json -> results/agents.json
```

Raw per-run metrics and every final answer are in `results/agent_runs.json`.

## Latest results

<!-- BENCH:START -->
<div align="center">
<img src="../docs/assets/bench-tokens.svg" alt="Benchmark: tokens" width="49%">
<img src="../docs/assets/bench-time.svg" alt="Benchmark: time" width="49%">
<img src="../docs/assets/bench-requests.svg" alt="Benchmark: requests" width="49%">
<img src="../docs/assets/bench-accuracy.svg" alt="Benchmark: accuracy" width="49%">
</div>

| Task | Raw route | iran-bourse-mcp | Tokens saved |
|---|---|---|---|
| Live quote with correct % change | 3 req · 0.4s · 6,225 tok | 1 call · 0.5s · 337 tok | **18x** |
| Order book with queue detection | 3 req · 0.3s · 6,298 tok | 1 call · 0.6s · 388 tok | **16x** |
| One day of ticks: VWAP, biggest trades, bars | 3 req · 0.7s · 2,142,302 tok | 1 call · 1.1s · 3,380 tok | **634x** |
| Real vs legal money flow, 10 days | 12 req · 0.9s · 612,009 tok | 1 call · 1.2s · 1,332 tok | **460x** |
| Major shareholders | 3 req · 0.4s · 7,018 tok | 1 call · 0.7s · 686 tok | **10x** |
| Market-wide ranking of buy queues | 222 req · 15.0s · 695,971 tok | 1 call · 9.4s · 1,241 tok | **561x** |
| Latest 5 Codal filings with links | 1 req · 1.6s · 6,489 tok | 1 call · 1.6s · 1,539 tok | **4x** |
| One year of daily prices, adjusted | 2 req · 0.4s · 610,549 tok | 1 call · 0.8s · 19,517 tok | **31x** |
| Screen the market: volume > 2x 20-day average, up yesterday and today | 22 req · 5.8s · 7,437,128 tok | 1 call · 3.9s · 723 tok | **10,286x** |

_Data-plane benchmark, 2026-11-04 15:51:55 UTC. Tokens are a tiktoken `o200k_base` proxy; the ratios matter more than the absolute numbers. A single-endpoint task takes about as long either way; the server wins where the raw route needs many sequential requests, and on tokens everywhere._

**Traps in the raw data** (each found on the live endpoints and handled by the server):

| Trap | Naive reading | Correct |
|---|---|---|
| The exchange's own `priceChange` field in GetClosingPriceInfo | `0.0` | `120.0` |
| Counting holders / summing percent from the dated shareholder endpoint | `{"holders": 24, "percent_sum": 92.97}` | `{"holders": 12, "percent_sum": 46.48}` |
| Reading real-buyer count with the key used by the live endpoint (`buy_CountI`) on history rows | `null` | `3790.0` |
| Calling every limit-up stock without visible sell orders a buy queue, using the gateway's market watch alone | `85` | `83` |
| Matching the company name the user types (Persian letters) against the exchange's text (Arabic letters) | `false` | `true` |

**Agent trials** (one LLM agent model, identical in every arm, 2026-11-04; 6 tasks, graded against independent ground truth):

| Agent | Accuracy | Net tokens (mean/task) | Time (mean/task) | Tool calls | Answered |
|---|---|---|---|---|---|
| Browser-only agent (page fetch) | 21% | 100,054 | 190s | 9.2 | 4/6 |
| Shell agent (curl/python + web, no MCP) | 94% | 17,129 | 83s | 6.8 | 6/6 |
| Agent + iran-bourse-mcp | 100% | 11,512 | 36s | 3.0 | 6/6 |

_Six tasks, one model, runs per task: 1 (2 for T2 and T6 in the shell and MCP arms). The shell agent used its own knowledge of the exchange's endpoints. On T4 it classified a fixed-price symbol (فولاد3) as an ordinary share, a different but defensible reading of 'ordinary shares'; queue sizes also drift by tens of percent within minutes after the close, so T4 is graded on the ranking only._

<!-- BENCH:END -->

## Caveats, stated plainly

- **Small and single-model.** Six tasks, one run per arm and task, one model. Treat the agent trials as indicative, not statistical. Variation between runs of the same agent is real.
- **The shell arm is strong.** It knows TSETMC's hidden endpoints from training and was helped by a User-Agent hint. A weaker model, or an endpoint it does not remember, would do worse. On single-endpoint tasks it matches the server on accuracy; the server wins on tool calls and time, and on every task where raw data is large or the trap is subtle.
- **Wall-clock time** of the data plane is about the same for single-endpoint tasks (the server adds a little processing). It wins where the raw route needs many sequential requests.
- **Tokens are a proxy** (tiktoken o200k_base) in the data plane and the harness's own totals in the agent trials.
- **Ground truth for T4** is a brute-force recomputation with the same definition (queue = no sell volume at the best prices and a bid at the daily upper limit); the definition is ours, the data is the exchange's.
- Everything depends on the day's market state and on the exchange's servers answering. Re-run before quoting a number.

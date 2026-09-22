# Backtest Lab

可執行的單一股票、Long-only 均線突破回測 Web App。系統以 Daily OHLCV 計算策略與模擬成交，對日 K 無法辨識的盤中順序採保守 adverse-first 假設，並保留完整 execution、position、strategy event log 供稽核。

> 這不是投資建議。回測結果高度依賴資料品質、成交假設、交易成本與樣本期間。

## Architecture

```text
backtest-web/
├── backend/
│   ├── app/
│   │   ├── api/               FastAPI routes
│   │   ├── backtest/          indicators, execution, portfolio, metrics, engine
│   │   │   └── strategies/    Simple / Advanced / Day1-stop state machines
│   │   ├── data/              provider interface, Yahoo, Stooq fallback, isolated caches
│   │   └── db/                SQLite repository
│   └── tests/                 synthetic strategy-correctness and engine tests
├── frontend/                  Next.js + React + TypeScript + Tailwind
├── data/                      local Parquet cache and SQLite history
└── docker-compose.yml
```

The concerns are deliberately separated:

- Strategy classes create state transitions and order intent; they do not calculate commission, metrics, or persistence.
- `Portfolio` performs whole-share sizing, cash accounting, commission, and buy/sell slippage.
- Shared Entry Zone v2 evaluation owns the exact `[LowerEntry, UpperEntry]` boundary for all three strategies. Pluggable Conservative, OHLC Heuristic, and Favorable policies resolve only unknowable Daily OHLC ordering.
- `DataProvider` exposes normalized daily OHLCV. The engine depends on the interface, not Yahoo, so CSV/Parquet/other providers can be added later.
- `BacktestRepository` persists request parameters, status, summary, and the full reproducible result.

## Installation

Requirements: Python 3.12+, Node.js 20+ (22 recommended), npm.

Backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. API docs are at `http://localhost:8000/docs`.

One-command container startup (desktop-only by default):

```bash
docker compose up --build
```

## Environment Variables

Copy `.env.example` as needed.

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | empty | Empty uses the recommended same-origin `/api` proxy; set only for a separate public API origin |
| `BACKEND_INTERNAL_URL` | `http://127.0.0.1:8000` | Server-side Next.js proxy target; never resolved by the phone |
| `ALLOWED_ORIGINS` | localhost and 127.0.0.1 | Comma-separated direct-browser API origins |
| `ALLOWED_HOSTS` | `*` | Trusted HTTP hostnames; set the public domain in production |
| `DATA_DIR` | `../data` | Persistent data root |
| `CACHE_DIR` | `$DATA_DIR/cache` | Persistent Parquet cache |
| `DATABASE_URL` | `$DATA_DIR/backtests.sqlite3` | SQLite URL, e.g. `sqlite:////data/backtests.sqlite3` in containers |
| `MAX_REQUEST_BYTES` | `1048576` | Maximum request body size |
| `YAHOO_REQUEST_TIMEOUT_SECONDS` | `20` | Hard limit for one isolated Yahoo daily-data request |
| `YAHOO_MAX_RETRIES` | `3` | Number of retries after the initial Yahoo attempt (per host round) |
| `YAHOO_RETRY_BACKOFF_SECONDS` | `1` | Exponential retry base; defaults to 1s, 2s, 4s |
| `YAHOO_STATUS_TIMEOUT_SECONDS` | `3` | Timeout for the lightweight provider status probe |
| `YAHOO_OFFLINE_COOLDOWN_SECONDS` | `300` | Do not repeat Yahoo probes/retries during a known outage |
| `YAHOO_STATUS_CACHE_SECONDS` | `60` | Cache successful/degraded Yahoo reachability probes |
| `STOOQ_REQUEST_TIMEOUT_SECONDS` | `20` | Hard limit for one isolated Stooq daily-data request |
| `STOOQ_MAX_RETRIES` | `2` | Number of retries after the initial Stooq attempt |
| `STOOQ_RETRY_BACKOFF_SECONDS` | `1` | Stooq exponential retry base |
| `STOOQ_STATUS_TIMEOUT_SECONDS` | `3` | Timeout for the Stooq status probe |
| `STOOQ_STATUS_CACHE_SECONDS` | `60` | Cache successful Stooq reachability probes |

## Using Backtest Web from Your Phone

The secure LAN design exposes only Next.js. FastAPI stays on the computer at `127.0.0.1:8000`; Next.js proxies `/api/*` internally. A phone never connects to port 8000 and never sees a `localhost` API URL.

### Zero-terminal Windows workflow

The end-user workflow is zero-terminal: ask Codex to open the stock backtest site, then use the Traditional Chinese web interface. Codex checks the Windows-side supervisor, starts it when necessary, confirms the application health, and provides the current LAN URL. A hidden one-click launcher is also included as a recovery entry point, but it is not part of the normal user workflow.

The watchdog restores either service after a crash. The backend runs from a project-owned Windows Python runtime and remains on `127.0.0.1:8000`; it does not depend on a transient Codex runtime process. Internal maintenance scripts and process details are implementation concerns, not end-user steps.

The displayed Computer URL and Phone URL both use the LAN address because the frontend deliberately binds only that address. The backend remains loopback-only. Windows may request a firewall exception for Node.js: approve **Private networks** only. No inbound rule is needed for Python or port 8000.

The watchdog checks every 15 seconds and permits at most five restarts per ten-minute window, preventing a fast crash loop. It does not change Windows power settings. The computer must remain powered on, awake, and connected to the network; a sleeping computer cannot serve the phone.

The LAN address is detected again on every start and status check. If your router later assigns a different address, use the newly printed URL. For a permanently stable phone URL, configure a DHCP reservation in the router; the project does not change router settings automatically.

1. Connect the computer and iPhone/Android device to the same Wi-Fi. Guest networks often block device-to-device traffic.
2. Ask Codex: 「打開股票回測網站」。
3. Open the LAN URL provided by Codex in Safari or Chrome.
4. Use the Traditional Chinese website for backtests, data downloads, provider checks, retries, risk-free-rate updates, and research jobs.

After Windows permits the current-user sign-in registration, the same supervisor can start automatically after sign-in. If Windows blocks registration, the only required user action is approving that registration in the Windows graphical security prompt; no terminal command is required.

### Firewall troubleshooting

- Windows Defender Firewall may prompt when Next.js first binds the Wi-Fi address. Approve **Private networks** only. Do not approve Public networks and do not create an inbound rule for port 8000.
- If no prompt appears, allow the installed Node.js executable on Private networks or add a narrowly scoped inbound TCP rule for port 3000 on the Private profile.
- On macOS, open **System Settings → Network → Firewall → Options** and allow incoming connections for Node.js. Keep Python/FastAPI unexposed.
- Disable VPN/client isolation temporarily if the phone cannot reach the printed URL. Confirm the phone and computer use the same subnet.
- If a Windows security dialog appears, allow the installed Node.js application on **Private networks** only. The backend remains local and requires no public firewall permission.

## Mobile Experience

- At widths below 900px the fixed desktop sidebar becomes a vertical settings surface.
- Market, Strategy, Entry, Validation, Risk Control, Take Profit, Extreme Take Profit, Backtest Settings, and Trading Costs are collapsible.
- Numeric fields request numeric/decimal mobile keyboards.
- The Run action is fixed above the iOS safe area, disabled during execution, and shows data/indicator/engine/metrics progress stages.
- The first six mobile metrics are Strategy Return, Buy & Hold, CAGR, Max Drawdown, Sharpe, and Trades in a two-column grid.
- Lightweight Charts enables touch horizontal pan and pinch zoom. Recharts use responsive containers. Monthly returns switch to a compact three-column mobile grid.
- Position, execution, and event tables become expandable mobile cards; desktop retains full tables.
- Result tabs remain single-line and horizontally scrollable.
- Backend-offline, invalid ticker, unavailable daily data, no-trade, and data warnings are visible in the page.
- `manifest.webmanifest`, theme metadata, safe-area viewport settings, and a maskable placeholder icon support Add to Home Screen. Offline backtesting is not provided.

## Production Deployment Readiness

`docker-compose.prod.yml` is a public deployment stack containing the production Next.js image, production Uvicorn process, an internal-only backend, a persistent `backtest_data` volume, and Caddy as the HTTPS reverse proxy. Caddy routes `/api/*` to FastAPI and all other traffic to Next.js, so mobile browsers use one HTTPS origin.

To deploy on a public Linux server:

1. Point the domain's DNS A/AAAA record at the server.
2. Allow inbound TCP 80/443 and UDP 443. Do not expose 3000 or 8000 publicly.
3. Copy `.env.production.example` to `.env.production` and set the real `DOMAIN`.
4. Run:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```

Caddy obtains and renews HTTPS certificates. The named `backtest_data` volume survives container replacement and stores both `backtests.sqlite3` and `cache/*.parquet`. Caddy certificate/config volumes are persistent too.

Back up persistent data with your platform's volume snapshot mechanism or by stopping the backend and copying `/data`. Do not run multiple Uvicorn workers against the same SQLite writer; this release intentionally uses one worker. For horizontal scaling, migrate the repository to a managed database and cache/object store first.

Security readiness includes strict Pydantic parameter schemas, a ticker character allowlist, a 20-year date-range maximum, a 1 MiB request limit, trusted-host configuration, production debug disabled, generic 500 responses, no user code execution, and no API that accepts filesystem paths.

The stack is deployment-ready, but a real public URL still requires a public Linux host, domain/DNS, ports 80/443, and Docker. No cloud account or domain was supplied, so this repository prepares deployment without creating an external deployment.

## Strategies

### Simple MA Percentage Breakout

For trading day `t`, all execution thresholds use `MA(t-1)`:

- `LowerEntry = reference MA × (1 + breakout_trigger_pct)` and `UpperEntry = reference MA × (1 + entry_stop_pct)`;
- if Open is at or below UpperEntry and High reaches UpperEntry, buy at exactly UpperEntry; Open equal to UpperEntry is allowed;
- if the first known price Open is above UpperEntry, do not chase at Open or later that day, and record `ENTRY_ZONE_MISSED` with the MA, both boundaries, Open, and `GAP_ABOVE_ENTRY_ZONE` reason;
- the armed stop expires at that day's close;
- exit all at `reference MA × (1 - exit_below_ma_pct)`.

### Advanced MA Breakout

Entry is identical to Simple. The explicit state machine contains `FLAT`, `ENTRY_ARMED`, Day 1/Day 2 validation, normal risk, break protection, post-first-TP, pending next-open exit, and closed states.

- Entry-day volume must be at least previous trading-day volume times the configured increase; failure exits at the next open.
- Day 2 close must be strictly greater than Day 1 close; equality fails and exits at Day 3 open.
- Before first TP, touching previous-day MA minus the risk threshold sells half of *current* shares and stores the break day's daily low.
- Starting the next trading day, a price strictly below that low exits all.
- Break protection resets only after close when the completed daily low is strictly above **current-day completed `MA(t)`**. The reset affects the following day.
- First TP uses the original actual fill `P0`, changes regime when reached, and normally sells half of current shares once.
- After first TP, the full protective stop is `max(P0, MA(t-1) × (1-risk_pct))`.
- Bias and ATR extremes compare Daily High with their threshold prices, using completed `MA(t-1)`, bias history through `t-1`, and `ATR(t-1)`. Their daily edge states re-arm independently after a completed day whose High is below the relevant threshold.
- One extreme execution sells configured percent of original `Q0`; simultaneous Bias/ATR rising edges make one sale; maximum count defaults to three.
- Profit-taking is blocked only when current shares are **below**, not equal to, the minimum Q0 ratio. Risk and forced full exits are never blocked.

### Advanced + Day1 3% Stop

This is a separate strategy implementation and leaves both Simple and Advanced unchanged. It inherits every Advanced entry, validation, Day 2+, break-protection, take-profit, protective-stop, Bias/ATR, Q0 sizing, and minimum-position rule. Its only difference is an entry-day-only full stop:

- `Day1Stop = MA(t-1) × (1 - day1_stop_pct)`, default 3%;
- if the entry day's completed Daily Low is at or below that level after an entry is feasible, all remaining shares exit with `DAY1_FULL_STOP`;
- an Open already below the stop uses the Open as the conservative gap fill;
- if entry, Day 1 stop, and/or a favorable target coexist inside one Daily OHLC bar, the engine assumes entry then adverse full stop, records `DAILY_INTRABAR_AMBIGUITY`, and suppresses favorable partial profit-taking;
- the Day 1 stop expires after the entry day. From Day 2 onward, the unchanged Advanced MA-risk half exit and BreakDayLow protection apply.

The Position Inspector exposes `Day1 Stop` only on the entry-day timeline row, and `DAY1_FULL_STOP` events include trigger, actual execution, share counts, and state transition.

## No-lookahead rules

`add_indicators` calculates daily MA and Wilder ATR, then explicitly shifts them. Every daily execution decision receives `reference_ma = MA.shift(1)` and `reference_atr = ATR.shift(1)`. Six-month bias sigma is computed from `daily_bias.shift(1).rolling(lookback)`, so day `t` is never included.

The single exception is break-protection reset. It is evaluated in the end-of-day callback only, with the now-completed `MA(t)` and `Low(t)`, and becomes actionable next trading day.

Warm-up data is requested before the user start date. Returned curves still begin at the first usable date inside the requested range.

## Execution assumptions

- Whole shares; initial quantity is `floor(current equity × allocation / actual buy cost including slippage and commission)`.
- Entry Zone v2 never buys when Open is above UpperEntry. An allowed Open inside the zone still fills at UpperEntry only after High reaches it; buy slippage then increases the execution price.
- Downward sell fill: stop level unless bar open already gapped below it, then open; sell slippage decreases price.
- Commission is charged independently for every execution.
- Scheduled next-open exit has highest priority, followed by protective stop, break-low exit, MA half-risk, entry, first TP, and extreme TP.
- Daily bars are processed in OPEN, INTRADAY RANGE, then CLOSE phases. Scheduled next-open exits and gap stops are processed before range events; volume/Day 2 validation and current-day-MA reset occur only at close.
- When one Daily OHLC bar permits both adverse and profitable paths but cannot reveal order, `DailyConservativeExecutionPolicy` chooses the adverse feasible event first and records `DAILY_INTRABAR_AMBIGUITY`. A same-day entry and risk threshold uses the feasible entry-then-adverse path.
- After an adverse trigger, favorable partial take-profits are suppressed for that day. This intentionally favors the worse feasible result when High/Low order is unknown.
- With `force_close_at_end=true`, remaining shares close at the last available daily close with `END_OF_BACKTEST`.

## Data providers and limitations

`DataProvider` exposes normalized timezone-aware daily OHLCV. `ProviderChain` is the application coordinator: it checks complete local cache first, then the preferred provider, then the other provider. The engine only receives one provider's complete frame and remains independent of Yahoo, Stooq, Polygon, Alpaca, CSV, or Parquet implementations.

The built-in providers are:

- **Yahoo Finance** (`query1` then `query2`): OHLC is adjusted using Yahoo's adjusted-close factor so split prices remain consistent; dividends are not modelled.
- **Stooq** (no-key alternative): daily CSV history with provider-native split adjustment semantics. It is cached under `CACHE_DIR/stooq`, separate from Yahoo, and is never merged with Yahoo bars.

The adjustment policy is part of cache metadata (`provider`, `adjustment_mode`, first/last date and last-updated timestamp). A cache fragment from one provider is never used as a fragment for the other provider. This avoids mixing adjusted, raw, or otherwise unknown corporate-action semantics. Dividend cash flows are intentionally ignored in this MVP, including in the buy-and-hold benchmark.

The application does not call Yahoo intraday endpoints. It downloads the requested period plus indicator warm-up as daily bars, enabling multi-year backtests. Daily OHLC cannot establish whether High or Low occurred first, so every result includes an explicit Daily OHLC conservative-execution warning. Neither provider should be treated as exchange-grade data.

Data Coverage reports Daily Bars, Warm-up Bars, First Strategy Date, Last Strategy Date, detectable missing trading days, provider, and `daily_conservative` execution model.

### Cache-first fallback and network resilience

Daily data is resolved in this order:

1. Read complete provider-isolated Parquet coverage. A complete cache never calls the network.
2. In Auto mode, try Yahoo (query1 then query2) and then Stooq. Selecting either provider changes preference but still permits fallback when it is unavailable.
3. Request only missing cache ranges; overlapping fragments are merged only inside the same provider namespace.
4. Retry transient connection, timeout, HTTP 429, and HTTP 5xx failures a finite number of times with exponential backoff. A known Yahoo outage enters a five-minute cooldown by default, so later backtests do not repeat the full host/retry sequence.
5. If a provider fails but its complete stale cache covers the request, use that cache and show its last-updated timestamp. An incomplete cache is never passed to the strategy engine.

Cache-backed results include `data_source`, provider, adjustment mode, cache coverage, and last-updated metadata. If all providers fail, the API returns one concise `MARKET_DATA_PROVIDERS_UNAVAILABLE` error with per-provider safe error codes (`NO_DATA`, `PROVIDER_CONNECTION_ERROR`, `PROVIDER_TIMEOUT`, `RATE_LIMITED`, or `CACHE_INCOMPLETE`); no credentials, cookies, server paths, or raw response bodies are returned to the browser.

`GET /api/data-provider/status` reports `{status, providers, preferred_provider, cache_available}`. Provider details include reachability, safe error type, cache availability, and cooldown state. From the backend directory, run `python -m scripts.diagnose_yahoo_network` for DNS, TCP 443, HTTPS, and redacted proxy-environment diagnostics. If this Windows environment blocks all outbound connections, approving the appropriate Private-network firewall policy is still required before an uncached ticker can use Yahoo or Stooq; the app does not create a proxy, tunnel, or bypass.

All internal frames require timezone-aware timestamps. A missing timezone returns a data-quality error.

## Metrics

- Daily strategy equity includes cash and marked-to-close shares; all executions include commission and slippage.
- Total return is final equity divided by initial capital minus one.
- CAGR uses elapsed calendar years.
- Sharpe uses daily equity returns, zero risk-free rate, and `sqrt(252)` annualization.
- Sortino uses negative daily-return deviation and `sqrt(252)` annualization.
- Maximum drawdown is `equity / running_max - 1`, with peak, bottom, and recovery dates.
- Calmar is CAGR divided by absolute maximum drawdown.
- Buy & hold starts on the strategy's first usable output day with the same initial capital.
- Position outcomes aggregate all partial sells; execution count remains separately available.
- `gross_pnl` is total sell execution value minus total buy execution value for the position. Actual execution prices already include slippage; gross PnL excludes all commissions.
- `net_pnl` / `realized_pnl` equal gross PnL less every buy and sell commission. `fees` reports their sum. Net cash accounting retains its original calculation order.
- Execution `slippage` and summary `estimated_slippage_cost` report raw-fill versus execution-fill costs separately. They must not be subtracted again from gross or net PnL. The Inspector also displays their position-level sum.
- Positions CSV and full JSON export these same stored values. History metrics and diagnostics continue to use net PnL and the existing equity curve.

To repair older persisted Gross PnL values, run `python -m scripts.repair_gross_pnl` from `backend` for a read-only preview, then add `--apply`. The command uses frozen executions (no data download or strategy replay), validates prices/shares/commissions/net PnL, backs up SQLite under `data/backups`, and atomically updates only `gross_pnl` in result positions and Inspector copies. A fingerprint check rejects any other field change. Running it again makes no further changes. Optional `--database` selects a local database; otherwise `DATABASE_URL` / `DATA_DIR` are respected.

## API

- `POST /api/backtests`
- `GET /api/backtests`
- `GET /api/backtests/{id}`
- `GET /api/backtests/{id}/positions/{position_id}/audit`
- `GET /api/backtests/{id}/diagnostics/day1-stop`
- `POST /api/backtests/{id}/diagnostics/ambiguity-sensitivity`
- `DELETE /api/backtests/{id}`
- `GET /api/health`
- `GET /health`
- `GET /api/data-provider/status`

The POST response contains the ID, summary, strategy and benchmark equity, drawdown, daily candles and MA, executions, positions, events, monthly returns, warnings, data coverage, and reproducibility metadata.

`POST /api/backtests` accepts `market_data_provider: "auto" | "yahoo" | "alternative"` (default `"auto"`). Auto checks complete local cache first, then prefers Yahoo and falls back to Stooq. The result's `data_coverage.data_provider`, `provider_display_name`, `adjustment_mode`, and `data_source` show exactly which isolated dataset was used.

## Trade Audit / Position Inspector

Every newly generated position has a stable `position_id` and a **View Details** action in the Trades tab. The inspector loads only after that action is selected; daily audit payloads are stored separately in SQLite's `position_audits` table and are not included in the normal backtest response.

The responsive drawer includes position PnL/fees/Q0 metadata, a candlestick window from 10 trading days before entry through 5 after exit, execution markers, MA, BreakDayLow, First TP and protective-stop overlays. Its daily timeline is backend-recorded and includes OHLCV, previous/current MA, previous ATR, completed bias sigma, open/close quantity and state, applicable strategy thresholds, Day 1 volume and Day 2 close validation, and execution-linked events. `DAILY_INTRABAR_AMBIGUITY` days are highlighted with the simultaneous conditions that caused the adverse-first decision.

Backtests saved before this feature do not contain audit snapshots. They remain readable, but must be rerun before **View Details** becomes available.

Validation cards require a matching event with `metadata.phase = "CLOSE"`.
A next-day `OPEN` execution may reuse `VOLUME_CONFIRMATION_FAIL` or
`DAY2_CLOSE_CONFIRMATION_FAIL` as its exit reason; it remains in the event and
execution logs but must not generate a new Day 1/Day 2 validation card. Unknown
timing is not inferred from the event name.

To repair old scheduled-exit validation cards, run from `backend`:

```bash
python -m scripts.repair_validation_audits          # read-only scan
python -m scripts.repair_validation_audits --apply  # back up and repair affected audits only
```

The repair reads existing event timing without downloading data or replaying
the engine. It preserves genuine CLOSE validations and changes only incorrect
validation fields in affected `position_audits`. It creates a SQLite backup in
`data/backups`, verifies every backtest/result field is byte-for-byte unchanged,
and rolls back on unexpected changes. The command respects `DATABASE_URL` /
`DATA_DIR`, or accepts an explicit `--database` path for local administration.

For completed `Advanced + Day1 3% Stop` runs, the **Diagnostic** tab lazily compares every `DAY1_FULL_STOP` with the latest compatible Existing Advanced backtest. Compatibility requires identical ticker, dates, capital, sizing, costs, execution settings, and all shared strategy parameters. The report shows entry-day OHLC/MA/stop/fill, 1/5/10/20-trading-day forward closes measured from the actual stop fill, ambiguity cohorts, every matched divergence, and the largest negative and positive position-PnL differences. Both sides link directly to their separately persisted Position Inspector records.

### Daily Intrabar Assumption Sensitivity

`execution_policy` defaults to `conservative`; old requests that omit it retain the original results. The Backtest Settings panel also offers `ohlc_heuristic` and `favorable`. These settings change only events whose order cannot be established from Daily OHLC:

- **Conservative:** adverse-first, including entry-then-stop when entry and a later adverse move are both feasible. This is the historical default.
- **OHLC Heuristic:** an up/flat candle assumes `Open → Low → High → Close`; a down candle assumes `Open → High → Low → Close`. This is explicitly a heuristic intraday path assumption, not observed market data.
- **Favorable:** chooses the favorable feasible order for an ambiguous daily bar. It does not ignore known opening gaps or stops on positions that already existed before the bar.

Open is always the first known price. Open equal to UpperEntry establishes the position at Open and a subsequent stop remains executable under every policy. Open above UpperEntry is always `ENTRY_ZONE_MISSED`; no policy may re-enter later that day. A pre-existing position that opens through a stop exits at Open under every policy.

Results display Execution Model, selected intrabar assumption, strategy version, ambiguous-day count, and ambiguous-position count. History labels pre-v2 records as **Legacy strategy version**. For `Advanced + Day1 3% Stop`, **Run Ambiguity Sensitivity** runs Advanced and Advanced + Day1 Stop across all three policies against one downloaded daily dataset. The six-row matrix includes positions, `ENTRY_ZONE_MISSED`, ambiguous positions, Day1 stops, return, CAGR, drawdown, and Sharpe, plus same-policy matched PnL/return deltas and the saved legacy chase analysis.

## Frontend workflow

Set ticker, dates, strategy, MA, thresholds, and transaction costs, then run. The fixed execution model is clearly shown as **Daily OHLC — Conservative**. Result tabs provide Overview, interactive stock chart, Trades, Events, Parameters, and History. Clicking an execution focuses the stock chart around its date. CSV exports are available for executions, positions, equity, and events; full JSON is also available.

Errors such as invalid/no ticker data, insufficient MA/bias warm-up, unavailable daily history, timezone mismatch, and no generated trades are rendered as visible application states instead of unhandled pages.

## Moving-average period optimization

The Traditional Chinese `/optimize` page provides a research tool for the MA period only. It supports the frozen Simple v2, Advanced v2, and Advanced + Day1 Stop strategies, while every non-MA strategy parameter remains fixed and visible. The range is defined by minimum, maximum, and step values and is rejected before execution if it would exceed 500 canonical backtests.

Each row calls the same production `BacktestEngine` used by the normal backtest page. Full executions, positions, events, equity, and position audits are persisted as ordinary backtests; the optimization job stores only summary rows and their backtest IDs. An optional chronological Train/Test mode selects the best MA exclusively from the Train results and evaluates that unchanged MA once on Test data.

The separate **rolling six-month** mode uses six calendar months (not 126 sessions) for each Train window, selects one MA using only that completed Train window, and fixes it for the following six-calendar-month Test window. The next pair uses the prior Test period as its new Train period. Every Test segment is an independent canonical backtest from flat; complete Test-segment returns may be geometrically chained for description, but that number is explicitly not continuous portfolio execution and no position is carried across a six-month boundary. A final incomplete Test period is marked provisional and excluded from the formal Test-only aggregate. Deterministic ties use the ranking metric, then higher after-cost total return, lower absolute maximum drawdown, and finally the smaller MA period. One user-selected fixed MA is evaluated over the same Test windows as a reference; it is never searched or optimized.

Optimization runs use durable background jobs. The page can be refreshed without losing progress, supports cancellation between canonical runs, and can reopen completed history. Result fingerprint caching is reused only when the exact request and the Daily OHLC data fingerprint are identical. The page includes sortable metrics, nearby-period stability diagnostics, an MA performance chart, comparison of up to five saved equity curves, and links to either open the exact full backtest or copy only that MA period into the ordinary backtest form. This is an analysis utility and does not modify any production strategy definition.

### MA_STRUCTURE_V1 rolling selection

Rolling optimization also exposes the explicit `selection_mode: "STRUCTURE_V1"`. It is available only for `rolling_6m`; the default remains `PERFORMANCE`, and the canonical BacktestEngine, strategies, execution, portfolio, and metrics are unchanged. Structure selection uses only numerical Train OHLC plus the required MA pre-roll. The frozen specification is versioned and included in every result as `structure_spec_version` and the SHA-256 `structure_spec_hash` (see `reports/MA_STRUCTURE_V1_IMPLEMENTATION_SPEC.md` and `backend/app/optimization/ma_structure_v1_spec.json`).

For each candidate MA, the analyzer records continuous above/below regimes, strict retests, fixed-threshold breakout/continuation states, and the next-session confirmation lifecycle. Structural gaps and canonical executable-entry outcomes are kept as separate annotations. Wilson 95% lower bounds, average-rank percentiles, equal 25% component weights, and the frozen deterministic tie-break select the Structure MA from Train only. A completed Test segment is then run independently from flat for both the unchanged Performance comparator and the Structure-selected MA; the user-selected fixed MA is evaluated on the same windows. `performance_aggregate`, `structure_aggregate`, `fixed_ma_aggregate`, and `structure_minus_performance` are retrospective out-of-sample comparisons, not a predictive claim or continuous portfolio simulation.

The result stores compact rankings and up to five Train artifacts. Numerical OHLC, MA reference values, and event markers remain in the dedicated artifact table and can be loaded through `GET /api/optimizations/{id}/structure/windows/{window_index}/candidates/{ma_period}`. Artifact reads require the matching frozen specification hash and a Top-5 candidate, so a changed specification cannot silently reuse old structural evidence. The `/optimize` page presents the selector, Chinese mobile labels, Train-only score/components/Wilson/count cards, and a numeric candlestick audit chart; it does not infer chart facts from raster images.

## Tests

```bash
cd backend
pytest -q
python -m scripts.validate_daily_history  # live Yahoo/API five-year smoke test
python -m scripts.validate_position_audits  # representative NVDA audit/log consistency check
```

```bash
cd frontend
npm test
npm run build
```

The backend suite includes the original strategy cases plus Entry Zone v2 boundaries across all strategies/policies, Daily execution, position-audit contracts, persistence, and end-to-end engine coverage. Frontend tests cover mobile layout, lazy audit loading, same-origin API use, LAN binding, version/diagnostic surfaces, daily-only errors, and responsive interaction; `npm run build` performs production type/build validation. `python -m scripts.validate_entry_zone_v2` persists and writes the real NVDA 3×3 validation report to `data/entry-zone-v2-validation.json`.

## Research Framework v2

Research Framework v2 separates future candidate research from the production backtest selector. See `reports/research-framework-v2.md`, the append-only registry at `data/research-candidate-registry.json`, the data fingerprint manifest at `data/research-framework-v2-data-manifest.json`, and the pre-result template at `research/templates/STRATEGY_SPEC.md`. The Traditional Chinese dashboard exposes the read-only framework at `/research`.

Simple v2 and Advanced v2 are frozen research baselines marked `REJECTED / NOT VALIDATED FOR FORWARD DEPLOYMENT`. M3 remains a rejected research-only baseline and is not registered as a production strategy. Future semantic or parameter changes require a new candidate ID; tested candidates are never overwritten or deleted.

### Research Environment Validation v3

Environment v3 keeps the prior eleven symbols under the explicit name `MEGA_CAP_TECH_UNIVERSE` and defines the separate `ETF_RESEARCH_UNIVERSE` (`SPY`, `QQQ`, `IWM`, `DIA`, `XLK`, `XLF`, `XLE`, `XLV`, `XLI`, `XLP`, `XLY`, `XLU`, `XLB`, `XLRE`). Neither list is represented as historical point-in-time constituent data. Research results from the two universes must remain separate.

The current validated cache begins on 2020-12-03, so the report at `reports/research-environment-v3.md` is explicitly marked `LONG-HISTORY VALIDATION UNAVAILABLE`. End users acquire and monitor real inputs entirely from the Traditional Chinese `/data` page. Provider checks, **補齊研究資料**, **下載／更新無風險利率**, progress, and retry/resume all execute inside the formal Windows backend.

New market files are isolated under `data/research-cache/<provider>/`; provider or adjustment bases are never combined. Each manifest records actual first/last dates, bar count, download time, Parquet checksum, normalized OHLCV checksum, validation, and adjustment contract. Failed downloads remain explicit and never create synthetic bars.

`CASH_RISK_FREE` uses only real FRED `DGS3MO` observations. An observation dated `t` is eligible only after `t`; the latest rate known by the previous research session compounds the cash balance using ACT/365. Invested stock value never receives cash yield simultaneously. If the series is unavailable, no rate manifest or risk-free result is generated.

Only after both market and rate readiness gates pass does `/research` enable **重新驗證研究環境**. Download completion never silently starts a research run.

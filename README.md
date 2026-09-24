# TokenWatcher

TokenWatcher is a lightweight Windows desktop overlay that displays a user-adjustable number of the most-used AI models, their exact token counts, each newly observed token increment, and cumulative standard-API-equivalent cost in USD. It reads local Codex, Claude Code, Cline, and DeepSeek Harness usage data, while using local Sub2API records only to resolve request aliases to their actual upstream model names. It refreshes the overlay every 0.25 seconds by default while using native Windows filesystem notifications for local log changes.

## Features

- Adjustable Top 1-10 models for today, this week, this month, or all time
- Exact token totals without K/M/B abbreviation
- Claude Code totals include input, output, cache-read, and cache-creation tokens
- A temporary green `+Token` value showing the exact newly observed increment
- Per-model request counts
- Request-count column sized for grouped seven-digit counts without reducing text size
- Platform-colored model badges without a separate platform-name column
- Per-model official API-equivalent USD cost with prices re-verified on 2026-08-27 and a green rolling animation when it increases
- Versioned OpenAI 5.6 prices, DeepSeek UTC peak/off-peak pricing, OpenAI/xAI per-request long-context tiers, prompt-cache components, deterministic model aliases, and explicit `—` for unpriced internal/unknown models
- User-adjustable 70%-140% interface scale, persisted between launches
- Bottom `增加列` and `减少列` controls with a persisted row count and matching window height
- Right-click row controls and a persisted 0.1/0.25/0.5/1/2-second refresh selector
- Event-driven log discovery, byte/frame-offset tailing, and cached summary/task files
- DeepSeek Harness session accounting with per-step usage replacement, fork seed deduplication, and Zstandard-frame tailing
- Persistent sub2api `usage_logs.id` high-water mark for incremental model-mapping discovery
- Automatic one-pass reconciliation after Windows notification-buffer loss; a 30-second discovery fallback is used only while native notifications are unavailable
- Codex cumulative-snapshot deduplication across continued, forked, and subagent tasks; replayed parent history is deduplicated by lineage, and missing `turn_context` models are inherited automatically
- Persistent Codex fingerprint/offset cache for fast restarts
- Immediate startup display from the last verified aggregate snapshot; live sources reconcile it in the background
- Field-level adaptive pure-color text: every text field uses one crisp black or white foreground while the overlay remains transparent
- Overlay remains visible in normal system screenshots while background contrast sampling runs
- Green rolling animation when a value increases
- Transparent, always-on-top, draggable window
- Automatic black/white selection based on the background directly behind each text field
- Flicker-free double-buffered text-layer replacement during background updates
- Large, borderless typography sized for high-DPI desktop displays
- Temporary manual-black text override
- Single-instance protection
- No telemetry or data upload

## Supported local data sources

- Codex: `~/.codex/sessions` and `~/.codex/archived_sessions`
- Claude Code: `~/.claude/stats-cache.json` and `~/.claude/projects`
- Cline: VS Code's `saoudrizwan.claude-dev` global storage
- DeepSeek Harness: `$DSH_HOME/sessions` (normally `~/.dsh/sessions`)
- Sub2API model mapping: `requested_model`/`model` to `upstream_model` in the local PostgreSQL `usage_logs` table

TokenWatcher only reads these local sources. It does not send usage records anywhere. DSH session discovery can be overridden with `TOKENWATCHER_DSH_SESSIONS`; sub2api is discovered at `D:\software\sub2api` by default, and custom installations can set `TOKENWATCHER_SUB2API_ROOT`, `TOKENWATCHER_SUB2API_CONFIG`, or `TOKENWATCHER_SUB2API_PSQL`. Sub2API is mapping-only: its token, call, and cost aggregates are never added to the final snapshot, so a request already present in a local Codex or DSH log is not counted twice. The official pricing matrix and source links are recorded in `docs/PRICING_AUDIT_2026-08-27.md`. Cost is computed per request before aggregation: DeepSeek's current peak schedule uses UTC weekdays `[01:00,04:00)` and `[06:00,10:00)`, while xAI Grok 4.5 enters its higher context band at an inclusive 200K prompt tokens. TokenWatcher never substitutes a similar model when an exact official price cannot be verified. The optional OpenAI Sol promotional rate is applied only inside its officially guaranteed window (from 2026-08-21 through 2026-11-21) and only when the event time is known; report totals always use the non-promotional standard-equivalent basis.

## Run from source

Requires Python 3.10 or later on Windows.

```powershell
python -m pip install -r requirements.txt
python src/token_watcher.py
```

Right-click the overlay to switch the time period, open an optional full report, or exit. Drag the overlay with the left mouse button.

## Optional baseline report

TokenWatcher can run without a generated report. If a compatible report already exists, point the app to the directory containing the token CSVs plus `model_cost.csv`, `daily_cost_by_platform_model.csv`, and `pricing_used.csv`:

```powershell
$env:AI_USAGE_REPORT_DIR = 'D:\path\to\report'
python src/token_watcher.py
```

Or pass it directly:

```powershell
python src/token_watcher.py --report-dir 'D:\path\to\report'
```

## Build the Windows executable

```powershell
python -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

The build writes `TokenWatcher.exe` plus the adjacent `TokenWatcher.runtime` directory for local use, and creates the atomic `TokenWatcher-windows.zip` package with `TokenWatcher-windows.zip.sha256`. The small root executable launches the reusable runtime without unpacking the Python application on every start. Set `TOKENWATCHER_SIGN_CERT_SHA1` to an installed Authenticode certificate thumbprint to sign both executable entry points before packaging; unsigned builds still receive a SHA-256 checksum.

## Diagnostics

Print a JSON snapshot, or write one atomically to an explicit path (recommended for the packaged windowed executable):

```powershell
python src/token_watcher.py --snapshot-json
.\TokenWatcher.exe --snapshot-json .\snapshot.json
```

Run the built-in data-source check. Success means collection completed without an engine error; it does not require three installed models:

```powershell
python src/token_watcher.py --self-test
```

## Privacy

The repository intentionally excludes local usage reports, logs, generated screenshots, build output, and executables. Review the source before running it if your local AI usage data is sensitive.

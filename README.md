# TokenWatcher

TokenWatcher is a lightweight Windows desktop overlay that displays a user-adjustable number of the most-used AI models, their exact token counts, each newly observed token increment, and cumulative standard-API-equivalent cost in USD. It reads local Codex, Claude Code, Cline, and DeepSeek API usage data and refreshes the overlay every 0.25 seconds by default while using native Windows filesystem notifications for local log changes.

## Features

- Adjustable Top 1-10 models for today, this week, this month, or all time
- Exact token totals without K/M/B abbreviation
- Claude Code totals include input, output, cache-read, and cache-creation tokens
- A temporary green `+Token` value showing the exact newly observed increment
- Per-model request counts
- Platform-colored model badges without a separate platform-name column
- Per-model USD cost with a green rolling animation when it increases
- User-adjustable 70%-140% interface scale, persisted between launches
- Bottom `增加列` and `减少列` controls with a persisted row count and matching window height
- Right-click row controls and a persisted 0.1/0.25/0.5/1/2-second refresh selector
- Event-driven log discovery, incremental tailing, and cached summary/task files
- Automatic one-pass reconciliation after Windows notification-buffer loss; a 30-second discovery fallback is used only while native notifications are unavailable
- Codex cumulative-snapshot deduplication across continued, forked, and subagent tasks; replayed parent history is deduplicated by lineage, and missing `turn_context` models are inherited automatically
- Persistent Codex fingerprint/offset cache for fast restarts
- Immediate startup display from the last verified aggregate snapshot; live sources reconcile it in the background
- Field-level adaptive pure-color text: every text field uses one crisp black or white foreground while the overlay remains transparent
- Green rolling animation when a value increases
- Transparent, always-on-top, draggable window
- Automatic black/white selection based on the background directly behind each text field
- Flicker-free double-buffered text-layer replacement during background updates
- Large, borderless typography sized for high-DPI desktop displays
- Manual black/white text toggle
- Single-instance protection
- No telemetry or data upload

## Supported local data sources

- Codex: `~/.codex/sessions` and `~/.codex/archived_sessions`
- Claude Code: `~/.claude/stats-cache.json` and `~/.claude/projects`
- Cline: VS Code's `saoudrizwan.claude-dev` global storage
- DeepSeek API: DeepSeek model rows in the local sub2api PostgreSQL `usage_logs` table

TokenWatcher only reads these local sources. It does not send usage records anywhere. By default, sub2api is discovered at `D:\software\sub2api`; custom installations can set `TOKENWATCHER_SUB2API_ROOT`, `TOKENWATCHER_SUB2API_CONFIG`, or `TOKENWATCHER_SUB2API_PSQL`.

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

The fast-start package is written to `TokenWatcher.exe` plus the adjacent
`TokenWatcher.runtime` directory. Keep them together when moving or distributing
the app. The small root executable launches the reusable runtime without unpacking
the Python application again on every start.

## Diagnostics

Print a JSON snapshot:

```powershell
python src/token_watcher.py --snapshot-json
```

Run the built-in data-source check:

```powershell
python src/token_watcher.py --self-test
```

## Privacy

The repository intentionally excludes local usage reports, logs, generated screenshots, build output, and executables. Review the source before running it if your local AI usage data is sensitive.

# Usage notes

## Overlay controls

- Left-drag: move the window.
- Click a period: switch between today, week, month, and cumulative usage.
- Click the bottom-left button: temporarily force black text; click again to restore automatic black/white selection.
- Click `增加列` or `减少列`: show one more or one fewer ranked model (1-10 rows).
- Right-click: open the period/report menu, add or remove rows, or select a 0.1/0.25/0.5/1/2-second refresh interval.

## Refresh behavior

The overlay updates every 0.25 seconds by default. The right-click `调整刷新时间` submenu changes both background collection and screen refresh together, persists the choice, and offers 0.1/0.25/0.5/1/2 seconds. At startup, the data engine performs one bounded discovery inside the known Codex, Claude Code, Cline, and `$DSH_HOME/sessions` roots. During runtime native Windows directory-change notifications identify created or modified logs; Codex, Claude, and raw DSH JSONL are read only after their cached byte offsets, while compressed DSH logs advance only across complete checksummed Zstandard frames. Cold files are not periodically enumerated or checked. Notification-buffer loss triggers one explicit reconciliation of the affected source, and a 30-second bounded discovery fallback runs only while native notifications are unavailable. A notified equal-size rewrite, file replacement, shrink, or deletion triggers one source reconciliation rather than changing normal append behavior. Codex token events are deduplicated by root fork/subagent lineage plus cumulative usage snapshot. DSH usage uses final-sample-wins semantics per `(session lifecycle, turn, step)` and ignores inherited `seq < seedLength` history in fork/subagent logs. Claude/Cline summary JSON is reparsed only when metadata changes. Sub2API polling uses a persisted `usage_logs.id` cursor only to discover request-to-upstream model mappings; its token, call, and cost aggregates are excluded from the final snapshot, preventing a local Codex/DSH request from being counted twice. When a model's token count, request count, or USD cost increases, the previous value rolls upward and the new value briefly appears in green. A separate green `+Token` field remains visible for 1.6 seconds and shows the exact increment detected by that refresh.

Each row begins with a platform-colored model badge such as `5.6-sol` or `opus-4.8`; the redundant `Codex`/`Claude` text column is intentionally omitted. The request-count column keeps its existing font size and accommodates grouped counts through `9,999,999`. The final column is cumulative official API equivalent cost in USD for the selected period. Prices were re-verified on 2026-08-27; the complete matrix and official links are in `PRICING_AUDIT_2026-08-27.md`. DeepSeek is priced by event timestamp using its UTC peak/off-peak schedule, and OpenAI/xAI long-context rates are selected per request rather than from a daily total. Exact aliases are deterministic; models without a verified public price display `—` instead of a misleading zero. The optional OpenAI Sol promotional rate is applied only inside its officially guaranteed window (2026-08-21 through 2026-11-21) and only for events with a known timestamp; reports keep the non-promotional standard-equivalent basis. Cline Coding Plan's recorded charge remains separately disclosed as zero while its GLM standard API equivalent cost is calculated independently and the subscription amount remains unknown.

The overlay keeps every non-badge area transparent. Each normal text field is rendered with one crisp antialiased pure color: automatic mode samples the background behind that field and selects either pure black or pure white for the best overall contrast. A single character no longer changes color internally. Windows background capture uses the physical window rectangle so the choice remains correct on secondary high-DPI displays. The temporary capture exclusion used for this sampling is cleared immediately after the sample, so normal Windows screenshots include the overlay. Background updates prepare all new text layers in memory and replace them without hiding the current layers, preventing refresh flicker. Growing token, request-count, and cost values roll upward in green. Click the `自动` indicator only when a temporary manual black override is needed; click it again to resume automatic mode.

The overlay is intentionally borderless. Any line, color band, wallpaper, or window visible between the text fields belongs to the desktop underneath the transparent overlay; only the text and colored model badges are drawn by TokenWatcher.

To adjust the complete overlay size, right-click anywhere and choose `缩小界面`, `放大界面`, or `恢复默认大小`. `Ctrl + mouse wheel` provides the same 5% stepping. The selected 70%-140% scale, 1-10 row count, and refresh interval are saved in `~/.tokenwatcher/ui_settings.json` and restored on the next launch; all row fonts, columns, gaps, and the window resize together.

TokenWatcher persists Codex fingerprints, per-file offsets, session lineage, and parser state in `~/.tokenwatcher/codex_fingerprint_cache.json`. On later starts, unchanged JSONL files are verified by size and modification time but are not opened. New or appended files are read only from the cached byte offset. If the cache is missing, invalid, or from an incompatible version, it is rebuilt automatically from local history.

Claude token totals include input, output, cache-read, and cache-creation tokens. The cumulative baseline comes from `stats-cache.json`; cache tokens for active calendar periods and all usage after the latest actual `dailyModelTokens` date are reconciled from project JSONL. Token deltas and request counts share one parser pass. Its offsets, compact fingerprints, and aggregate deltas are persisted in `~/.tokenwatcher/claude_tail_cache.json`, so unchanged project logs are metadata-checked but not reopened on normal restarts.

DeepSeek Harness file offsets, complete-frame boundaries, routes, fork metadata, and last usage sample per step are stored in `~/.tokenwatcher/dsh_tail_cache.json`. The sub2api cache stores discovered model aliases and the monotonic database cursor in `~/.tokenwatcher/sub2api_usage_cache.json`; it does not serve as a second token-count source. A pricing-schema change performs one controlled cache rebuild from the database and atomically commits the new cursor and mappings together; after that, normal polling resumes strict `id > cursor` queries. The 2026-08-27 pricing verification additionally performed one controlled DSH tail-cache rebuild (version 5): on the next startup it re-reads the known DeepSeek Harness session root once from offset 0 and persists fresh offsets, then normal runtime stays strictly incremental. It never turns normal runtime into a disk scan. Unknown-price models retain token and call totals while showing `—` cost.

The last verified aggregate values are stored separately in `~/.tokenwatcher/usage_snapshot_cache.json`. This small file is tied to the resolved baseline-report directory and loaded before the overlay is shown, so token totals appear immediately while the incremental trackers reconcile newer events in the background. It is written after the first completed background refresh and on a clean exit only when totals changed; the configurable UI refresh loop does not write it.

The overlay remains hidden until cached totals have been painted. If the snapshot cache is missing or invalid, TokenWatcher uses the small baseline report as an immediate preview instead of showing a visible waiting state while local log trackers initialize.

## Data lookup order

An optional generated baseline report is resolved in this order:

1. The `--report-dir` command-line option.
2. The `AI_USAGE_REPORT_DIR` environment variable.
3. `outputs/codex_claude_usage_since_2026-02` beside the source or executable.
4. `~/.tokenwatcher/codex_claude_usage_since_2026-02`.

If no report exists, TokenWatcher starts with an empty baseline and reconstructs available usage from local Codex, Claude Code, Cline, and DeepSeek Harness sources; Sub2API is consulted only for model-name mapping.

## Limitations

- Only locally available logs are counted.
- Deleted, remote-only, or unsynchronized sessions cannot be recovered.
- Claude Code cache-inclusive totals depend on the locally retained `stats-cache.json` and project JSONL history.
- Cline paths currently follow the standard VS Code extension storage location on Windows.
- DeepSeek Harness history depends on retained session artifacts. Sub2API mapping data can rename a locally observed request but cannot reconstruct missing usage.

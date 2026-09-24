from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

PERIODS = ("today", "week", "month", "cumulative")
SHANGHAI = timezone(timedelta(hours=8))
CACHE_VERSION = 6
PRICING_SCHEMA_REVISION = "2026-09-05-gpt6"
POLL_SECONDS = 5.0
MAX_VALUE = (1 << 63) - 1


def _empty_periods() -> dict[str, Counter]:
    return {period: Counter() for period in PERIODS}


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} is not an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError(f"{name} is not an integer")
    if parsed < 0 or parsed > MAX_VALUE:
        raise ValueError(f"{name} is outside the supported range")
    return parsed


def _strip_inline_comment(value: str) -> str:
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in "\"'":
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
            continue
        if character == "#" and not quote and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    if quote:
        raise ValueError("unterminated quoted database value")
    return value.strip()


def _load_database_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    in_database = False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        if not in_database:
            if re.fullmatch(r"database\s*:\s*", raw_line):
                in_database = True
            continue
        if raw_line and not raw_line[0].isspace():
            break
        match = re.match(
            r"^\s+(host|port|user|password|dbname)\s*:\s*(.*?)\s*$",
            raw_line,
        )
        if match is None:
            continue
        value = _strip_inline_comment(match.group(2))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[match.group(1)] = value
    missing = [name for name in ("host", "port", "user", "dbname") if not values.get(name)]
    if missing:
        raise ValueError(f"sub2api database config missing: {', '.join(missing)}")
    return values


class Sub2ApiUsagePoller:
    """Incrementally discover model mappings from local Sub2API usage-log ids."""

    QUERY_TEMPLATE = """
WITH new_rows AS MATERIALIZED (
    SELECT id, requested_model, model, upstream_model
    FROM usage_logs
    WHERE id > {cursor}
)
SELECT '__mapping__', requested_model, upstream_model, 'current', 0,
       0, 0, 0, 0, 0, id, ''
FROM (
    SELECT
        COALESCE(
            NULLIF(TRIM(requested_model), ''),
            NULLIF(TRIM(model), '')
        ) AS requested_model,
        NULLIF(TRIM(upstream_model), '') AS upstream_model,
        id
    FROM new_rows
    WHERE COALESCE(
              NULLIF(TRIM(upstream_model), ''),
              ''
          ) <> ''
      AND COALESCE(
              NULLIF(TRIM(requested_model), ''),
              NULLIF(TRIM(model), '')
          ) <> ''
      AND LOWER(
              COALESCE(
                  NULLIF(TRIM(requested_model), ''),
                  NULLIF(TRIM(model), '')
              )
          ) <> LOWER(NULLIF(TRIM(upstream_model), ''))
) AS model_mappings
UNION ALL
SELECT '__cursor__', '', '1970-01-01', 'current', 0,
       0, 0, 0, 0, 0,
       COALESCE((SELECT MAX(id) FROM new_rows), {cursor}), ''
ORDER BY 11;
""".strip()

    def __init__(
        self,
        config_path: Path,
        psql_path: Path,
        *,
        runner=None,
        prices: dict[str, dict[str, float]] | None = None,
        cache_path: Path | None = None,
        config_loader: Callable[[Path], dict[str, str]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.psql_path = Path(psql_path)
        self.runner = runner or subprocess.run
        self.cache_path = cache_path or Path.home() / ".tokenwatcher" / "sub2api_usage_cache.json"
        self.config_loader = config_loader or _load_database_config
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self.periods = _empty_periods()
        self.call_periods = _empty_periods()
        self.cost_periods = _empty_periods()
        self.dsh_periods = _empty_periods()
        self.dsh_call_periods = _empty_periods()
        self.dsh_cost_periods = _empty_periods()
        self.status = "sub2api 正在载入"
        self.next_check = 0.0
        self.cursor = 0
        self.model_aliases: dict[str, str] = {}
        self.cache_errors = 0
        self._cache_source = ""
        self._cache_loaded = False
        self._cache_dirty = False
        self.poll(force=True)

    @property
    def query(self) -> str:
        return self.QUERY_TEMPLATE.format(cursor=self.cursor)

    # Compatibility for diagnostics/tests that inspect the query text.
    @property
    def QUERY(self) -> str:  # noqa: N802 - historical public diagnostic name
        return self.query

    def _source_key(self, config: dict[str, str]) -> str:
        return json.dumps(
            {
                "config": str(self.config_path.resolve()),
                "psql": str(self.psql_path.resolve()),
                "host": config["host"],
                "port": config["port"],
                "user": config["user"],
                "dbname": config["dbname"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _load_cache(self, source: str) -> None:
        self._cache_loaded = True
        self._cache_source = source
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if int(payload.get("version") or 0) != CACHE_VERSION:
                return
            if str(payload.get("source") or "") != source:
                return
            cursor = _nonnegative_int(payload.get("cursor") or 0, "cursor")
            if str(payload.get("pricing_schema_revision") or "") != PRICING_SCHEMA_REVISION:
                return
            aliases = payload.get("model_aliases") or {}
            if not isinstance(aliases, dict):
                raise ValueError("model aliases cache is not an object")
            model_aliases = {
                str(alias).strip().casefold(): str(upstream).strip()
                for alias, upstream in aliases.items()
                if str(alias).strip() and str(upstream).strip()
            }
            self.cursor = cursor
            self.model_aliases = model_aliases
        except FileNotFoundError:
            return
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.cache_errors += 1
            self.cursor = 0
            self.model_aliases = {}

    def _save_cache(self) -> None:
        if not self._cache_dirty:
            return
        payload = {
            "version": CACHE_VERSION,
            "source": self._cache_source,
            "pricing_schema_revision": PRICING_SCHEMA_REVISION,
            "cursor": self.cursor,
            "saved_at": self.now().isoformat(),
            "model_aliases": dict(sorted(self.model_aliases.items())),
        }
        temporary = self.cache_path.with_name(f"{self.cache_path.name}.{os.getpid()}.tmp")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self.cache_path)
            self._cache_dirty = False
        except OSError:
            self.cache_errors += 1
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _command(self, config: dict[str, str]) -> list[str]:
        return [
            str(self.psql_path),
            "-X",
            "-w",
            "-h",
            config["host"],
            "-p",
            config["port"],
            "-U",
            config["user"],
            "-d",
            config["dbname"],
            "-At",
            "-F",
            "\t",
            "-c",
            self.query,
        ]

    def _merge_output(self, output: str) -> bool:
        next_cursor = self.cursor
        mappings_changed = False
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t", 11)
            if len(fields) != 12:
                raise ValueError("unexpected sub2api query output")
            (
                platform,
                model,
                day_text,
                pricing_bucket,
                long_context_text,
                input_text,
                output_text,
                cache_write_text,
                cache_read_text,
                calls_text,
                max_id_text,
                latest_text,
            ) = fields
            max_id = _nonnegative_int(max_id_text, "max_id")
            next_cursor = max(next_cursor, max_id)
            if platform == "__mapping__":
                requested_model = str(model).strip()
                upstream_model = str(day_text).strip()
                if requested_model and upstream_model:
                    alias_key = requested_model.casefold()
                    if self.model_aliases.get(alias_key) != upstream_model:
                        self.model_aliases[alias_key] = upstream_model
                        mappings_changed = True
                continue
            if platform == "__cursor__":
                continue
            raise ValueError("Sub2API returned non-mapping usage data")
        changed = next_cursor != self.cursor
        self.cursor = next_cursor
        if changed or mappings_changed:
            self._cache_dirty = True
        self.status = (
            f"sub2api：模型映射 {len(self.model_aliases)} 条"
            "（usage_logs 仅作映射来源）"
        )
        return changed or mappings_changed

    def resolve_model(self, model: str) -> str:
        """Resolve a local request alias to Sub2API's actual upstream model."""
        raw = str(model or "").strip()
        if not raw:
            return raw
        return self.model_aliases.get(raw.casefold(), raw)

    def poll(self, force: bool = False) -> None:
        monotonic_now = time.monotonic()
        if not force and monotonic_now < self.next_check:
            return
        self.next_check = monotonic_now + POLL_SECONDS
        try:
            if not self.config_path.is_file() or not self.psql_path.is_file():
                self.status = "sub2api：未检测到本地服务"
                return
            config = self.config_loader(self.config_path)
            source = self._source_key(config)
            if not self._cache_loaded:
                self._load_cache(source)
            elif source != self._cache_source:
                self.cursor = 0
                self.model_aliases = {}
                self._cache_source = source
                self._cache_dirty = True
            environment = dict(os.environ)
            environment["PGPASSWORD"] = config.get("password", "")
            result = self.runner(
                self._command(config),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10.0 if self.cursor == 0 else 3.0,
                check=False,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                self.status = f"sub2api：查询失败 ({result.returncode})，保留上次数据"
                return
            self._merge_output(result.stdout)
            self._save_cache()
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            detail = re.sub(r"\s+", " ", str(exc)).strip()[:120]
            self.status = f"sub2api：{type(exc).__name__} ({detail})，保留上次数据"

    def roll_periods(self, _previous_date: date, _current_date: date) -> None:
        self.next_check = 0.0

    def close(self) -> None:
        self._save_cache()


__all__ = ["Sub2ApiUsagePoller"]

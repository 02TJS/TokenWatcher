from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from model_pricing import usage_cost_usd

try:
    import zstandard as _zstandard  # type: ignore
except ImportError:  # Node fallback remains available for source checkouts.
    _zstandard = None

PERIODS = ("today", "week", "month", "cumulative")
SHANGHAI = timezone(timedelta(hours=8))
LONG_CONTEXT_THRESHOLD = 272_000
# 2026-08-27 价格核验将 deepseek-v4-flash-vision-exp / deepseek-v4-pro-0813
# 纳入官方定价后，DSH 缓存版本 5 触发一次受控重建：启动时在已知 DSH 会话
# 根目录内从偏移 0 重新读取一次并持久化新偏移（与 sub2api v3 迁移同规则），
# 此后正常轮询仍严格增量，绝不对整个磁盘扫描。
CACHE_VERSION = 5
PLATFORM = "DeepSeek Harness"
SESSION_LOG_NAMES = (
    "session.jsonl",
    "session.jsonl.zstd",
    "session.v4.jsonl",
    "session.v4.jsonl.zstd",
)
DEFAULT_SINCE = datetime(2026, 2, 1, tzinfo=SHANGHAI)
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SKIPPABLE_MIN = 0x184D2A50
SKIPPABLE_MAX = 0x184D2A5F


def _default_root() -> Path:
    configured = os.environ.get("TOKENWATCHER_DSH_SESSIONS")
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))).expanduser() / "sessions"


def _empty_periods() -> dict[str, Counter]:
    return {name: Counter() for name in PERIODS}


def _active_periods(event_date: date, now_date: date) -> tuple[str, ...]:
    result = ["cumulative"]
    if (event_date.year, event_date.month) == (now_date.year, now_date.month):
        result.append("month")
    week_start = now_date - timedelta(days=now_date.weekday())
    if week_start <= event_date <= now_date:
        result.append("week")
    if event_date == now_date:
        result.append("today")
    return tuple(result)


def _parse_time(value: object) -> datetime:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean usage")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("non-integral usage")
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValueError("invalid usage")
    if number < 0 or number > (1 << 63) - 1:
        raise ValueError("invalid usage")
    return number


def _usage(raw: object) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    aliases = {
        "input": ("inputTokens", "input_tokens", "input"),
        "output": ("outputTokens", "output_tokens", "output"),
        "cacheRead": ("cacheReadTokens", "cache_read_input_tokens", "cacheRead", "cachedTokens"),
        "cacheWrite": ("cacheWriteTokens", "cache_creation_input_tokens", "cacheWrite"),
    }
    result: dict[str, int] = {}
    try:
        for target, names in aliases.items():
            result[target] = _int(next((raw[name] for name in names if name in raw), 0) or 0)
    except (ValueError, TypeError, OverflowError):
        return None
    return result


def _route(raw: object) -> tuple[str, str] | None:
    if not isinstance(raw, dict):
        return None
    provider = raw.get("provider") or raw.get("providerId") or raw.get("apiProvider")
    model = raw.get("model") or raw.get("modelId")
    if isinstance(model, dict):
        provider = provider or model.get("provider")
        model = model.get("id") or model.get("name")
    if provider and model:
        return str(provider), str(model)
    return None


def _event_type(event: dict) -> str:
    return str(event.get("type") or event.get("event") or event.get("kind") or "")


def _identity(stat_result: os.stat_result) -> dict[str, int]:
    return {
        "dev": int(getattr(stat_result, "st_dev", 0)),
        "ino": int(getattr(stat_result, "st_ino", 0)),
        "ctime_ns": int(getattr(stat_result, "st_ctime_ns", int(stat_result.st_ctime * 1e9))),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1e9))),
        "size": int(stat_result.st_size),
    }


def _same_file(old: dict, new: dict) -> bool:
    if old.get("dev") != new.get("dev"):
        return False
    if old.get("ino") and new.get("ino"):
        return old.get("ino") == new.get("ino")
    return old.get("ctime_ns") == new.get("ctime_ns")


def _frame_length(data: bytes, start: int = 0) -> int | None:
    """Return one complete Zstd/skippable frame length, None for an incomplete frame.

    The parser performs only structural framing; checksum validation belongs to the decoder.
    """
    if len(data) - start < 4:
        return None
    magic = int.from_bytes(data[start : start + 4], "little")
    if SKIPPABLE_MIN <= magic <= SKIPPABLE_MAX:
        if len(data) - start < 8:
            return None
        length = 8 + int.from_bytes(data[start + 4 : start + 8], "little")
        return length if len(data) - start >= length else None
    if data[start : start + 4] != ZSTD_MAGIC:
        raise ValueError("invalid Zstd magic")
    pos = start + 4
    if pos >= len(data):
        return None
    descriptor = data[pos]
    pos += 1
    if descriptor & 0x18:
        raise ValueError("reserved Zstd frame-header bit")
    fcs_flag = descriptor >> 6
    single_segment = bool(descriptor & 0x20)
    checksum = bool(descriptor & 0x04)
    dictionary_flag = descriptor & 0x03
    if not single_segment:
        if pos >= len(data):
            return None
        pos += 1
    dictionary_size = (0, 1, 2, 4)[dictionary_flag]
    fcs_size = (1 if single_segment else 0, 2, 4, 8)[fcs_flag]
    if pos + dictionary_size + fcs_size > len(data):
        return None
    pos += dictionary_size + fcs_size
    while True:
        if pos + 3 > len(data):
            return None
        header = int.from_bytes(data[pos : pos + 3], "little")
        pos += 3
        last = header & 1
        block_type = (header >> 1) & 3
        block_size = header >> 3
        if block_type == 3:
            raise ValueError("reserved Zstd block type")
        payload_size = 1 if block_type == 1 else block_size
        if pos + payload_size > len(data):
            return None
        pos += payload_size
        if last:
            break
    if checksum:
        if pos + 4 > len(data):
            return None
        pos += 4
    return pos - start


class DshTailTracker:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        watcher=None,
        cache_path: str | Path | None = None,
        prices: dict[str, dict[str, float]] | None = None,
        frame_decoder: Callable[[bytes], bytes] | None = None,
        node_runner: Callable[[bytes], bytes] | None = None,
        excluded_providers: Iterable[str] = (),
        include_promotions: bool = True,
        since: datetime = DEFAULT_SINCE,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else _default_root().resolve()
        self.watcher = watcher
        self.cache_path = Path(cache_path).expanduser() if cache_path else Path.home() / ".tokenwatcher" / "dsh_tail_cache.json"
        self.prices = prices or {}
        self.frame_decoder = frame_decoder
        self.node_runner = node_runner
        self.excluded_providers = {
            str(provider).casefold() for provider in excluded_providers
        }
        self.include_promotions = bool(include_promotions)
        self.since = (
            since if since.tzinfo is not None else since.replace(tzinfo=SHANGHAI)
        ).astimezone(timezone.utc)
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self.periods = _empty_periods()
        self.call_periods = _empty_periods()
        self.cost_periods = _empty_periods()
        self.last_event: datetime | None = None
        self.errors = 0
        self.cache_errors = 0
        self.status = "starting"
        self._files: dict[str, dict] = {}
        self._last_reconcile = 0.0
        self._load_cache()
        self._reconcile()
        self.status = "watching" if watcher is not None and bool(getattr(watcher, "available", False)) else "polling"

    def _known_paths(self) -> set[Path]:
        if not self.root.is_dir():
            return set()
        found: set[Path] = set()
        try:
            for first in self.root.iterdir():
                if not first.is_dir():
                    continue
                for second in first.iterdir():
                    if not second.is_dir():
                        continue
                    for name in SESSION_LOG_NAMES:
                        path = second / name
                        if path.is_file():
                            found.add(path.resolve())
        except OSError:
            self.errors += 1
        return found

    def _allowed(self, path: Path) -> Path | None:
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(self.root)
        except (OSError, ValueError):
            return None
        if len(relative.parts) == 3 and relative.parts[-1] in SESSION_LOG_NAMES:
            return resolved
        return None

    def poll(self) -> None:
        paths: set[Path] = set()
        reconcile = False
        if self.watcher is not None and bool(getattr(self.watcher, "available", False)):
            try:
                reconcile = bool(self.watcher.consume_resync_required())
                paths.update(Path(value) for value in self.watcher.drain())
            except Exception:
                self.errors += 1
                reconcile = True
        elif time.monotonic() - self._last_reconcile >= 30.0:
            reconcile = True
        if reconcile:
            self._reconcile()
            return
        changed = False
        for path in paths:
            allowed = self._allowed(path)
            if allowed is not None:
                changed |= self._refresh(allowed)
        if changed:
            self._rebuild()
            self._save_cache()

    def close(self) -> None:
        self._save_cache()
        if self.watcher is not None:
            try:
                self.watcher.close()
            except Exception:
                self.errors += 1
        self.status = "closed"

    def roll_periods(self, previous_date: date, current_date: date) -> tuple[str, ...]:
        if current_date <= previous_date:
            return ()
        reset = ["today"]
        if previous_date.isocalendar()[:2] != current_date.isocalendar()[:2]:
            reset.append("week")
        if (previous_date.year, previous_date.month) != (current_date.year, current_date.month):
            reset.append("month")
        self._rebuild()
        return tuple(reset)

    def _reconcile(self) -> None:
        self._last_reconcile = time.monotonic()
        discovered = self._known_paths()
        changed = False
        for key in set(self._files) - {str(path) for path in discovered}:
            del self._files[key]
            changed = True
        for path in discovered:
            changed |= self._refresh(path)
        if changed:
            self._rebuild()
            self._save_cache()
        else:
            self._rebuild()

    def _refresh(self, path: Path) -> bool:
        key = str(path)
        try:
            stat_result = path.stat()
        except OSError:
            if key in self._files:
                del self._files[key]
                return True
            return False
        current = _identity(stat_result)
        previous = self._files.get(key)
        state = json.loads(json.dumps(previous)) if previous is not None else None
        if state and _same_file(state.get("identity", {}), current):
            old_size = int(state.get("identity", {}).get("size", 0))
            old_mtime = int(state.get("identity", {}).get("mtime_ns", 0))
            if current["size"] == old_size and current["mtime_ns"] == old_mtime:
                return False
            append = current["size"] > old_size and int(state.get("offset", 0)) <= old_size
            if not append:
                # A same-size notification can be an in-place rewrite anywhere
                # in the artifact. Rebuild this one file so its old contribution
                # is retracted; normal append notifications never take this path.
                state = None
        else:
            state = None
        if state is None:
            state = self._new_state()
        try:
            if path.name.endswith(".zstd"):
                self._read_zstd(path, state, current["size"])
            else:
                self._read_raw(path, state, current["size"])
            state["identity"] = current
            self._files[key] = state
            return True
        except Exception:
            self.errors += 1
            return False

    @staticmethod
    def _new_state() -> dict:
        return {
            "identity": None,
            "offset": 0,
            "remainder": "",
            "header": {},
            "route": None,
            "steps": {},
            "aux": {},
            "last_event": None,
        }

    def _read_raw(self, path: Path, state: dict, size: int) -> None:
        offset = int(state.get("offset", 0))
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(max(0, size - offset))
        state["offset"] = offset + len(chunk)
        data = str(state.get("remainder", "")).encode("utf-8", "surrogateescape") + chunk
        parts = data.split(b"\n")
        state["remainder"] = parts.pop().decode("utf-8", "surrogateescape")
        self._consume_lines(parts, state)

    def _read_zstd(self, path: Path, state: dict, size: int) -> None:
        offset = int(state.get("offset", 0))
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(max(0, size - offset))
        position = 0
        frames: list[bytes] = []
        while position < len(data):
            length = _frame_length(data, position)
            if length is None:
                break
            frames.append(data[position : position + length])
            position += length
        for decoded in self._decode_frames(frames):
            self._consume_lines(decoded.splitlines(), state)
        state["offset"] = offset + position
        state["remainder"] = ""

    def _decode_frames(self, frames: list[bytes]) -> list[bytes]:
        if not frames:
            return []
        if self.frame_decoder is not None:
            return [self.frame_decoder(frame) for frame in frames]
        if _zstandard is not None:
            decoder = _zstandard.ZstdDecompressor()
            decoded: list[bytes] = []
            for frame in frames:
                magic = int.from_bytes(frame[:4], "little")
                if SKIPPABLE_MIN <= magic <= SKIPPABLE_MAX:
                    decoded.append(b"")
                    continue
                with decoder.stream_reader(io.BytesIO(frame), read_across_frames=False) as reader:
                    decoded.append(reader.read())
            return decoded
        if self.node_runner is not None:
            return [self.node_runner(frame) for frame in frames]
        helper = (
            "const f=require('node:fs'),z=require('node:zlib');"
            "const a=JSON.parse(f.readFileSync(0,'utf8'));"
            "process.stdout.write(JSON.stringify(a.map(x=>"
            "z.zstdDecompressSync(Buffer.from(x,'base64')).toString('base64'))));"
        )
        payload = json.dumps(
            [base64.b64encode(frame).decode("ascii") for frame in frames],
            separators=(",", ":"),
        ).encode("ascii")
        completed = subprocess.run(
            [os.environ.get("TOKENWATCHER_DSH_NODE", "node"), "-e", helper],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        decoded = json.loads(completed.stdout)
        if not isinstance(decoded, list) or len(decoded) != len(frames):
            raise ValueError("unexpected Node Zstandard decoder result")
        return [base64.b64decode(str(value).encode("ascii")) for value in decoded]

    def _consume_lines(self, lines: Iterable[bytes], state: dict) -> None:
        for raw in lines:
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("event is not an object")
                self._consume(event, state)
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                self.errors += 1

    def _consume(self, event: dict, state: dict) -> None:
        kind = _event_type(event)
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        seq = event.get("seq", data.get("seq"))
        if kind in ("session", "header", "session/header") or (not state["header"] and "id" in event and "createdAt" in event):
            header = data.get("header") if isinstance(data.get("header"), dict) else data or event
            state["header"] = {
                "id": header.get("id") or event.get("id"),
                "createdAt": header.get("createdAt") or event.get("createdAt"),
                "seedLength": header.get("seedLength", event.get("seedLength", 0)) or 0,
            }
            route = _route(header.get("config")) or _route(header)
            if route:
                state["route"] = route
            return
        try:
            if seq is not None and int(seq) < int(state.get("header", {}).get("seedLength", 0)):
                return
        except (TypeError, ValueError):
            self.errors += 1
            return
        route = self._event_route(data, event, state)
        if kind in ("request", "assistant/request", "request/header", "request/context"):
            header = data.get("header") if isinstance(data.get("header"), dict) else {}
            request_route = _route(header.get("config")) or _route(data) or route
            if request_route:
                state["route"] = list(request_route)
            return
        timestamp = (
            event.get("time")
            or event.get("timestamp")
            or event.get("createdAt")
            or data.get("timestamp")
            or data.get("createdAt")
        )
        if kind == "assistant/chunk":
            chunk = data.get("chunk") if isinstance(data.get("chunk"), dict) else data
            if chunk.get("type") != "usage":
                return
            sample_usage = _usage(chunk.get("usage") or chunk)
            self._store_step(event, data, state, sample_usage, route, timestamp, final=False)
        elif kind == "assistant/message":
            message = data.get("message") if isinstance(data.get("message"), dict) else data
            sample_usage = _usage(message.get("usage") or data.get("usage"))
            self._store_step(event, data, state, sample_usage, route, timestamp, final=True)
        elif kind == "compaction/summary" and data.get("llmStreamCall") is True:
            sample_usage = _usage(data.get("usage"))
            if sample_usage and route and seq is not None:
                state["aux"][f"compaction:{seq}"] = self._sample(
                    sample_usage,
                    route,
                    timestamp,
                )
        elif kind == "session/title-llm-usage":
            sample_usage = _usage(data.get("usage"))
            title_route = _route(data.get("route")) or route
            request_seq = data.get("requestSeq")
            if sample_usage and title_route and request_seq is not None:
                state["aux"][f"title:{request_seq}"] = self._sample(
                    sample_usage,
                    title_route,
                    timestamp,
                )
        if timestamp:
            try:
                parsed = _parse_time(timestamp).isoformat()
                if state.get("last_event") is None or parsed > state["last_event"]:
                    state["last_event"] = parsed
            except ValueError:
                self.errors += 1

    @staticmethod
    def _event_route(data: dict, event: dict, state: dict) -> tuple[str, str] | None:
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        return (
            _route(message.get("source"))
            or _route(data.get("provenance"))
            or _route(data.get("source"))
            or _route(data)
            or _route(event.get("source"))
            or (tuple(state["route"]) if state.get("route") else None)
        )

    def _store_step(self, event: dict, data: dict, state: dict, usage: dict | None, route, timestamp, *, final: bool) -> None:
        if usage is None:
            return
        turn = event.get("turn", data.get("turn", data.get("turnId", 0)))
        step = event.get("step", data.get("step", data.get("stepId", 0)))
        key = json.dumps([turn, step], separators=(",", ":"), default=str)
        previous = state["steps"].get(key)
        if final and route is None and previous:
            route = tuple(previous.get("route", ())) or None
        if route is None:
            route = tuple(state["route"]) if state.get("route") else None
        if route is None:
            return
        if previous and previous.get("final") and not final:
            return
        sample = self._sample(usage, route, timestamp)
        sample["final"] = final
        state["steps"][key] = sample

    def _sample(self, usage: dict, route: tuple[str, str], timestamp: object) -> dict:
        try:
            parsed = _parse_time(timestamp) if timestamp else self.now()
        except ValueError:
            self.errors += 1
            parsed = self.now()
        return {"usage": usage, "route": list(route), "timestamp": parsed.isoformat()}

    def _cost(
        self,
        model: str,
        usage: dict[str, int],
        when: datetime,
    ) -> float | None:
        return usage_cost_usd(
            model,
            input_tokens=usage["input"],
            cache_read_tokens=usage["cacheRead"],
            cache_write_tokens=usage["cacheWrite"],
            output_tokens=usage["output"],
            prices=self.prices,
            event_time=when,
            include_promotions=self.include_promotions,
        )

    def _rebuild(self) -> None:
        self.periods = _empty_periods()
        self.call_periods = _empty_periods()
        self.cost_periods = _empty_periods()
        self.last_event = None
        today = self.now().astimezone(SHANGHAI).date()
        for state in self._files.values():
            for sample in list(state.get("steps", {}).values()) + list(state.get("aux", {}).values()):
                try:
                    usage = sample["usage"]
                    provider = str(sample["route"][0])
                    model = str(sample["route"][1])
                    if provider.casefold() in self.excluded_providers:
                        continue
                    when = _parse_time(sample["timestamp"])
                    if when.astimezone(timezone.utc) < self.since:
                        continue
                    event_date = when.astimezone(SHANGHAI).date()
                    key = (PLATFORM, model)
                    tokens = usage["input"] + usage["output"] + usage["cacheRead"] + usage["cacheWrite"]
                    cost = self._cost(model, usage, when)
                    for period in _active_periods(event_date, today):
                        self.periods[period][key] += tokens
                        self.call_periods[period][key] += 1
                        if cost is not None:
                            self.cost_periods[period][key] += cost
                    if self.last_event is None or when > self.last_event:
                        self.last_event = when
                except (KeyError, TypeError, ValueError):
                    self.errors += 1

    def _load_cache(self) -> None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != CACHE_VERSION or Path(payload.get("root", "")).resolve() != self.root:
                return
            files = payload.get("files", {})
            if isinstance(files, dict):
                self._files = files
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.cache_errors += 1

    def _save_cache(self) -> None:
        temporary = self.cache_path.with_name(f"{self.cache_path.name}.{os.getpid()}.tmp")
        payload = {
            "version": CACHE_VERSION,
            "root": str(self.root),
            "files": self._files,
            "periods": {name: {json.dumps(key): value for key, value in counter.items()} for name, counter in self.periods.items()},
            "call_periods": {name: {json.dumps(key): value for key, value in counter.items()} for name, counter in self.call_periods.items()},
            "cost_periods": {name: {json.dumps(key): value for key, value in counter.items()} for name, counter in self.cost_periods.items()},
            "last_event": self.last_event.isoformat() if self.last_event else None,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self.cache_path)
        except OSError:
            self.cache_errors += 1
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["DshTailTracker", "PERIODS", "SHANGHAI"]

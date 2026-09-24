from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from dsh_usage_tracker import DshTailTracker
from model_pricing import (
    DEFAULT_PRICES,
    MODEL_VERIFIED_ON,
    PRICE_VERIFIED_ON,
    resolve_price,
    usage_cost_usd as calculate_usage_cost_usd,
)
from sub2api_usage_poller import Sub2ApiUsagePoller


APP_TITLE = "TokenWatcher"
INSTANCE_MUTEX_NAME = "Local\\TokenWatcher.Singleton"
START_DATE = date(2026, 2, 1)
DEFAULT_REFRESH_SECONDS = 0.25
MIN_REFRESH_SECONDS = 0.1
MAX_REFRESH_SECONDS = 2.0
MAX_USAGE_VALUE = (1 << 63) - 1
LIVE_DELTA_VISIBLE_MS = 1600
STARTUP_DELTA_VISIBLE_MS = 8000
REFRESH_OPTIONS = (0.1, 0.25, 0.5, 1.0, 2.0)
REFRESH_SECONDS = DEFAULT_REFRESH_SECONDS
STARTUP_HOT_SECONDS = 300.0
REFERENCE_FILE_CHECK_SECONDS = 5.0
FALLBACK_RESCAN_SECONDS = 30.0
REPORT_CHECK_SECONDS = 10.0
FINGERPRINT_COMPACT_THRESHOLD = 4096
LONG_CONTEXT_THRESHOLD = 272_000
SHANGHAI = timezone(timedelta(hours=8))
PERIODS = ("today", "week", "month", "cumulative")
PERIOD_LABELS = {
    "today": "本日",
    "week": "本周",
    "month": "本月",
    "cumulative": "累计",
}
PLATFORM_COLORS = {
    "Codex": "#4C8DFF",
    "Claude Code": "#F59E42",
    "Cline": "#26C6A2",
    "DeepSeek API": "#536DFE",
    "DeepSeek Harness": "#7C4DFF",
}
REPORT_FOLDER_NAME = "codex_claude_usage_since_2026-02"
CLINE_HISTORY = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Code"
    / "User"
    / "globalStorage"
    / "saoudrizwan.claude-dev"
    / "state"
    / "taskHistory.json"
)
CLINE_TASKS = CLINE_HISTORY.parent.parent / "tasks"
SUB2API_ROOT = Path(
    os.environ.get("TOKENWATCHER_SUB2API_ROOT", r"D:\software\sub2api")
)
SUB2API_CONFIG = Path(
    os.environ.get("TOKENWATCHER_SUB2API_CONFIG", str(SUB2API_ROOT / "config.yaml"))
)
SUB2API_PSQL = Path(
    os.environ.get(
        "TOKENWATCHER_SUB2API_PSQL",
        str(SUB2API_ROOT / "runtime" / "pgsql" / "bin" / "psql.exe"),
    )
)
DSH_HOME = Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))
DSH_SESSIONS = Path(
    os.environ.get("TOKENWATCHER_DSH_SESSIONS", str(DSH_HOME / "sessions"))
)
CODEX_USAGE_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
CODEX_CACHE_VERSION = 8
CLAUDE_CACHE_VERSION = 6
USAGE_SNAPSHOT_CACHE_VERSION = 8
WINDOWS_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
CASCADIA_MONO_FONT = str(WINDOWS_FONTS / "CascadiaMono.ttf")
YAHEI_FONT = str(WINDOWS_FONTS / "msyh.ttc")
YAHEI_BOLD_FONT = str(WINDOWS_FONTS / "msyhbd.ttc")
WINDOW_WIDTH = 902
WINDOW_HEIGHT = 260
ROW_HEIGHT = 56
ROW_MIDDLE = ROW_HEIGHT // 2
DEFAULT_ROW_COUNT = 3
MIN_ROW_COUNT = 1
MAX_ROW_COUNT = 10
ROW_COUNT_LABELS = (
    "零",
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
)
BODY_FONT_SIZE = 26
TITLE_FONT_SIZE = 28
MODEL_BADGE_FONT_SIZE = BODY_FONT_SIZE
DELTA_FONT_SIZE = BODY_FONT_SIZE
COST_FONT_SIZE = BODY_FONT_SIZE
VALUE_COLUMN_GAP = 20
MODEL_CALL_LEFT_SHIFT = 16
RANK_LEFT_SHIFT = 16
RANK_COLUMN_WIDTH = 28
MODEL_COLUMN_WIDTH = 116
CALL_COLUMN_WIDTH = 150
DELTA_COLUMN_WIDTH = 132
TOKEN_COLUMN_WIDTH = 218
COST_COLUMN_WIDTH = 150
FOOTER_CONTROL_WIDTH = 68
FOOTER_COLUMN_WIDTH = WINDOW_WIDTH - 80 - (2 * FOOTER_CONTROL_WIDTH)
DEFAULT_UI_SCALE = 0.9
MIN_UI_SCALE = 0.7
MAX_UI_SCALE = 1.4
UI_SCALE_STEP = 0.05
UI_SETTINGS_PATH = Path.home() / ".tokenwatcher" / "ui_settings.json"
BASE_UI_METRICS = {
    "WINDOW_WIDTH": WINDOW_WIDTH,
    "WINDOW_HEIGHT": WINDOW_HEIGHT,
    "ROW_HEIGHT": ROW_HEIGHT,
    "BODY_FONT_SIZE": BODY_FONT_SIZE,
    "TITLE_FONT_SIZE": TITLE_FONT_SIZE,
    "MODEL_BADGE_FONT_SIZE": MODEL_BADGE_FONT_SIZE,
    "DELTA_FONT_SIZE": DELTA_FONT_SIZE,
    "COST_FONT_SIZE": COST_FONT_SIZE,
    "RANK_COLUMN_WIDTH": RANK_COLUMN_WIDTH,
    "MODEL_COLUMN_WIDTH": MODEL_COLUMN_WIDTH,
    "CALL_COLUMN_WIDTH": CALL_COLUMN_WIDTH,
    "DELTA_COLUMN_WIDTH": DELTA_COLUMN_WIDTH,
    "TOKEN_COLUMN_WIDTH": TOKEN_COLUMN_WIDTH,
    "COST_COLUMN_WIDTH": COST_COLUMN_WIDTH,
    "FOOTER_CONTROL_WIDTH": FOOTER_CONTROL_WIDTH,
    "VALUE_COLUMN_GAP": VALUE_COLUMN_GAP,
    "MODEL_CALL_LEFT_SHIFT": MODEL_CALL_LEFT_SHIFT,
    "RANK_LEFT_SHIFT": RANK_LEFT_SHIFT,
}


def scaled(value: int, scale: float) -> int:
    return max(1, round(value * scale))


def apply_ui_scale(value: float) -> float:
    global WINDOW_WIDTH, WINDOW_HEIGHT, ROW_HEIGHT, ROW_MIDDLE
    global BODY_FONT_SIZE, TITLE_FONT_SIZE, MODEL_BADGE_FONT_SIZE
    global DELTA_FONT_SIZE, COST_FONT_SIZE, RANK_COLUMN_WIDTH
    global MODEL_COLUMN_WIDTH, CALL_COLUMN_WIDTH, DELTA_COLUMN_WIDTH
    global TOKEN_COLUMN_WIDTH, COST_COLUMN_WIDTH, VALUE_COLUMN_GAP
    global MODEL_CALL_LEFT_SHIFT, RANK_LEFT_SHIFT
    global FOOTER_CONTROL_WIDTH, FOOTER_COLUMN_WIDTH

    value = min(MAX_UI_SCALE, max(MIN_UI_SCALE, float(value)))
    for name, base_value in BASE_UI_METRICS.items():
        globals()[name] = scaled(base_value, value)
    ROW_MIDDLE = ROW_HEIGHT // 2
    FOOTER_COLUMN_WIDTH = (
        WINDOW_WIDTH - scaled(80, value) - (2 * FOOTER_CONTROL_WIDTH)
    )
    return value


def clamp_row_count(value: int) -> int:
    return min(MAX_ROW_COUNT, max(MIN_ROW_COUNT, int(value)))


def row_count_label(value: int) -> str:
    return ROW_COUNT_LABELS[clamp_row_count(value)]


def window_height_for_rows(row_count: int) -> int:
    return WINDOW_HEIGHT + (
        clamp_row_count(row_count) - DEFAULT_ROW_COUNT
    ) * ROW_HEIGHT


def _read_ui_settings(settings_path: Path) -> dict:
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return settings if isinstance(settings, dict) else {}


def _save_ui_settings(updates: dict, settings_path: Path) -> None:
    temporary_path = settings_path.with_name(
        f"{settings_path.name}.{os.getpid()}.tmp"
    )
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = _read_ui_settings(settings_path)
        settings.update(updates)
        temporary_path.write_text(
            json.dumps(settings, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, settings_path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def load_ui_scale(settings_path: Path = UI_SETTINGS_PATH) -> float:
    environment_value = os.environ.get("TOKENWATCHER_UI_SCALE", "").strip()
    try:
        value = (
            float(environment_value)
            if environment_value
            else float(_read_ui_settings(settings_path).get("scale", DEFAULT_UI_SCALE))
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        value = DEFAULT_UI_SCALE
    return min(MAX_UI_SCALE, max(MIN_UI_SCALE, value))


def save_ui_scale(
    value: float,
    settings_path: Path = UI_SETTINGS_PATH,
) -> None:
    _save_ui_settings({"scale": round(value, 2)}, settings_path)


def load_row_count(settings_path: Path = UI_SETTINGS_PATH) -> int:
    environment_value = os.environ.get("TOKENWATCHER_ROW_COUNT", "").strip()
    try:
        value = int(
            environment_value
            if environment_value
            else _read_ui_settings(settings_path).get(
                "row_count",
                DEFAULT_ROW_COUNT,
            )
        )
    except (ValueError, TypeError):
        value = DEFAULT_ROW_COUNT
    return clamp_row_count(value)


def save_row_count(
    value: int,
    settings_path: Path = UI_SETTINGS_PATH,
) -> None:
    _save_ui_settings({"row_count": clamp_row_count(value)}, settings_path)


def clamp_refresh_seconds(value: float) -> float:
    return min(MAX_REFRESH_SECONDS, max(MIN_REFRESH_SECONDS, float(value)))


def apply_refresh_seconds(value: float) -> float:
    global REFRESH_SECONDS
    REFRESH_SECONDS = clamp_refresh_seconds(value)
    return REFRESH_SECONDS


def load_refresh_seconds(settings_path: Path = UI_SETTINGS_PATH) -> float:
    environment_value = os.environ.get(
        "TOKENWATCHER_REFRESH_SECONDS",
        "",
    ).strip()
    try:
        value = float(
            environment_value
            if environment_value
            else _read_ui_settings(settings_path).get(
                "refresh_seconds",
                DEFAULT_REFRESH_SECONDS,
            )
        )
    except (ValueError, TypeError):
        value = DEFAULT_REFRESH_SECONDS
    return clamp_refresh_seconds(value)


def save_refresh_seconds(
    value: float,
    settings_path: Path = UI_SETTINGS_PATH,
) -> None:
    _save_ui_settings(
        {"refresh_seconds": round(clamp_refresh_seconds(value), 2)},
        settings_path,
    )


def format_refresh_seconds(value: float) -> str:
    return f"{clamp_refresh_seconds(value):g}"

def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def _relative_luminance(pixel: tuple[int, int, int]) -> float:
    channels = []
    for value in pixel:
        normalized = value / 255.0
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def choose_text_foreground(
    pixels: list[tuple[int, int, int]],
    previous_foreground: str = "#FFFFFF",
) -> str:
    if not pixels:
        return previous_foreground
    luminances = [_relative_luminance(pixel) for pixel in pixels]
    black_contrasts = [(value + 0.05) / 0.05 for value in luminances]
    white_contrasts = [1.05 / (value + 0.05) for value in luminances]
    black_score = _percentile(black_contrasts, 0.2)
    white_score = _percentile(white_contrasts, 0.2)
    if abs(black_score - white_score) < 0.15:
        return previous_foreground
    return "#000000" if black_score > white_score else "#FFFFFF"


def _render_solid_contrast_text(
    background,
    text: str,
    font_name: str,
    font_size: int,
    position: tuple[int, int],
    anchor: str,
    solid_color: str | None = None,
    previous_foreground: str = "#FFFFFF",
):
    from PIL import Image, ImageColor, ImageDraw, ImageFont

    width, height = background.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    font = _load_image_font(font_name, font_size)
    draw.text(position, text, font=font, fill=255, anchor=anchor)
    selected_color = solid_color
    if selected_color is None:
        rgb_background = background.convert("RGB")
        glyph_pixels = [
            pixel
            for pixel, alpha in zip(rgb_background.getdata(), mask.getdata())
            if alpha >= 32
        ]
        selected_color = choose_text_foreground(
            glyph_pixels,
            previous_foreground,
        )
    red, green, blue = ImageColor.getrgb(selected_color)
    color = Image.new("RGBA", (width, height), (red, green, blue, 255))
    color.putalpha(mask)
    return color, selected_color


def render_solid_contrast_text(
    background,
    text: str,
    font_name: str,
    font_size: int,
    position: tuple[int, int],
    anchor: str,
    solid_color: str | None = None,
    previous_foreground: str = "#FFFFFF",
):
    image, _ = _render_solid_contrast_text(
        background,
        text,
        font_name,
        font_size,
        position,
        anchor,
        solid_color,
        previous_foreground,
    )
    return image


@lru_cache(maxsize=32)
def _load_image_font(font_name: str, font_size: int):
    from PIL import ImageFont

    return ImageFont.truetype(font_name, font_size)


class AdaptiveCanvasText:
    def __init__(
        self,
        canvas: tk.Canvas,
        *,
        text: str,
        font_name: str,
        font_size: int,
        position: tuple[int, int],
        anchor: str,
    ):
        self.canvas = canvas
        self.text = text
        self.font_name = font_name
        self.font_size = font_size
        self.position = position
        self.anchor = anchor
        self.solid_color: str | None = None
        self.automatic_foreground = "#FFFFFF"
        self.photo = None
        self.last_image = None
        self.image_id = canvas.create_image(0, 0, anchor="nw")
        self.last_background = None
        self.last_root = None

    def set_text(self, text: str) -> None:
        self.text = text
        self.render_cached()

    def hide(self) -> None:
        self.canvas.itemconfigure(self.image_id, state="hidden")

    def prepare(self, background, root: tk.Tk):
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        x = self.canvas.winfo_rootx() - root.winfo_rootx()
        y = self.canvas.winfo_rooty() - root.winfo_rooty()
        crop = background.crop((x, y, x + width, y + height))
        image, selected_color = _render_solid_contrast_text(
            crop,
            self.text,
            self.font_name,
            self.font_size,
            self.position,
            self.anchor,
            self.solid_color,
            self.automatic_foreground,
        )
        if self.solid_color is None:
            self.automatic_foreground = selected_color
        return image

    def apply_prepared(self, image, background, root: tk.Tk) -> None:
        from PIL import ImageTk

        new_photo = ImageTk.PhotoImage(image)
        previous_photo = self.photo
        self.last_image = image
        self.canvas.itemconfigure(
            self.image_id,
            image=new_photo,
            state="normal",
        )
        self.photo = new_photo
        self.last_background = background
        self.last_root = root
        del previous_photo

    def prepare_photo(self, image):
        from PIL import ImageTk

        return ImageTk.PhotoImage(image)

    def apply_buffered(self, image, photo, background, root: tk.Tk) -> None:
        previous_photo = self.photo
        self.last_image = image
        self.canvas.itemconfigure(self.image_id, image=photo, state="normal")
        self.photo = photo
        self.last_background = background
        self.last_root = root
        del previous_photo

    def render(self, background, root: tk.Tk) -> None:
        self.apply_prepared(self.prepare(background, root), background, root)

    def render_cached(self) -> None:
        if self.last_background is not None and self.last_root is not None:
            self.render(self.last_background, self.last_root)


def codex_usage_fingerprint(
    session_id: str,
    event_timestamp: object,
    info: dict,
) -> tuple:
    last_usage = info.get("last_token_usage") or {}
    total_usage = info.get("total_token_usage") or {}
    last_values = tuple(int(last_usage.get(key) or 0) for key in CODEX_USAGE_KEYS)
    total_values = tuple(int(total_usage.get(key) or 0) for key in CODEX_USAGE_KEYS)
    if any(total_values):
        return (session_id or "<unknown>", "cumulative", *total_values, *last_values)
    return (
        session_id or "<unknown>",
        "timestamp",
        str(event_timestamp or ""),
        *last_values,
    )


def codex_fingerprint_digest(fingerprint: tuple) -> bytes:
    payload = json.dumps(
        fingerprint,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).digest()


def codex_parent_session_id(payload: dict) -> str:
    """Return the parent session recorded by Codex subagent/fork metadata."""
    session_id = str(payload.get("id") or "")
    source = payload.get("source") or {}
    source = source if isinstance(source, dict) else {}
    subagent = source.get("subagent") or {}
    subagent = subagent if isinstance(subagent, dict) else {}
    thread_spawn = subagent.get("thread_spawn") or {}
    thread_spawn = thread_spawn if isinstance(thread_spawn, dict) else {}
    for candidate in (
        payload.get("parent_thread_id"),
        payload.get("forked_from_id"),
        thread_spawn.get("parent_thread_id"),
        payload.get("session_id"),
    ):
        candidate = str(candidate or "")
        if candidate and candidate != session_id:
            return candidate
    return ""


class DirectoryChangeWatcher:
    """Collect recursive Windows directory changes without rescanning the tree."""

    def __init__(self, root: Path):
        self.root = root
        self.available = False
        self._changes: queue.SimpleQueue[Path] = queue.SimpleQueue()
        self._resync_required = threading.Event()
        self._closed = threading.Event()
        self._kernel32 = None
        self._handle = None
        self._thread: threading.Thread | None = None
        if os.name == "nt" and root.exists():
            self._start_windows()

    def _start_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        file_list_directory = 0x0001
        share_all = 0x00000001 | 0x00000002 | 0x00000004
        open_existing = 3
        backup_semantics = 0x02000000
        invalid_handle = ctypes.c_void_p(-1).value
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CreateFileW.restype = wintypes.HANDLE
        handle = kernel32.CreateFileW(
            str(self.root),
            file_list_directory,
            share_all,
            None,
            open_existing,
            backup_semantics,
            None,
        )
        if handle == invalid_handle:
            return
        self._kernel32 = kernel32
        self._handle = handle
        self.available = True
        self._thread = threading.Thread(
            target=self._run_windows,
            daemon=True,
            name=f"watch-{self.root.name}",
        )
        self._thread.start()

    def _run_windows(self) -> None:
        import ctypes
        import struct
        from ctypes import wintypes

        notify_filter = (
            0x00000001  # FILE_NOTIFY_CHANGE_FILE_NAME
            | 0x00000002  # FILE_NOTIFY_CHANGE_DIR_NAME
            | 0x00000008  # FILE_NOTIFY_CHANGE_SIZE
            | 0x00000010  # FILE_NOTIFY_CHANGE_LAST_WRITE
            | 0x00000040  # FILE_NOTIFY_CHANGE_CREATION
        )
        kernel32 = self._kernel32
        if kernel32 is None:
            self.available = False
            return
        kernel32.ReadDirectoryChangesW.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        )
        kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
        buffer = ctypes.create_string_buffer(64 * 1024)
        bytes_returned = wintypes.DWORD()
        error_notify_enum_dir = 1022
        while not self._closed.is_set() and self._handle is not None:
            ctypes.set_last_error(0)
            ok = kernel32.ReadDirectoryChangesW(
                self._handle,
                buffer,
                len(buffer),
                True,
                notify_filter,
                ctypes.byref(bytes_returned),
                None,
                None,
            )
            if not ok:
                if self._closed.is_set():
                    break
                self._resync_required.set()
                if ctypes.get_last_error() == error_notify_enum_dir:
                    continue
                break
            length = int(bytes_returned.value)
            if not length:
                # A synchronous ReadDirectoryChangesW call reports a buffer
                # overflow with an empty result.  The directory handle remains
                # usable, but one or more file names were lost.  Keep listening
                # and ask consumers for one explicit reconciliation pass.
                self._resync_required.set()
                continue
            offset = 0
            while offset < length:
                next_offset, _action, name_bytes = struct.unpack_from(
                    "<III", buffer.raw, offset
                )
                name_start = offset + 12
                relative_name = buffer.raw[
                    name_start : name_start + name_bytes
                ].decode("utf-16-le", errors="replace")
                self._changes.put(self.root / relative_name)
                if not next_offset:
                    break
                offset += next_offset
        self.available = False

    def drain(self) -> set[Path]:
        changes: set[Path] = set()
        while True:
            try:
                changes.add(self._changes.get_nowait())
            except queue.Empty:
                return changes

    def consume_resync_required(self) -> bool:
        if not self._resync_required.is_set():
            return False
        self._resync_required.clear()
        return True

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        handle = self._handle
        self._handle = None
        self.available = False
        if handle is not None and os.name == "nt":
            from ctypes import wintypes

            kernel32 = self._kernel32
            if kernel32 is not None:
                kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
                kernel32.CancelIoEx.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
                kernel32.CloseHandle.restype = wintypes.BOOL
                kernel32.CancelIoEx(handle, None)
                kernel32.CloseHandle(handle)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def acquire_single_instance_mutex():
    if os.name != "nt":
        return True
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        return None
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def release_single_instance_mutex(handle) -> None:
    if os.name == "nt" and handle not in (None, True):
        import ctypes

        ctypes.windll.kernel32.CloseHandle(handle)


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def nonnegative_int(value: object, field_name: str = "value") -> int:
    """Parse a finite non-negative integer from a durable or provider boundary."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{field_name} must be a finite integer")
        parsed = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if parsed < 0 or parsed > MAX_USAGE_VALUE:
        raise ValueError(f"{field_name} is outside the supported range")
    return parsed


def nonnegative_float(value: object, field_name: str = "value") -> float:
    """Parse a finite non-negative number from a durable or provider boundary."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return parsed


def format_tokens(value: int) -> str:
    return f"{int(value):,}"


def format_cost(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def observed_growth(
    current: int,
    previous: dict[tuple[str, str], int],
    key: tuple[str, str],
    *,
    include_new_key: bool,
) -> int:
    """Return growth against a prior snapshot, optionally counting a new key."""
    return int(current) - int(previous.get(key, 0 if include_new_key else current))


def write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def emit_stdout(text: str) -> bool:
    payload = text + "\n"
    if sys.stdout is not None:
        try:
            sys.stdout.write(payload)
            sys.stdout.flush()
            return True
        except (OSError, ValueError):
            pass
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.AttachConsole(wintypes.DWORD(-1).value)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, 0, invalid_handle):
            return False
        mode = wintypes.DWORD()
        written = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return bool(
                kernel32.WriteConsoleW(
                    handle,
                    payload,
                    len(payload),
                    ctypes.byref(written),
                    None,
                )
            )
        encoded = payload.encode("utf-8")
        return bool(
            kernel32.WriteFile(
                handle,
                encoded,
                len(encoded),
                ctypes.byref(written),
                None,
            )
        )
    except (AttributeError, OSError, ValueError):
        return False


def compact_model_name(model: str) -> str:
    name = model.strip()
    lower = name.lower()
    if lower.startswith("gpt-"):
        name = lower.removeprefix("gpt-").replace("codex", "cdx")
    elif lower.startswith("claude-"):
        name = lower.removeprefix("claude-")
        name = name.replace("sonnet", "son").replace("deepseek", "ds")
        if name.endswith(tuple(f"-{year}" for year in range(2020, 2031))):
            name = name.rsplit("-", 1)[0]
        parts = name.split("-")
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            name = "-".join(parts[:-2]) + f"-{parts[-2]}.{parts[-1]}"
    elif lower.startswith("deepseek-"):
        name = "ds-" + lower.removeprefix("deepseek-")
    elif lower.startswith("glm-"):
        name = name.upper()
    if len(name) > 9:
        return f"{name[:8]}…"
    return name


def empty_periods() -> dict[str, Counter]:
    return {period: Counter() for period in PERIODS}


def rollover_periods(
    periods: dict[str, Counter] | dict[str, dict],
    previous_date: date,
    current_date: date,
) -> tuple[str, ...]:
    if current_date <= previous_date:
        return ()
    reset = ["today"]
    if previous_date.isocalendar()[:2] != current_date.isocalendar()[:2]:
        reset.append("week")
    if (previous_date.year, previous_date.month) != (
        current_date.year,
        current_date.month,
    ):
        reset.append("month")
    for period in reset:
        periods[period].clear()
    return tuple(reset)


def cached_period_date(payload: dict, fallback: date | None = None) -> date:
    value = payload.get("period_date") or payload.get("updated_at")
    if value:
        return parse_time(str(value)).astimezone(SHANGHAI).date()
    return fallback or datetime.now(SHANGHAI).date()


def active_periods(event_date: date, now_date: date | None = None) -> tuple[str, ...]:
    now_date = now_date or datetime.now(SHANGHAI).date()
    periods = ["cumulative"]
    if event_date.year == now_date.year and event_date.month == now_date.month:
        periods.append("month")
    week_start = now_date - timedelta(days=now_date.weekday())
    if week_start <= event_date <= now_date:
        periods.append("week")
    if event_date == now_date:
        periods.append("today")
    return tuple(periods)


def add_period_usage(
    periods: dict[str, Counter],
    key: tuple[str, str],
    tokens: int,
    event_date: date,
) -> None:
    for period in active_periods(event_date):
        periods[period][key] += int(tokens)


def add_period_cost(
    periods: dict[str, Counter],
    key: tuple[str, str],
    cost_usd: float,
    event_date: date,
) -> None:
    for period in active_periods(event_date):
        periods[period][key] += float(cost_usd)


def find_report_dir() -> Path:
    configured = os.environ.get("AI_USAGE_REPORT_DIR")
    candidates = [Path(configured).expanduser()] if configured else []

    def add_ancestor_candidates(root: Path) -> None:
        for directory in (root, *tuple(root.parents)[:3]):
            candidate = directory / "outputs" / REPORT_FOLDER_NAME
            if candidate not in candidates:
                candidates.append(candidate)

    if getattr(sys, "frozen", False):
        executable_root = Path(sys.executable).resolve().parent
        add_ancestor_candidates(executable_root)
    else:
        root = Path(__file__).resolve().parents[1]
        add_ancestor_candidates(root)
    add_ancestor_candidates(Path.cwd().resolve())
    candidates.append(Path.home() / ".tokenwatcher" / REPORT_FOLDER_NAME)
    for candidate in candidates:
        if (candidate / "model_total.csv").exists():
            return candidate
    return candidates[0]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_pricing(report_dir: Path) -> dict[str, dict[str, float]]:
    prices = {model: dict(values) for model, values in DEFAULT_PRICES.items()}
    path = report_dir / "pricing_used.csv"
    if not path.exists():
        return prices
    try:
        rows = read_csv(path)
    except OSError:
        return prices
    field_map = {
        "input": "input_usd_per_mtok",
        "cached": "cached_input_usd_per_mtok",
        "cache_write": "cache_write_usd_per_mtok",
        "cache_write_1h": "cache_write_1h_usd_per_mtok",
        "output": "output_usd_per_mtok",
        "long_input": "long_input_usd_per_mtok",
        "long_cached": "long_cached_input_usd_per_mtok",
        "long_cache_write": "long_cache_write_usd_per_mtok",
        "long_output": "long_output_usd_per_mtok",
        "peak_input": "peak_input_usd_per_mtok",
        "peak_cached": "peak_cached_input_usd_per_mtok",
        "peak_cache_write": "peak_cache_write_usd_per_mtok",
        "peak_output": "peak_output_usd_per_mtok",
    }
    for row in rows:
        if row.get("pricing_status") != "official_standard_price":
            continue
        expected_date = MODEL_VERIFIED_ON.get(str(row.get("model") or ""), PRICE_VERIFIED_ON)
        if str(row.get("verified_on") or "") != expected_date:
            continue
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        values = dict(prices.get(model, {}))
        try:
            for name, field_name in field_map.items():
                raw_value = str(row.get(field_name) or "").strip()
                if raw_value:
                    values[name] = nonnegative_float(raw_value, field_name)
        except ValueError:
            continue
        if "input" in values and "output" in values:
            prices[model] = values
    return prices


def usage_cost_usd(
    model: str,
    usage: dict,
    *,
    source: str,
    prices: dict[str, dict[str, float]] | None = None,
    context_window: int = 0,
    event_time: datetime | None = None,
    pricing_bucket: str | None = None,
    include_promotions: bool = False,
) -> float | None:
    try:
        input_tokens = nonnegative_int(
            usage.get("input_tokens") or 0,
            "input_tokens",
        )
        output_tokens = nonnegative_int(
            usage.get("output_tokens") or 0,
            "output_tokens",
        )
    except ValueError:
        return None
    if source == "codex":
        try:
            cached_tokens = nonnegative_int(
                usage.get("cached_input_tokens") or 0,
                "cached_input_tokens",
            )
        except ValueError:
            return None
        if cached_tokens > input_tokens:
            return None
        uncached_tokens = input_tokens - cached_tokens
        cache_write_tokens = 0
    else:
        uncached_tokens = input_tokens
        try:
            cached_tokens = nonnegative_int(
                usage.get("cache_read_input_tokens") or 0,
                "cache_read_input_tokens",
            )
            cache_write_tokens = nonnegative_int(
                usage.get("cache_creation_input_tokens") or 0,
                "cache_creation_input_tokens",
            )
        except ValueError:
            return None
    price = resolve_price(
        model,
        prices=prices or DEFAULT_PRICES,
        event_time=event_time,
        bucket=pricing_bucket,
        include_promotions=include_promotions,
    )
    if price is None:
        return None
    threshold = price.get("long_threshold")
    long_context = None
    if threshold is None and "long_input" in price:
        long_context = (
            context_window > LONG_CONTEXT_THRESHOLD
            and uncached_tokens + cached_tokens + cache_write_tokens
            > LONG_CONTEXT_THRESHOLD
        )
    return calculate_usage_cost_usd(
        model,
        input_tokens=uncached_tokens,
        cache_read_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
        prices=prices or DEFAULT_PRICES,
        event_time=event_time,
        bucket=pricing_bucket,
        long_context=long_context,
        include_promotions=include_promotions,
    )


@dataclass
class Baseline:
    report_dir: Path
    refreshed_at: datetime
    periods: dict[str, Counter] = field(default_factory=empty_periods)
    call_periods: dict[str, Counter] = field(default_factory=empty_periods)
    cost_periods: dict[str, Counter] = field(default_factory=empty_periods)
    report_mtime: float = 0.0
    warnings: tuple[str, ...] = ()


def load_baseline(report_dir: Path) -> Baseline:
    summary_path = report_dir / "summary.json"
    warnings: list[str] = []
    refreshed_at = datetime.combine(
        START_DATE,
        datetime.min.time(),
        tzinfo=SHANGHAI,
    )
    report_mtime = 0.0
    try:
        report_mtime = summary_path.stat().st_mtime
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ValueError("summary root is not an object")
        refreshed_at = parse_time(summary.get("refreshed_at_shanghai"))
    except FileNotFoundError:
        pass
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        warnings.append(f"summary.json: {type(exc).__name__}")

    baseline = Baseline(
        report_dir=report_dir,
        refreshed_at=refreshed_at,
        report_mtime=report_mtime,
    )

    def rows(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        try:
            return read_csv(path)
        except (OSError, csv.Error, UnicodeError) as exc:
            warnings.append(f"{path.name}: {type(exc).__name__}")
            return []

    model_total_path = report_dir / "model_total.csv"
    for row in rows(model_total_path):
        try:
            key = (str(row["platform"]), str(row["model"]))
            baseline.periods["cumulative"][key] += nonnegative_int(
                row["total_tokens"],
                "total_tokens",
            )
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{model_total_path.name}: skipped invalid row")

    now_date = datetime.now(SHANGHAI).date()
    daily_path = report_dir / "daily_by_platform_model.csv"
    for row in rows(daily_path):
        try:
            row_date = date.fromisoformat(str(row["date"]))
            key = (str(row["platform"]), str(row["model"]))
            tokens = nonnegative_int(row["total_tokens"], "total_tokens")
            calls = nonnegative_int(row.get("responses") or 0, "responses")
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{daily_path.name}: skipped invalid row")
            continue
        for period in active_periods(row_date, now_date):
            baseline.call_periods[period][key] += calls
            if period != "cumulative":
                baseline.periods[period][key] += tokens

    model_cost_path = report_dir / "model_cost.csv"
    for row in rows(model_cost_path):
        try:
            key = (str(row["platform"]), str(row["model"]))
            cost_usd = nonnegative_float(
                row["estimated_cost_usd"],
                "estimated_cost_usd",
            )
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{model_cost_path.name}: skipped invalid row")
            continue
        baseline.cost_periods["cumulative"][key] += cost_usd

    daily_cost_path = report_dir / "daily_cost_by_platform_model.csv"
    for row in rows(daily_cost_path):
        try:
            row_date = date.fromisoformat(str(row["date"]))
            key = (str(row["platform"]), str(row["model"]))
            cost_usd = nonnegative_float(
                row["estimated_cost_usd"],
                "estimated_cost_usd",
            )
        except (KeyError, TypeError, ValueError):
            warnings.append(f"{daily_cost_path.name}: skipped invalid row")
            continue
        for period in active_periods(row_date, now_date):
            if period != "cumulative":
                baseline.cost_periods[period][key] += cost_usd

    baseline.warnings = tuple(dict.fromkeys(warnings))
    return baseline


@dataclass
class CodexFileState:
    offset: int = 0
    remainder: bytes = b""
    model: str = "<unknown>"
    session_id: str = ""
    parent_session_id: str = ""
    last_mtime: float = 0.0
    last_mtime_ns: int = 0
    last_size: int = 0
    file_dev: int = 0
    file_ino: int = 0
    next_check: float = 0.0
    watching: bool = True
    stop_after_initial: bool = False


@dataclass
class CodexPendingUsage:
    fingerprint: bytes
    session_id: str
    total_tokens: int
    usage: dict
    context_window: int
    event_time: datetime


class CodexTailTracker:
    def __init__(
        self,
        since: datetime,
        watcher: DirectoryChangeWatcher | None = None,
        cache_path: Path | None = None,
        prices: dict[str, dict[str, float]] | None = None,
    ):
        self.since = since.astimezone(timezone.utc)
        self.root = Path.home() / ".codex"
        self.cache_path = cache_path or (
            Path.home() / ".tokenwatcher" / "codex_fingerprint_cache.json"
        )
        self._owns_watcher = watcher is None
        self.watcher = watcher or DirectoryChangeWatcher(self.root)
        self.prices = prices or DEFAULT_PRICES
        self.states: dict[Path, CodexFileState] = {}
        self.periods = empty_periods()
        self.call_periods = empty_periods()
        self.cost_periods = empty_periods()
        self.seen_packed = b""
        self.seen: set[bytes] = set()
        self.cached_files: dict[str, dict] = {}
        self.legacy_cached_files: dict[str, dict] = {}
        self.path_name_counts: Counter = Counter()
        self.session_models: dict[str, str] = {}
        self.session_parents: dict[str, str] = {}
        self.model_resolver: Callable[[str], str] = lambda model: model
        self.pending_usage: dict[str, list[CodexPendingUsage]] = {}
        self.pending_fingerprints: set[bytes] = set()
        self.cache_dirty = False
        self.last_event: datetime | None = None
        self.errors = 0
        self.cache_errors = 0
        self.next_fallback_check = 0.0
        self.rebuild_required = False
        self._load_cache()
        self._discover_startup()
        if self.rebuild_required:
            self._rebuild_all()

    @staticmethod
    def _known_model(model: str | None) -> bool:
        return bool(model and model != "<unknown>")

    def _resolve_session_model(
        self,
        session_id: str,
        visited: set[str] | None = None,
    ) -> str | None:
        if not session_id:
            return None
        model = self.session_models.get(session_id)
        if self._known_model(model):
            return model
        visited = set() if visited is None else visited
        if session_id in visited:
            return None
        visited.add(session_id)
        parent_id = self.session_parents.get(session_id, "")
        if not parent_id:
            return None
        model = self._resolve_session_model(parent_id, visited)
        if model:
            self.session_models[session_id] = model
        return model

    def _resolve_lineage_root(self, session_id: str) -> str:
        current_id = str(session_id or "")
        if not current_id:
            return ""
        visited = set()
        while current_id not in visited:
            visited.add(current_id)
            parent_id = self.session_parents.get(current_id, "")
            if not parent_id:
                return current_id
            current_id = parent_id
        return min(visited)

    def _register_state_model(self, state: CodexFileState) -> None:
        if not state.session_id:
            return
        if state.parent_session_id:
            self.session_parents[state.session_id] = state.parent_session_id
        if self._known_model(state.model):
            self.session_models[state.session_id] = state.model
        inherited = self._resolve_session_model(state.session_id)
        if inherited and not self._known_model(state.model):
            state.model = inherited
        self._propagate_resolved_models()
        self._flush_pending_usage()

    def _propagate_resolved_models(self) -> None:
        for state in self.states.values():
            model = self._resolve_session_model(state.session_id)
            if model and not self._known_model(state.model):
                state.model = model
        for record in self.cached_files.values():
            session_id = str(record.get("session_id") or "")
            model = self._resolve_session_model(session_id)
            if model and not self._known_model(str(record.get("model") or "")):
                record["model"] = model
                self.cache_dirty = True

    def _add_resolved_usage(self, model: str, pending: CodexPendingUsage) -> None:
        resolved_model = str(self.model_resolver(model) or model).strip() or model
        key = ("Codex", resolved_model)
        event_date = pending.event_time.astimezone(SHANGHAI).date()
        add_period_usage(self.periods, key, pending.total_tokens, event_date)
        add_period_usage(self.call_periods, key, 1, event_date)
        cost_usd = usage_cost_usd(
            resolved_model,
            pending.usage,
            source="codex",
            prices=self.prices,
            context_window=pending.context_window,
            event_time=pending.event_time,
            include_promotions=True,
        )
        if cost_usd is not None:
            add_period_cost(self.cost_periods, key, cost_usd, event_date)
        self.last_event = (
            max(self.last_event, pending.event_time)
            if self.last_event
            else pending.event_time
        )

    @staticmethod
    def _remap_periods(
        periods: dict[str, Counter],
        resolver: Callable[[str], str],
    ) -> dict[str, Counter]:
        remapped = empty_periods()
        for period in PERIODS:
            for (platform, model), value in periods[period].items():
                resolved_model = str(resolver(model) or model).strip() or model
                remapped[period][(platform, resolved_model)] += value
        return remapped

    def set_model_resolver(self, resolver: Callable[[str], str] | None) -> None:
        """Apply a model mapping without changing any usage quantities."""
        self.model_resolver = resolver or (lambda model: model)
        changed = False
        for state in self.states.values():
            if not self._known_model(state.model):
                continue
            resolved_model = str(self.model_resolver(state.model) or state.model).strip()
            if resolved_model and resolved_model != state.model:
                state.model = resolved_model
                changed = True
            if state.session_id and self.session_models.get(state.session_id) != state.model:
                self.session_models[state.session_id] = state.model
                changed = True
        for record in self.cached_files.values():
            model = str(record.get("model") or "")
            if not self._known_model(model):
                continue
            resolved_model = str(self.model_resolver(model) or model).strip()
            if resolved_model and resolved_model != model:
                record["model"] = resolved_model
                changed = True
        for session_id, model in list(self.session_models.items()):
            if not self._known_model(model):
                continue
            resolved_model = str(self.model_resolver(model) or model).strip()
            if resolved_model and resolved_model != model:
                self.session_models[session_id] = resolved_model
                changed = True
        remapped_periods = self._remap_periods(self.periods, self.model_resolver)
        remapped_calls = self._remap_periods(
            self.call_periods,
            self.model_resolver,
        )
        remapped_costs = self._remap_periods(
            self.cost_periods,
            self.model_resolver,
        )
        if (
            changed
            or remapped_periods != self.periods
            or remapped_calls != self.call_periods
            or remapped_costs != self.cost_periods
        ):
            self.periods = remapped_periods
            self.call_periods = remapped_calls
            self.cost_periods = remapped_costs
            self.cache_dirty = True
        self._flush_pending_usage()

    def _flush_pending_usage(self) -> None:
        for session_id in list(self.pending_usage):
            model = self._resolve_session_model(session_id)
            if not model:
                continue
            entries = self.pending_usage.pop(session_id)
            for pending in entries:
                self.pending_fingerprints.discard(pending.fingerprint)
                if self._has_fingerprint(pending.fingerprint):
                    continue
                self.seen.add(pending.fingerprint)
                self._add_resolved_usage(model, pending)
                self.cache_dirty = True

    def _cache_key(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path.resolve())

    def _load_cache(self) -> None:
        try:
            cache_date = datetime.fromtimestamp(
                self.cache_path.stat().st_mtime,
                SHANGHAI,
            ).date()
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            version = int(payload.get("version") or 0)
            if version not in (7, CODEX_CACHE_VERSION):
                return
            files = payload.get("files") or {}
            if not isinstance(files, dict):
                return
            encoded = str(payload.get("fingerprints_b64") or "")
            packed = base64.b64decode(encoded.encode("ascii")) if encoded else b""
            if len(packed) % 16:
                raise ValueError("invalid packed Codex fingerprints")
            self.seen_packed = packed
            decoded_files = {
                str(key): value
                for key, value in files.items()
                if isinstance(value, dict)
            }
            if version == CODEX_CACHE_VERSION:
                self.cached_files = decoded_files
            else:
                self.legacy_cached_files = decoded_files
                self.cache_dirty = True
            if str(payload.get("since") or "") == self.since.isoformat():
                self.periods = ClaudeTailTracker._decode_periods(
                    payload.get("periods")
                )
                self.call_periods = ClaudeTailTracker._decode_periods(
                    payload.get("call_periods")
                )
                self.cost_periods = ClaudeTailTracker._decode_periods(
                    payload.get("cost_periods"), float
                )
                cached_date = cached_period_date(payload, cache_date)
                current_date = datetime.now(SHANGHAI).date()
                reset = rollover_periods(
                    self.periods,
                    cached_date,
                    current_date,
                )
                rollover_periods(
                    self.call_periods,
                    cached_date,
                    current_date,
                )
                rollover_periods(
                    self.cost_periods,
                    cached_date,
                    current_date,
                )
                if reset:
                    self.cache_dirty = True
                last_event = payload.get("last_event")
                self.last_event = (
                    parse_time(last_event).astimezone(timezone.utc)
                    if last_event
                    else None
                )
            else:
                self.seen_packed = b""
                self.seen.clear()
                self.cache_dirty = True
        except FileNotFoundError:
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.cache_errors += 1

    def _save_cache(self) -> None:
        if not self.cache_dirty:
            return
        self._compact_fingerprints()
        payload = {
            "version": CODEX_CACHE_VERSION,
            "updated_at": datetime.now(SHANGHAI).isoformat(),
            "period_date": datetime.now(SHANGHAI).date().isoformat(),
            "since": self.since.isoformat(),
            "fingerprints_b64": base64.b64encode(
                self.seen_packed
            ).decode("ascii"),
            "files": self.cached_files,
            "periods": ClaudeTailTracker._encode_periods(self.periods),
            "call_periods": ClaudeTailTracker._encode_periods(self.call_periods),
            "cost_periods": ClaudeTailTracker._encode_periods(
                self.cost_periods, float
            ),
            "last_event": self.last_event.isoformat() if self.last_event else None,
        }
        temporary_path = self.cache_path.with_suffix(".tmp")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.cache_path)
            self.cache_dirty = False
        except OSError:
            self.cache_errors += 1
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _has_fingerprint(self, fingerprint: bytes) -> bool:
        if fingerprint in self.seen:
            return True
        low = 0
        high = len(self.seen_packed) // 16
        while low < high:
            middle = (low + high) // 2
            value = self.seen_packed[middle * 16 : (middle + 1) * 16]
            if value < fingerprint:
                low = middle + 1
            else:
                high = middle
        return (
            low < len(self.seen_packed) // 16
            and self.seen_packed[low * 16 : (low + 1) * 16] == fingerprint
        )

    def _compact_fingerprints(self) -> None:
        if not self.seen:
            return
        existing = [
            self.seen_packed[index : index + 16]
            for index in range(0, len(self.seen_packed), 16)
        ]
        self.seen_packed = b"".join(sorted(set(existing) | self.seen))
        self.seen.clear()

    def fingerprint_count(self) -> int:
        return len(self.seen_packed) // 16 + len(self.seen)

    def _state_from_cache(
        self,
        path: Path,
        stat: os.stat_result,
        startup_cold: bool,
    ) -> tuple[CodexFileState, bool]:
        cache_key = self._cache_key(path)
        record = self.cached_files.get(cache_key) or {}
        if (
            not record
            and self.path_name_counts[path.name] == 1
            and path.name in self.legacy_cached_files
        ):
            record = self.legacy_cached_files[path.name]
            self.cached_files[cache_key] = record
            self.cache_dirty = True
        cached_size = int(record.get("size") or 0)
        cached_mtime_ns = int(record.get("mtime_ns") or 0)
        cached_offset = int(record.get("offset") or 0)
        exact = (
            cached_size == stat.st_size
            and cached_mtime_ns == stat.st_mtime_ns
            and cached_offset == stat.st_size
            and self._known_model(str(record.get("model") or ""))
        )
        offset = cached_offset
        if offset < 0 or offset > stat.st_size:
            offset = 0
        if not exact and stat.st_size == cached_size:
            offset = 0
        remainder = b""
        encoded_remainder = record.get("remainder")
        if offset and isinstance(encoded_remainder, str):
            try:
                remainder = base64.b64decode(encoded_remainder.encode("ascii"))
            except (ValueError, UnicodeEncodeError):
                remainder = b""
        state = CodexFileState(
            offset=offset,
            remainder=remainder,
            model=str(record.get("model") or "<unknown>"),
            session_id=str(record.get("session_id") or ""),
            parent_session_id=str(record.get("parent_session_id") or ""),
            last_mtime=stat.st_mtime,
            last_mtime_ns=int(record.get("mtime_ns") or stat.st_mtime_ns),
            last_size=stat.st_size if exact else offset,
            file_dev=int(record.get("dev") or getattr(stat, "st_dev", 0)),
            file_ino=int(record.get("ino") or getattr(stat, "st_ino", 0)),
            watching=not startup_cold,
            stop_after_initial=startup_cold,
        )
        return state, exact

    def _remember_file(
        self,
        path: Path,
        state: CodexFileState,
        stat: os.stat_result,
    ) -> None:
        record = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "dev": int(getattr(stat, "st_dev", 0)),
            "ino": int(getattr(stat, "st_ino", 0)),
            "offset": state.offset,
            "session_id": state.session_id,
            "parent_session_id": state.parent_session_id,
            "model": state.model,
            "remainder": base64.b64encode(state.remainder).decode("ascii")
            if state.remainder
            else "",
        }
        key = self._cache_key(path)
        if self.cached_files.get(key) != record:
            self.cached_files[key] = record
            self.cache_dirty = True

    def _paths(self) -> list[Path]:
        paths = []
        for folder_name in ("sessions", "archived_sessions"):
            folder = self.root / folder_name
            if not folder.exists():
                continue
            for path in folder.rglob("*.jsonl"):
                paths.append(path)
        return sorted(paths, key=lambda path: path.name)

    def _prime_session_metadata(self, path: Path, state: CodexFileState) -> None:
        """Read only session metadata so lineage is complete before token replay."""
        try:
            with path.open("rb") as handle:
                for _ in range(30):
                    raw_line = handle.readline()
                    if not raw_line:
                        break
                    try:
                        event = json.loads(raw_line.decode("utf-8", errors="replace"))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if event.get("type") != "session_meta":
                        continue
                    payload = event.get("payload") or {}
                    state.session_id = str(payload.get("id") or state.session_id)
                    state.parent_session_id = (
                        codex_parent_session_id(payload) or state.parent_session_id
                    )
                    direct_model = str(payload.get("model") or "")
                    if self._known_model(direct_model):
                        state.model = direct_model
                    break
        except OSError:
            self.errors += 1

    def _discover_startup(self) -> None:
        entries = []
        paths = self._paths()
        self.path_name_counts = Counter(path.name for path in paths)
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                self.errors += 1
                continue
            startup_cold = stat.st_mtime < time.time() - STARTUP_HOT_SECONDS
            state, exact_cache_hit = self._state_from_cache(
                path,
                stat,
                startup_cold,
            )
            self.states[path] = state
            entries.append((path, state, exact_cache_hit))

        for path, state, exact_cache_hit in entries:
            if not exact_cache_hit and not state.session_id:
                self._prime_session_metadata(path, state)

        for _path, state, _exact_cache_hit in entries:
            self._register_state_model(state)

        for path, state, exact_cache_hit in entries:
            if exact_cache_hit:
                state.next_check = time.monotonic() + REFRESH_SECONDS
                continue
            self._read_path(path, state, initial=True)
        self._save_cache()

    def _discover_changes(self) -> set[Path]:
        changed: set[Path] = set()
        for path in self.watcher.drain():
            if path.suffix.lower() != ".jsonl":
                continue
            changed.add(path)
            state = self.states.get(path)
            if state is None:
                try:
                    stat = path.stat()
                    state, _exact_cache_hit = self._state_from_cache(
                        path,
                        stat,
                        startup_cold=False,
                    )
                except OSError:
                    state = CodexFileState()
                self.states[path] = state
            state.watching = True
            state.stop_after_initial = False
            state.next_check = 0.0
        return changed

    def _resync_paths(self) -> set[Path]:
        """Reconcile once after native notifications may have been lost."""
        changed: set[Path] = set()
        current_paths = set(self._paths())
        for path in current_paths:
            try:
                stat = path.stat()
            except OSError:
                self.errors += 1
                continue
            state = self.states.get(path)
            if state is None:
                state, _exact_cache_hit = self._state_from_cache(
                    path,
                    stat,
                    startup_cold=False,
                )
                self.states[path] = state
                changed.add(path)
            elif state.last_size != stat.st_size or state.last_mtime != stat.st_mtime:
                changed.add(path)
            if path in changed:
                state.watching = True
                state.stop_after_initial = False
                state.next_check = 0.0
        removed = set(self.states) - current_paths
        for path in removed:
            del self.states[path]
        if removed:
            self.rebuild_required = True
        return changed

    def _consume(self, data: bytes, state: CodexFileState, initial: bool) -> None:
        data = state.remainder + data
        lines = data.split(b"\n")
        state.remainder = lines.pop() if data and not data.endswith(b"\n") else b""
        for raw_line in lines:
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (TypeError, json.JSONDecodeError):
                self.errors += 1
                continue
            payload = event.get("payload") or {}
            if event.get("type") == "session_meta":
                state.session_id = str(payload.get("id") or state.session_id)
                state.parent_session_id = (
                    codex_parent_session_id(payload) or state.parent_session_id
                )
                direct_model = str(payload.get("model") or "")
                if self._known_model(direct_model):
                    state.model = direct_model
                self._register_state_model(state)
                continue
            if event.get("type") == "turn_context":
                state.model = str(payload.get("model") or state.model)
                self._register_state_model(state)
                continue
            if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            usage = info.get("last_token_usage")
            if not isinstance(usage, dict):
                continue
            try:
                total_tokens = nonnegative_int(
                    usage.get("total_tokens") or 0,
                    "total_tokens",
                )
                if not total_tokens:
                    total_tokens = nonnegative_int(
                        usage.get("input_tokens") or 0,
                        "input_tokens",
                    ) + nonnegative_int(
                        usage.get("output_tokens") or 0,
                        "output_tokens",
                    )
            except ValueError:
                self.errors += 1
                continue
            if total_tokens <= 0:
                continue
            fingerprint = codex_fingerprint_digest(
                codex_usage_fingerprint(
                    self._resolve_lineage_root(state.session_id),
                    event.get("timestamp"),
                    info,
                )
            )
            if self._has_fingerprint(fingerprint) or fingerprint in self.pending_fingerprints:
                continue
            try:
                event_time = parse_time(event.get("timestamp")).astimezone(timezone.utc)
            except (TypeError, ValueError):
                self.errors += 1
                continue
            if event_time <= self.since:
                self.seen.add(fingerprint)
                self.cache_dirty = True
                continue
            try:
                context_window = nonnegative_int(
                    info.get("model_context_window") or 0,
                    "model_context_window",
                )
            except ValueError:
                self.errors += 1
                context_window = 0
            pending = CodexPendingUsage(
                fingerprint=fingerprint,
                session_id=state.session_id,
                total_tokens=total_tokens,
                usage=usage,
                context_window=context_window,
                event_time=event_time,
            )
            model = (
                state.model
                if self._known_model(state.model)
                else self._resolve_session_model(state.session_id)
            )
            if not model:
                self.pending_usage.setdefault(state.session_id, []).append(pending)
                self.pending_fingerprints.add(fingerprint)
                continue
            state.model = model
            self.session_models[state.session_id] = model
            self.seen.add(fingerprint)
            if len(self.seen) >= FINGERPRINT_COMPACT_THRESHOLD:
                self._compact_fingerprints()
            self.cache_dirty = True
            self._add_resolved_usage(model, pending)

    def _read_path(
        self,
        path: Path,
        state: CodexFileState,
        initial: bool = False,
        now: float | None = None,
    ) -> None:
        now = time.monotonic() if now is None else now
        if not initial and not state.watching:
            return
        if not initial and now < state.next_check:
            return
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            device = int(getattr(stat, "st_dev", 0))
            inode = int(getattr(stat, "st_ino", 0))
            file_replaced = bool(
                state.offset
                and (
                    (state.file_dev and device != state.file_dev)
                    or (state.file_ino and inode and inode != state.file_ino)
                )
            )
            if size < state.offset or file_replaced:
                self.rebuild_required = True
                return
            if (
                size == state.offset
                and state.last_mtime_ns
                and stat.st_mtime_ns != state.last_mtime_ns
            ):
                self.rebuild_required = True
                return
            state.last_size = size
            state.last_mtime = mtime
            state.last_mtime_ns = stat.st_mtime_ns
            state.file_dev = device
            state.file_ino = inode
            if size == state.offset:
                if initial and state.stop_after_initial:
                    state.watching = False
                state.next_check = now + REFRESH_SECONDS
                self._remember_file(path, state, stat)
                return
            with path.open("rb") as handle:
                handle.seek(state.offset)
                data = handle.read()
            state.offset = size
            state.next_check = now + REFRESH_SECONDS
            self._consume(data, state, initial)
            self._remember_file(path, state, stat)
            if initial and state.stop_after_initial:
                state.watching = False
        except FileNotFoundError:
            if state.offset:
                state.watching = False
                self.rebuild_required = True
            else:
                state.next_check = now + REFRESH_SECONDS
        except OSError:
            self.errors += 1

    def _rebuild_all(self) -> None:
        """Rebuild this source once after a notified historical rewrite."""
        self.states.clear()
        self.periods = empty_periods()
        self.call_periods = empty_periods()
        self.cost_periods = empty_periods()
        self.seen_packed = b""
        self.seen.clear()
        self.cached_files.clear()
        self.session_models.clear()
        self.session_parents.clear()
        self.pending_usage.clear()
        self.pending_fingerprints.clear()
        self.last_event = None
        self.cache_dirty = True
        self.rebuild_required = False
        self._discover_startup()

    def poll(self) -> None:
        changed = self._discover_changes()
        now = time.monotonic()
        resync_required = self.watcher.consume_resync_required()
        if resync_required:
            changed.update(self._resync_paths())
        if self.watcher.available or resync_required:
            paths = changed
        elif now >= self.next_fallback_check:
            paths = self._resync_paths()
            self.next_fallback_check = now + FALLBACK_RESCAN_SECONDS
        else:
            paths = set()
        for path in paths:
            state = self.states.get(path)
            if state is None:
                continue
            self._read_path(path, state, now=now)
            if self.rebuild_required:
                break
        if self.rebuild_required:
            self._rebuild_all()

    def close(self) -> None:
        self._save_cache()
        if self._owns_watcher:
            self.watcher.close()


def _claude_cached_periods(
    projects_root: Path,
    boundary: datetime,
) -> dict[str, Counter]:
    periods = empty_periods()
    if not projects_root.exists():
        return periods
    now_date = datetime.now(SHANGHAI).date()
    month_start = now_date.replace(day=1)
    threshold = datetime.combine(
        month_start,
        datetime.min.time(),
        tzinfo=SHANGHAI,
    ).timestamp() - 5
    messages: dict[tuple[str, str, str], tuple[datetime, int]] = {}
    for path in projects_root.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < threshold:
                continue
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = event.get("message") or {}
                    usage = message.get("usage")
                    if event.get("type") != "assistant" or not isinstance(usage, dict):
                        continue
                    model = str(message.get("model") or "<unknown>")
                    if model == "<synthetic>":
                        continue
                    try:
                        event_time = parse_time(event.get("timestamp")).astimezone(
                            SHANGHAI
                        )
                    except (TypeError, ValueError):
                        continue
                    if event_time >= boundary or event_time.date() < month_start:
                        continue
                    cached_tokens = int(
                        usage.get("cache_read_input_tokens") or 0
                    ) + int(usage.get("cache_creation_input_tokens") or 0)
                    if cached_tokens <= 0:
                        continue
                    fingerprint = (
                        str(event.get("sessionId") or path),
                        str(message.get("id") or event.get("uuid") or "<unknown>"),
                        model,
                    )
                    previous = messages.get(fingerprint)
                    if previous is None or event_time >= previous[0]:
                        messages[fingerprint] = (event_time, cached_tokens)
        except OSError:
            continue
    for fingerprint, (event_time, cached_tokens) in messages.items():
        key = ("Claude Code", fingerprint[2])
        for period in active_periods(event_time.date(), now_date):
            if period != "cumulative":
                periods[period][key] += cached_tokens
    return periods


def _parse_claude_usage(stats_path: Path) -> tuple[dict[str, Counter], str, datetime]:
    periods = empty_periods()
    if not stats_path.exists():
        boundary = datetime.now(SHANGHAI).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return periods, "Claude stats-cache 不存在", boundary
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    for model, usage in (stats.get("modelUsage") or {}).items():
        if not isinstance(usage, dict):
            continue
        try:
            periods["cumulative"][("Claude Code", str(model))] = sum(
                nonnegative_int(usage.get(field) or 0, field)
                for field in (
                    "inputTokens",
                    "outputTokens",
                    "cacheReadInputTokens",
                    "cacheCreationInputTokens",
                )
            )
        except ValueError:
            continue
    last_daily_date: date | None = None
    for row in stats.get("dailyModelTokens", []):
        try:
            row_date = date.fromisoformat(row["date"])
        except (KeyError, ValueError):
            continue
        last_daily_date = max(last_daily_date, row_date) if last_daily_date else row_date
        for model, tokens in (row.get("tokensByModel") or {}).items():
            try:
                parsed_tokens = nonnegative_int(tokens or 0, "tokensByModel")
            except ValueError:
                continue
            key = ("Claude Code", str(model))
            for period in active_periods(row_date):
                if period != "cumulative":
                    periods[period][key] += parsed_tokens
    last_date_text = stats.get("lastComputedDate")
    if last_daily_date is not None:
        boundary = datetime.combine(
            last_daily_date + timedelta(days=1),
            datetime.min.time(),
            tzinfo=SHANGHAI,
        )
    elif last_date_text:
        boundary = datetime.combine(
            date.fromisoformat(last_date_text) + timedelta(days=1),
            datetime.min.time(),
            tzinfo=SHANGHAI,
        )
    else:
        boundary = datetime.now(SHANGHAI).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    cached_periods = _claude_cached_periods(stats_path.parent / "projects", boundary)
    for period in ("today", "week", "month"):
        periods[period].update(cached_periods[period])
    return (
        periods,
        f"Claude 含缓存：日数据至 {(last_daily_date.isoformat() if last_daily_date else last_date_text) or '未知日期'}",
        boundary,
    )


class ClaudeUsageCache:
    def __init__(self):
        self.stats_path = Path.home() / ".claude" / "stats-cache.json"
        self.last_signature: tuple[float, int] | None = None
        self.cached: tuple[dict[str, Counter], str, datetime] | None = None
        self.period_date: date | None = None
        self.next_check = 0.0

    def read(self) -> tuple[dict[str, Counter], str, datetime]:
        now = time.monotonic()
        current_date = datetime.now(SHANGHAI).date()
        if (
            self.cached is not None
            and current_date == self.period_date
            and now < self.next_check
        ):
            return self.cached
        self.next_check = now + REFERENCE_FILE_CHECK_SECONDS
        try:
            stat = self.stats_path.stat()
            signature = (stat.st_mtime, stat.st_size)
        except OSError:
            signature = (0.0, 0)
        if (
            self.cached is None
            or signature != self.last_signature
            or current_date != self.period_date
        ):
            try:
                parsed = _parse_claude_usage(self.stats_path)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                if self.cached is None:
                    boundary = datetime.now(SHANGHAI).replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    self.cached = (
                        empty_periods(),
                        f"Claude stats-cache 无效：{type(exc).__name__}",
                        boundary,
                    )
                    self.period_date = current_date
                return self.cached
            self.cached = parsed
            self.last_signature = signature
            self.period_date = current_date
        return self.cached


@dataclass
class ClaudeFileState:
    offset: int = 0
    remainder: bytes = b""
    last_mtime: float = 0.0
    last_mtime_ns: int = 0
    last_size: int = 0
    file_dev: int = 0
    file_ino: int = 0
    next_check: float = 0.0
    watching: bool = True
    stop_after_initial: bool = False


class ClaudeTailTracker:
    def __init__(
        self,
        since: datetime,
        track_tokens: bool = True,
        watcher: DirectoryChangeWatcher | None = None,
        call_since: datetime | None = None,
        cost_since: datetime | None = None,
        cache_path: Path | None = None,
        prices: dict[str, dict[str, float]] | None = None,
    ):
        self.since = since.astimezone(timezone.utc)
        self.call_since = (call_since or since).astimezone(timezone.utc)
        self.cost_since = (cost_since or since).astimezone(timezone.utc)
        self.scan_since = min(self.since, self.call_since, self.cost_since)
        self.track_tokens = track_tokens
        self.root = Path.home() / ".claude" / "projects"
        self.cache_path = cache_path or (
            Path.home() / ".tokenwatcher" / "claude_tail_cache.json"
        )
        self._owns_watcher = watcher is None
        self.watcher = watcher or DirectoryChangeWatcher(self.root)
        self.prices = prices or DEFAULT_PRICES
        self.states: dict[Path, ClaudeFileState] = {}
        self.periods = empty_periods()
        self.call_periods = empty_periods()
        self.cost_periods = empty_periods()
        self.seen: set[bytes] = set()
        self.cached_files: dict[str, dict] = {}
        self.cache_dirty = False
        self.last_event: datetime | None = None
        self.errors = 0
        self.cache_errors = 0
        self.next_fallback_check = 0.0
        self.rebuild_required = False
        self._load_cache()
        self._discover_startup()
        if self.rebuild_required:
            self._rebuild_all()
        self._save_cache()

    @staticmethod
    def _encode_periods(
        periods: dict[str, Counter],
        coerce=int,
    ) -> dict[str, list[dict]]:
        return {
            period: [
                {"platform": key[0], "model": key[1], "value": coerce(value)}
                for key, value in sorted(periods[period].items())
            ]
            for period in PERIODS
        }

    @staticmethod
    def _decode_periods(payload: object, coerce=int) -> dict[str, Counter]:
        periods = empty_periods()
        if not isinstance(payload, dict):
            return periods
        for period in PERIODS:
            for row in payload.get(period) or []:
                if not isinstance(row, dict):
                    continue
                key = (str(row.get("platform") or "<unknown>"), str(row.get("model") or "<unknown>"))
                periods[period][key] = coerce(row.get("value") or 0)
        return periods

    def _load_cache(self) -> None:
        try:
            cache_date = datetime.fromtimestamp(
                self.cache_path.stat().st_mtime,
                SHANGHAI,
            ).date()
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            version = int(payload.get("version") or 0)
            if version not in (4, 5, CLAUDE_CACHE_VERSION):
                return
            if str(payload.get("token_since") or "") != self.since.isoformat():
                return
            if str(payload.get("call_since") or "") != self.call_since.isoformat():
                return
            if str(payload.get("cost_since") or "") != self.cost_since.isoformat():
                return
            if bool(payload.get("track_tokens", True)) != self.track_tokens:
                return
            self.periods = self._decode_periods(payload.get("periods"))
            self.call_periods = self._decode_periods(payload.get("call_periods"))
            self.cost_periods = self._decode_periods(
                payload.get("cost_periods"), float
            )
            cached_date = cached_period_date(payload, cache_date)
            current_date = datetime.now(SHANGHAI).date()
            reset = rollover_periods(
                self.periods,
                cached_date,
                current_date,
            )
            rollover_periods(
                self.call_periods,
                cached_date,
                current_date,
            )
            rollover_periods(
                self.cost_periods,
                cached_date,
                current_date,
            )
            if reset:
                self.cache_dirty = True
            if version == CLAUDE_CACHE_VERSION:
                encoded_seen = str(payload.get("seen_b64") or "")
                packed_seen = (
                    base64.b64decode(encoded_seen.encode("ascii"))
                    if encoded_seen
                    else b""
                )
                if len(packed_seen) % 16:
                    raise ValueError("invalid packed Claude fingerprints")
                self.seen = {
                    packed_seen[index : index + 16]
                    for index in range(0, len(packed_seen), 16)
                }
            else:
                self.seen = {
                    codex_fingerprint_digest(tuple(str(value) for value in row))
                    for row in payload.get("seen") or []
                    if isinstance(row, list) and len(row) == 3
                }
                self.cache_dirty = True
            self.cached_files = {
                str(path): value
                for path, value in (payload.get("files") or {}).items()
                if isinstance(value, dict)
            }
            last_event = payload.get("last_event")
            self.last_event = parse_time(last_event).astimezone(timezone.utc) if last_event else None
        except (OSError, ValueError, TypeError, KeyError):
            self.cache_errors += 1

    def _save_cache(self) -> None:
        if not self.cache_dirty:
            return
        payload = {
            "version": CLAUDE_CACHE_VERSION,
            "token_since": self.since.isoformat(),
            "call_since": self.call_since.isoformat(),
            "cost_since": self.cost_since.isoformat(),
            "track_tokens": self.track_tokens,
            "period_date": datetime.now(SHANGHAI).date().isoformat(),
            "periods": self._encode_periods(self.periods),
            "call_periods": self._encode_periods(self.call_periods),
            "cost_periods": self._encode_periods(self.cost_periods, float),
            "seen_b64": base64.b64encode(b"".join(sorted(self.seen))).decode("ascii"),
            "last_event": self.last_event.isoformat() if self.last_event else None,
            "files": self.cached_files,
        }
        temporary_path = self.cache_path.with_name(
            f"{self.cache_path.name}.{os.getpid()}.tmp"
        )
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.cache_path)
            self.cache_dirty = False
        except OSError:
            self.cache_errors += 1
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _state_from_cache(self, cached: dict, startup_cold: bool) -> ClaudeFileState:
        try:
            remainder = base64.b64decode(str(cached.get("remainder") or ""))
        except (ValueError, TypeError):
            remainder = b""
        return ClaudeFileState(
            offset=int(cached.get("offset") or 0),
            remainder=remainder,
            last_mtime=float(cached.get("mtime") or 0.0),
            last_mtime_ns=int(cached.get("mtime_ns") or 0),
            last_size=int(cached.get("size") or 0),
            file_dev=int(cached.get("dev") or 0),
            file_ino=int(cached.get("ino") or 0),
            watching=not startup_cold,
            stop_after_initial=startup_cold,
        )

    def _remember_file(self, path: Path, state: ClaudeFileState, stat) -> None:
        entry = {
            "offset": state.offset,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "mtime_ns": stat.st_mtime_ns,
            "dev": int(getattr(stat, "st_dev", 0)),
            "ino": int(getattr(stat, "st_ino", 0)),
            "remainder": base64.b64encode(state.remainder).decode("ascii"),
        }
        key = str(path)
        if self.cached_files.get(key) != entry:
            self.cached_files[key] = entry
            self.cache_dirty = True

    def _discover_startup(self) -> None:
        if not self.root.exists():
            return
        threshold = self.scan_since.timestamp() - 5
        for path in self.root.rglob("*.jsonl"):
            try:
                stat = path.stat()
                if stat.st_mtime < threshold or path in self.states:
                    continue
            except OSError:
                continue
            startup_cold = stat.st_mtime < time.time() - STARTUP_HOT_SECONDS
            cached = self.cached_files.get(str(path))
            state = (
                self._state_from_cache(cached, startup_cold)
                if cached is not None
                else ClaudeFileState(stop_after_initial=startup_cold)
            )
            self.states[path] = state
            if cached is not None:
                exact = (
                    int(cached.get("size") or -1) == stat.st_size
                    and int(cached.get("mtime_ns") or -1) == stat.st_mtime_ns
                    and state.offset == stat.st_size
                )
                if exact:
                    state.last_size = stat.st_size
                    state.last_mtime = stat.st_mtime
                    state.last_mtime_ns = stat.st_mtime_ns
                    state.file_dev = int(getattr(stat, "st_dev", 0))
                    state.file_ino = int(getattr(stat, "st_ino", 0))
                    continue
                if stat.st_size <= state.offset:
                    state.offset = 0
                    state.remainder = b""
            self._read_path(path, state, initial=True)

    def _discover_changes(self) -> set[Path]:
        changed: set[Path] = set()
        for path in self.watcher.drain():
            if path.suffix.lower() != ".jsonl":
                continue
            changed.add(path)
            state = self.states.get(path)
            if state is None:
                state = ClaudeFileState()
                self.states[path] = state
            state.watching = True
            state.stop_after_initial = False
            state.next_check = 0.0
        return changed

    def _resync_paths(self) -> set[Path]:
        """Reconcile Claude logs once when directory notifications were lost."""
        changed: set[Path] = set()
        current_paths: set[Path] = set()
        threshold = self.scan_since.timestamp() - 5
        if self.root.exists():
            for path in self.root.rglob("*.jsonl"):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_mtime < threshold and path not in self.states:
                    continue
                current_paths.add(path)
                state = self.states.get(path)
                if state is None:
                    state = ClaudeFileState()
                    self.states[path] = state
                    changed.add(path)
                elif state.last_size != stat.st_size or state.last_mtime != stat.st_mtime:
                    changed.add(path)
                if path in changed:
                    state.watching = True
                    state.stop_after_initial = False
                    state.next_check = 0.0
        removed = set(self.states) - current_paths
        for path in removed:
            del self.states[path]
        if removed:
            self.rebuild_required = True
        return changed

    def _consume(self, data: bytes, state: ClaudeFileState) -> None:
        data = state.remainder + data
        lines = data.split(b"\n")
        state.remainder = lines.pop() if data and not data.endswith(b"\n") else b""
        for raw_line in lines:
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (TypeError, json.JSONDecodeError):
                self.errors += 1
                continue
            message = event.get("message") or {}
            usage = message.get("usage")
            if event.get("type") != "assistant" or not isinstance(usage, dict):
                continue
            model = str(message.get("model") or "<unknown>")
            if model == "<synthetic>":
                continue
            try:
                event_time = parse_time(event.get("timestamp")).astimezone(timezone.utc)
            except (TypeError, ValueError):
                self.errors += 1
                continue
            if event_time < self.scan_since:
                continue
            try:
                total_tokens = sum(
                    nonnegative_int(usage.get(field) or 0, field)
                    for field in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
            except ValueError:
                self.errors += 1
                continue
            fingerprint = codex_fingerprint_digest((
                str(event.get("sessionId") or "<unknown>"),
                str(message.get("id") or event.get("uuid") or "<unknown>"),
                model,
            ))
            if fingerprint in self.seen:
                continue
            self.seen.add(fingerprint)
            key = ("Claude Code", model)
            event_date = event_time.astimezone(SHANGHAI).date()
            if self.track_tokens and event_time >= self.since:
                add_period_usage(self.periods, key, total_tokens, event_date)
            if event_time >= self.call_since:
                add_period_usage(self.call_periods, key, 1, event_date)
            model_cost_since = (
                self.since
                if model.startswith(("claude-", "deepseek-"))
                else self.cost_since
            )
            if event_time >= model_cost_since:
                cost_usd = usage_cost_usd(
                    model,
                    usage,
                    source="claude",
                    prices=self.prices,
                    event_time=event_time,
                    include_promotions=True,
                )
                if cost_usd is not None:
                    add_period_cost(
                        self.cost_periods,
                        key,
                        cost_usd,
                        event_date,
                    )
            self.last_event = max(self.last_event, event_time) if self.last_event else event_time
            self.cache_dirty = True

    def _read_path(
        self,
        path: Path,
        state: ClaudeFileState,
        initial: bool = False,
        now: float | None = None,
    ) -> None:
        now = time.monotonic() if now is None else now
        if not initial and not state.watching:
            return
        if now < state.next_check:
            return
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            device = int(getattr(stat, "st_dev", 0))
            inode = int(getattr(stat, "st_ino", 0))
            file_replaced = bool(
                state.offset
                and (
                    (state.file_dev and device != state.file_dev)
                    or (state.file_ino and inode and inode != state.file_ino)
                )
            )
            if size < state.offset or file_replaced:
                self.rebuild_required = True
                return
            if (
                size == state.offset
                and state.last_mtime_ns
                and stat.st_mtime_ns != state.last_mtime_ns
            ):
                self.rebuild_required = True
                return
            state.last_size = size
            state.last_mtime = mtime
            state.last_mtime_ns = stat.st_mtime_ns
            state.file_dev = device
            state.file_ino = inode
            if size == state.offset:
                if initial and state.stop_after_initial:
                    state.watching = False
                state.next_check = now + REFRESH_SECONDS
                self._remember_file(path, state, stat)
                return
            with path.open("rb") as handle:
                handle.seek(state.offset)
                data = handle.read()
            state.offset = size
            state.next_check = now + REFRESH_SECONDS
            self._consume(data, state)
            self._remember_file(path, state, stat)
            if initial and state.stop_after_initial:
                state.watching = False
        except FileNotFoundError:
            if state.offset:
                state.watching = False
                self.rebuild_required = True
            else:
                state.next_check = now + REFRESH_SECONDS
        except OSError:
            self.errors += 1

    def _rebuild_all(self) -> None:
        """Rebuild this source once after a notified historical rewrite."""
        self.states.clear()
        self.periods = empty_periods()
        self.call_periods = empty_periods()
        self.cost_periods = empty_periods()
        self.seen.clear()
        self.cached_files.clear()
        self.last_event = None
        self.cache_dirty = True
        self.rebuild_required = False
        self._discover_startup()
        self._save_cache()

    def poll(self) -> None:
        changed = self._discover_changes()
        now = time.monotonic()
        resync_required = self.watcher.consume_resync_required()
        if resync_required:
            changed.update(self._resync_paths())
        if self.watcher.available or resync_required:
            paths = changed
        elif now >= self.next_fallback_check:
            paths = self._resync_paths()
            self.next_fallback_check = now + FALLBACK_RESCAN_SECONDS
        else:
            paths = set()
        for path in paths:
            state = self.states.get(path)
            if state is None:
                continue
            self._read_path(path, state, now=now)
            if self.rebuild_required:
                break
        if self.rebuild_required:
            self._rebuild_all()

    def close(self) -> None:
        self._save_cache()
        if self._owns_watcher:
            self.watcher.close()


def load_cline_tasks() -> dict[str, tuple[str, int, datetime]]:
    if not CLINE_HISTORY.exists():
        return {}
    data = json.loads(CLINE_HISTORY.read_text(encoding="utf-8"))
    if not isinstance(data, (dict, list)):
        raise ValueError("Cline taskHistory root must be an object or list")
    history = data if isinstance(data, list) else data.get("taskHistory") or []
    if not isinstance(history, list):
        raise ValueError("Cline taskHistory must be a list")
    tasks = {}
    for task in history:
        if not isinstance(task, dict):
            continue
        try:
            task_id = str(task.get("id") or task.get("ulid") or "<unknown>")
            model = str(task.get("modelId") or "<unknown>")
            total = nonnegative_int(task.get("tokensIn") or 0, "tokensIn")
            total += nonnegative_int(task.get("tokensOut") or 0, "tokensOut")
            timestamp_ms = nonnegative_int(task.get("ts") or 0, "ts")
            timestamp = datetime.fromtimestamp(
                timestamp_ms / 1000,
                timezone.utc,
            ).astimezone(SHANGHAI)
        except (OSError, OverflowError, ValueError):
            continue
        tasks[task_id] = (model, total, timestamp)
    return tasks


class ClineTaskCache:
    def __init__(self):
        self.last_signature: tuple[float, int] | None = None
        self.cached: dict[str, tuple[str, int, datetime]] = {}
        self.next_check = 0.0

    def read(self, force: bool = False) -> dict[str, tuple[str, int, datetime]]:
        now = time.monotonic()
        if not force and now < self.next_check:
            return dict(self.cached)
        self.next_check = now + REFERENCE_FILE_CHECK_SECONDS
        try:
            stat = CLINE_HISTORY.stat()
            signature = (stat.st_mtime, stat.st_size)
        except OSError:
            signature = (0.0, 0)
        if signature != self.last_signature:
            try:
                loaded = load_cline_tasks()
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return dict(self.cached)
            self.cached = loaded
            self.last_signature = signature
        return dict(self.cached)


class ClineRequestCounter:
    def __init__(
        self,
        since: datetime,
        watcher: DirectoryChangeWatcher | None = None,
    ):
        self.since = since.astimezone(SHANGHAI)
        self._owns_watcher = watcher is None
        self.watcher = watcher or DirectoryChangeWatcher(CLINE_HISTORY.parent.parent)
        self.states: dict[Path, tuple[tuple[float, int], dict[str, Counter]]] = {}
        self.known_paths: set[Path] = set()
        self.initialized = False
        self.periods = empty_periods()
        self.next_fallback_check = 0.0

    def _parse_path(self, path: Path, fallback_model: str) -> dict[str, Counter]:
        periods = empty_periods()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError):
            return periods
        messages = data if isinstance(data, list) else data.get("messages") or data.get("uiMessages") or []
        for event in messages:
            if event.get("type") != "say" or event.get("say") != "api_req_started":
                continue
            try:
                payload = json.loads(event.get("text") or "{}")
                if not any(metric in payload for metric in ("tokensIn", "tokensOut", "cacheReads", "cacheWrites")):
                    continue
                event_date = datetime.fromtimestamp(
                    int(event["ts"]) / 1000, timezone.utc
                ).astimezone(SHANGHAI)
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                continue
            if event_date <= self.since:
                continue
            model = str((event.get("modelInfo") or {}).get("modelId") or fallback_model)
            add_period_usage(periods, ("Cline", model), 1, event_date.date())
        return periods

    def _refresh_path(self, path: Path, fallback_model: str) -> None:
        try:
            stat = path.stat()
        except OSError:
            self.states.pop(path, None)
            return
        if stat.st_mtime <= self.since.timestamp():
            return
        signature = (stat.st_mtime, stat.st_size)
        previous = self.states.get(path)
        if previous is None or previous[0] != signature:
            self.states[path] = (signature, self._parse_path(path, fallback_model))

    def poll(self, tasks: dict[str, tuple[str, int, datetime]]) -> None:
        self.poll_changes(tasks, None)

    def poll_changes(
        self,
        tasks: dict[str, tuple[str, int, datetime]],
        changes: set[Path] | None,
    ) -> None:
        models_by_path: dict[Path, str] = {}
        timestamps_by_path: dict[Path, datetime] = {}
        for task_id, (model, _total, timestamp) in tasks.items():
            path = CLINE_TASKS / task_id / "ui_messages.json"
            models_by_path[path] = model
            timestamps_by_path[path] = timestamp
        active_paths = set(models_by_path)
        if not self.initialized:
            candidates = set(active_paths)
            self.initialized = True
        else:
            changed_paths = self.watcher.drain() if changes is None else changes
            candidates = {
                path
                for path in changed_paths
                if path.name.lower() == "ui_messages.json" and path in active_paths
            }
            candidates.update(active_paths - self.known_paths)
            now = time.monotonic()
            if not self.watcher.available and now >= self.next_fallback_check:
                self.next_fallback_check = now + REFERENCE_FILE_CHECK_SECONDS
                hot_boundary = datetime.now(SHANGHAI) - timedelta(
                    seconds=STARTUP_HOT_SECONDS
                )
                candidates.update(
                    path
                    for path, timestamp in timestamps_by_path.items()
                    if timestamp >= hot_boundary
                )
        for path in candidates:
            self._refresh_path(path, models_by_path[path])
        for path in set(self.states) - active_paths:
            del self.states[path]
        self.known_paths = active_paths
        combined = empty_periods()
        for _signature, path_periods in self.states.values():
            for period in PERIODS:
                combined[period].update(path_periods[period])
        self.periods = combined

    def roll_periods(self, previous_date: date, current_date: date) -> None:
        for _signature, path_periods in self.states.values():
            rollover_periods(path_periods, previous_date, current_date)
        rollover_periods(self.periods, previous_date, current_date)

    def close(self) -> None:
        if self._owns_watcher:
            self.watcher.close()


class ClinePoller:
    def __init__(self, baseline: Baseline):
        self.baseline_periods = {
            period: Counter(
                {
                    key: value
                    for key, value in baseline.periods[period].items()
                    if key[0] == "Cline"
                }
            )
            for period in PERIODS
        }
        self.baseline_call_periods = {
            period: Counter(
                {
                    key: value
                    for key, value in baseline.call_periods[period].items()
                    if key[0] == "Cline"
                }
            )
            for period in PERIODS
        }
        self.baseline_cost_periods = {
            period: Counter(
                {
                    key: value
                    for key, value in baseline.cost_periods[period].items()
                    if key[0] == "Cline"
                }
            )
            for period in PERIODS
        }
        self.report_time = baseline.refreshed_at.astimezone(SHANGHAI)
        self.task_cache = ClineTaskCache()
        self.initial_tasks = self.task_cache.read(force=True)
        initial_by_model = Counter()
        for model, total, _ in self.initial_tasks.values():
            initial_by_model[("Cline", model)] += total
        self.offsets = Counter()
        for key in set(initial_by_model) | set(self.baseline_periods["cumulative"]):
            self.offsets[key] = max(
                self.baseline_periods["cumulative"][key], initial_by_model[key]
            ) - initial_by_model[key]
        self.periods = {
            period: Counter(values)
            for period, values in self.baseline_periods.items()
        }
        self.request_counter = ClineRequestCounter(self.report_time)
        self.call_periods = {
            period: Counter(values)
            for period, values in self.baseline_call_periods.items()
        }
        self.cost_periods = {
            period: Counter(values)
            for period, values in self.baseline_cost_periods.items()
        }
        self.status = "Cline taskHistory 已载入"
        self.poll()

    def poll(self) -> None:
        changes = self.request_counter.watcher.drain()
        resync_required = self.request_counter.watcher.consume_resync_required()
        history_changed = CLINE_HISTORY in changes or resync_required
        current_tasks = self.task_cache.read(
            force=history_changed
        )
        if resync_required:
            changes.update(
                CLINE_TASKS / task_id / "ui_messages.json"
                for task_id in current_tasks
            )
        self.request_counter.poll_changes(current_tasks, changes)
        current_by_model = Counter()
        delta_periods = empty_periods()
        for task_id, (model, total, timestamp) in current_tasks.items():
            key = ("Cline", model)
            current_by_model[key] += total
            initial_total = self.initial_tasks.get(task_id, (model, 0, timestamp))[1]
            delta = max(0, total - initial_total)
            if delta:
                add_period_usage(delta_periods, key, delta, timestamp.date())
            if task_id not in self.initial_tasks and timestamp > self.report_time:
                add_period_usage(
                    delta_periods,
                    key,
                    max(0, total - delta),
                    timestamp.date(),
                )
        cumulative = Counter()
        for key in set(current_by_model) | set(self.baseline_periods["cumulative"]):
            cumulative[key] = current_by_model[key] + self.offsets[key]
        self.periods = {
            "cumulative": cumulative,
            "today": self.baseline_periods["today"] + delta_periods["today"],
            "week": self.baseline_periods["week"] + delta_periods["week"],
            "month": self.baseline_periods["month"] + delta_periods["month"],
        }
        self.call_periods = {
            period: self.baseline_call_periods[period]
            + self.request_counter.periods[period]
            for period in PERIODS
        }
        self.status = f"Cline 任务：{len(current_tasks)}"

    def roll_periods(self, previous_date: date, current_date: date) -> None:
        rollover_periods(
            self.baseline_periods,
            previous_date,
            current_date,
        )
        rollover_periods(
            self.baseline_call_periods,
            previous_date,
            current_date,
        )
        rollover_periods(
            self.baseline_cost_periods,
            previous_date,
            current_date,
        )
        rollover_periods(self.periods, previous_date, current_date)
        rollover_periods(self.call_periods, previous_date, current_date)
        rollover_periods(self.cost_periods, previous_date, current_date)
        self.request_counter.roll_periods(previous_date, current_date)
        current_tasks = self.task_cache.read(force=True)
        current_by_model = Counter()
        for model, total, _timestamp in current_tasks.values():
            current_by_model[("Cline", model)] += total
        cumulative = Counter(self.periods["cumulative"])
        self.initial_tasks = current_tasks
        self.offsets = Counter()
        for key in set(current_by_model) | set(cumulative):
            self.offsets[key] = cumulative[key] - current_by_model[key]


    def close(self) -> None:
        self.request_counter.close()


def _strip_yaml_inline_comment(value: str) -> str:
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
        if character == "#" and not quote and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[:index].rstrip()
    if quote:
        raise ValueError("unterminated quoted value in sub2api database config")
    return value.strip()


def load_sub2api_database_config(path: Path) -> dict[str, str]:
    """Read only the simple database mapping from sub2api's local YAML file."""
    values: dict[str, str] = {}
    inside_database = False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        if not inside_database:
            if re.fullmatch(r"database\s*:\s*", raw_line):
                inside_database = True
            continue
        if raw_line and not raw_line[0].isspace():
            break
        match = re.match(
            r"^\s+(host|port|user|password|dbname)\s*:\s*(.*?)\s*$",
            raw_line,
        )
        if not match:
            continue
        value = _strip_yaml_inline_comment(match.group(2))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[match.group(1)] = value
    missing = [name for name in ("host", "port", "user", "dbname") if not values.get(name)]
    if missing:
        raise ValueError(f"sub2api database config missing: {', '.join(missing)}")
    return values


class IncrementalDeepSeekApiPoller(Sub2ApiUsagePoller):
    """Configured incremental sub2api reader used by the live engine."""

    def __init__(
        self,
        config_path: Path | None = None,
        psql_path: Path | None = None,
        runner=None,
        prices: dict[str, dict[str, float]] | None = None,
        cache_path: Path | None = None,
        now=None,
    ) -> None:
        super().__init__(
            config_path or SUB2API_CONFIG,
            psql_path or SUB2API_PSQL,
            runner=runner,
            prices=prices or DEFAULT_PRICES,
            cache_path=cache_path,
            config_loader=load_sub2api_database_config,
            now=now,
        )


@dataclass(frozen=True)
class UsageSnapshot:
    periods: dict[str, dict[tuple[str, str], int]]
    call_periods: dict[str, dict[tuple[str, str], int]]
    updated_at: datetime
    report_time: datetime
    source_status: tuple[str, ...]
    cost_periods: dict[str, dict[tuple[str, str], float]] = field(
        default_factory=lambda: {period: {} for period in PERIODS}
    )
    error: str = ""

    def top(
        self,
        period: str,
        limit: int = DEFAULT_ROW_COUNT,
    ) -> list[tuple[tuple[str, str], int]]:
        values = self.periods.get(period, {})
        return sorted(
            values.items(),
            key=lambda item: (
                -item[1],
                item[0][0].casefold(),
                item[0][1].casefold(),
                item[0][0],
                item[0][1],
            ),
        )[: max(0, int(limit))]

    def call_count(self, period: str) -> int:
        return sum(self.call_periods.get(period, {}).values())


def usage_snapshot_signature(snapshot: UsageSnapshot) -> tuple:
    def normalized(values, coerce) -> tuple:
        return tuple(
            (
                period,
                tuple(
                    sorted(
                        (platform, model, coerce(value))
                        for (platform, model), value in values.get(period, {}).items()
                    )
                ),
            )
            for period in PERIODS
        )

    return (
        normalized(snapshot.periods, int),
        normalized(snapshot.call_periods, int),
        normalized(snapshot.cost_periods, float),
        snapshot.report_time.isoformat(),
    )


def usage_snapshot_to_json(snapshot: UsageSnapshot) -> dict:
    def encode(values, coerce) -> dict[str, list[dict]]:
        return {
            period: [
                {
                    "platform": platform,
                    "model": model,
                    "value": coerce(value),
                }
                for (platform, model), value in sorted(values.get(period, {}).items())
            ]
            for period in PERIODS
        }

    return {
        "periods": encode(snapshot.periods, int),
        "call_periods": encode(snapshot.call_periods, int),
        "cost_periods": encode(snapshot.cost_periods, float),
        "updated_at": snapshot.updated_at.isoformat(),
        "report_time": snapshot.report_time.isoformat(),
        "source_status": list(snapshot.source_status),
    }


def usage_snapshot_from_json(payload: dict) -> UsageSnapshot:
    def decode(name: str, coerce) -> dict:
        decoded = {period: {} for period in PERIODS}
        source = payload.get(name) or {}
        for period in PERIODS:
            for row in source.get(period) or []:
                key = (str(row["platform"]), str(row["model"]))
                decoded[period][key] = coerce(row["value"])
        return decoded

    return UsageSnapshot(
        periods=decode("periods", int),
        call_periods=decode("call_periods", int),
        cost_periods=decode("cost_periods", float),
        updated_at=parse_time(payload.get("updated_at")),
        report_time=parse_time(payload.get("report_time")),
        source_status=tuple(str(value) for value in payload.get("source_status") or ()),
    )


class UsageEngine:
    def __init__(
        self,
        report_dir: Path | None = None,
        snapshot_cache_path: Path | None = None,
    ):
        self.report_dir = report_dir or find_report_dir()
        self.prices = load_pricing(self.report_dir)
        self.snapshot_cache_path = snapshot_cache_path or (
            Path.home() / ".tokenwatcher" / "usage_snapshot_cache.json"
        )
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.snapshot: UsageSnapshot | None = None
        self.snapshot_cache_signature: tuple | None = None
        self.thread: threading.Thread | None = None
        self.baseline: Baseline | None = None
        self.codex: CodexTailTracker | None = None
        self.claude: ClaudeTailTracker | None = None
        self.claude_usage = ClaudeUsageCache()
        self.claude_boundary: datetime | None = None
        self.cline: ClinePoller | None = None
        self.dsh: DshTailTracker | None = None
        self.deepseek_api: IncrementalDeepSeekApiPoller | None = None
        self.source_warnings: list[str] = []
        self.period_date = datetime.now(SHANGHAI).date()
        self.next_report_check = 0.0
        self._load_snapshot_cache()
        if self.snapshot is None:
            self._load_report_preview()

    def _load_snapshot_cache(self) -> None:
        try:
            payload = json.loads(self.snapshot_cache_path.read_text(encoding="utf-8"))
            version = int(payload.get("version") or 0)
            if version not in (7, USAGE_SNAPSHOT_CACHE_VERSION):
                return
            cached_report_dir = Path(str(payload["report_dir"])).resolve()
            if cached_report_dir != self.report_dir.resolve():
                return
            snapshot = usage_snapshot_from_json(payload["snapshot"])
            snapshot_date = date.fromisoformat(str(payload["period_date"]))
        except (OSError, ValueError, TypeError, KeyError):
            return
        rollover_periods(
            snapshot.periods,
            snapshot_date,
            self.period_date,
        )
        rollover_periods(
            snapshot.call_periods,
            snapshot_date,
            self.period_date,
        )
        rollover_periods(
            snapshot.cost_periods,
            snapshot_date,
            self.period_date,
        )
        self.snapshot = snapshot
        self.snapshot_cache_signature = (
            usage_snapshot_signature(snapshot)
            if version == USAGE_SNAPSHOT_CACHE_VERSION
            else None
        )

    def _load_report_preview(self) -> None:
        try:
            baseline = load_baseline(self.report_dir)
        except (OSError, ValueError, TypeError, KeyError):
            return
        if not any(baseline.periods[period] for period in PERIODS):
            return
        self.snapshot = UsageSnapshot(
            periods={
                period: dict(baseline.periods[period]) for period in PERIODS
            },
            call_periods={
                period: dict(baseline.call_periods[period]) for period in PERIODS
            },
            cost_periods={
                period: dict(baseline.cost_periods[period]) for period in PERIODS
            },
            updated_at=baseline.refreshed_at.astimezone(SHANGHAI),
            report_time=baseline.refreshed_at.astimezone(SHANGHAI),
            source_status=("Baseline report preview; live sources are loading",),
        )

    def _save_snapshot_cache(self) -> None:
        snapshot = self.get_snapshot()
        if snapshot is None or snapshot.error:
            return
        signature = usage_snapshot_signature(snapshot)
        if signature == self.snapshot_cache_signature:
            return
        payload = {
            "version": USAGE_SNAPSHOT_CACHE_VERSION,
            "saved_at": datetime.now(SHANGHAI).isoformat(),
            "period_date": self.period_date.isoformat(),
            "report_dir": str(self.report_dir.resolve()),
            "snapshot": usage_snapshot_to_json(snapshot),
        }
        temporary_path = self.snapshot_cache_path.with_name(
            f"{self.snapshot_cache_path.name}.{os.getpid()}.tmp"
        )
        try:
            self.snapshot_cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.snapshot_cache_path)
            self.snapshot_cache_signature = signature
        except OSError:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _close_trackers(self) -> None:
        for name, tracker in (
            ("Codex", self.codex),
            ("Claude Code", self.claude),
            ("Cline", self.cline),
            ("DeepSeek Harness", self.dsh),
            ("Sub2API", self.deepseek_api),
        ):
            if tracker is None:
                continue
            try:
                tracker.close()
            except Exception as exc:
                self.source_warnings.append(
                    f"{name} 关闭失败，已跳过：{type(exc).__name__}"
                )

    def _reload(self) -> None:
        baseline = load_baseline(self.report_dir)
        self.prices = load_pricing(self.report_dir)
        self._close_trackers()
        self.source_warnings = list(baseline.warnings)
        self.baseline = baseline
        self.codex = None
        self.claude = None
        self.cline = None
        self.dsh = None
        self.deepseek_api = None

        def start_source(name: str, factory):
            try:
                return factory()
            except Exception as exc:
                self.source_warnings.append(
                    f"{name} 未检测到或初始化失败，已跳过：{type(exc).__name__}"
                )
                return None

        self.codex = start_source(
            "Codex",
            lambda: CodexTailTracker(
                self.baseline.refreshed_at,
                prices=self.prices,
            ),
        )

        def start_claude():
            _, _, boundary = self.claude_usage.read()
            self.claude_boundary = boundary
            return ClaudeTailTracker(
                boundary,
                call_since=self.baseline.refreshed_at,
                cost_since=self.baseline.refreshed_at,
                prices=self.prices,
            )

        self.claude = start_source("Claude Code", start_claude)
        self.cline = start_source("Cline", lambda: ClinePoller(self.baseline))
        self.dsh = start_source(
            "DeepSeek Harness",
            lambda: DshTailTracker(
                root=DSH_SESSIONS,
                watcher=DirectoryChangeWatcher(DSH_SESSIONS),
                prices=self.prices,
                excluded_providers=("sub2api",),
            ),
        )
        self.deepseek_api = start_source(
            "Sub2API",
            lambda: IncrementalDeepSeekApiPoller(prices=self.prices),
        )
        if self.codex is not None and self.deepseek_api is not None:
            try:
                self.codex.set_model_resolver(self.deepseek_api.resolve_model)
            except Exception as exc:
                self.source_warnings.append(
                    f"Sub2API 模型映射未应用，已跳过：{type(exc).__name__}"
                )

    def _roll_periods_if_needed(self, current_date: date) -> None:
        if current_date <= self.period_date:
            return
        previous_date = self.period_date
        if self.baseline is not None:
            rollover_periods(
                self.baseline.periods,
                previous_date,
                current_date,
            )
            rollover_periods(
                self.baseline.call_periods,
                previous_date,
                current_date,
            )
            rollover_periods(
                self.baseline.cost_periods,
                previous_date,
                current_date,
            )
        for tracker in (self.codex, self.claude):
            if tracker is None:
                continue
            rollover_periods(
                tracker.periods,
                previous_date,
                current_date,
            )
            rollover_periods(
                tracker.call_periods,
                previous_date,
                current_date,
            )
            rollover_periods(
                tracker.cost_periods,
                previous_date,
                current_date,
            )
            tracker.cache_dirty = True
        for name, tracker in (
            ("Cline", self.cline),
            ("DeepSeek Harness", self.dsh),
            ("Sub2API", self.deepseek_api),
        ):
            if tracker is None:
                continue
            try:
                tracker.roll_periods(previous_date, current_date)
            except Exception as exc:
                self.source_warnings.append(
                    f"{name} 日期切换失败，已跳过：{type(exc).__name__}"
                )
        snapshot = self.get_snapshot()
        if snapshot is not None:
            periods = {
                period: dict(snapshot.periods.get(period, {})) for period in PERIODS
            }
            call_periods = {
                period: dict(snapshot.call_periods.get(period, {}))
                for period in PERIODS
            }
            cost_periods = {
                period: dict(snapshot.cost_periods.get(period, {}))
                for period in PERIODS
            }
            rollover_periods(periods, previous_date, current_date)
            rollover_periods(call_periods, previous_date, current_date)
            rollover_periods(cost_periods, previous_date, current_date)
            rolled = UsageSnapshot(
                periods=periods,
                call_periods=call_periods,
                cost_periods=cost_periods,
                updated_at=snapshot.updated_at,
                report_time=snapshot.report_time,
                source_status=snapshot.source_status,
                error=snapshot.error,
            )
            with self.lock:
                if self.snapshot is snapshot:
                    self.snapshot = rolled
        self.period_date = current_date

    def refresh_once(self) -> UsageSnapshot:
        try:
            current_date = datetime.now(SHANGHAI).date()
            summary_path = self.report_dir / "summary.json"
            now = time.monotonic()
            if self.baseline is None or now >= self.next_report_check:
                try:
                    current_mtime = summary_path.stat().st_mtime
                except OSError:
                    current_mtime = 0.0
                self.next_report_check = now + REPORT_CHECK_SECONDS
            else:
                current_mtime = self.baseline.report_mtime
            if self.baseline is None or current_mtime != self.baseline.report_mtime:
                self._reload()
                self.period_date = current_date
            else:
                self._roll_periods_if_needed(current_date)
            assert self.baseline is not None
            pollers = (
                ("Codex", self.codex),
                ("Cline", self.cline),
                ("DeepSeek Harness", self.dsh),
                ("Sub2API", self.deepseek_api),
            )
            for name, tracker in pollers:
                if tracker is None:
                    continue
                try:
                    tracker.poll()
                except Exception as exc:
                    self.source_warnings.append(
                        f"{name} 读取失败，本次已跳过：{type(exc).__name__}"
                    )
            if self.codex is not None and self.deepseek_api is not None:
                try:
                    self.codex.set_model_resolver(self.deepseek_api.resolve_model)
                except Exception as exc:
                    self.source_warnings.append(
                        f"Sub2API 模型映射未应用，本次已跳过：{type(exc).__name__}"
                    )
            claude_periods = empty_periods()
            claude_status = "Claude Code：未检测到"
            claude_boundary = self.claude_boundary
            try:
                claude_periods, claude_status, claude_boundary = self.claude_usage.read()
                if self.claude is None or self.claude_boundary != claude_boundary:
                    if self.claude is not None:
                        self.claude.close()
                    self.claude = ClaudeTailTracker(
                        claude_boundary,
                        call_since=self.baseline.refreshed_at,
                        cost_since=self.baseline.refreshed_at,
                        prices=self.prices,
                    )
                    self.claude_boundary = claude_boundary
                if self.claude is not None:
                    self.claude.poll()
            except Exception as exc:
                self.source_warnings.append(
                    f"Claude Code 读取失败，本次已跳过：{type(exc).__name__}"
                )
                claude_periods = empty_periods()
                claude_status = "Claude Code：读取失败，已跳过"
            combined_periods = {}
            combined_call_periods = {}
            combined_cost_periods = {}
            for period in PERIODS:
                values = Counter(self.baseline.periods[period])
                if self.codex is not None:
                    values.update(self.codex.periods[period])
                if self.claude is not None:
                    for key in [key for key in values if key[0] == "Claude Code"]:
                        del values[key]
                    values.update(
                        claude_periods[period] + self.claude.periods[period]
                    )
                if self.cline is not None:
                    for key in [key for key in values if key[0] == "Cline"]:
                        del values[key]
                    values.update(self.cline.periods[period])
                if self.dsh is not None:
                    for key in [key for key in values if key[0] == "DeepSeek Harness"]:
                        del values[key]
                    values.update(self.dsh.periods[period])
                combined_periods[period] = dict(values)
                calls = Counter(self.baseline.call_periods[period])
                if self.codex is not None:
                    calls.update(self.codex.call_periods[period])
                if self.claude is not None:
                    calls.update(self.claude.call_periods[period])
                if self.cline is not None:
                    for key in [key for key in calls if key[0] == "Cline"]:
                        del calls[key]
                    calls.update(self.cline.call_periods[period])
                if self.dsh is not None:
                    for key in [key for key in calls if key[0] == "DeepSeek Harness"]:
                        del calls[key]
                    calls.update(self.dsh.call_periods[period])
                combined_call_periods[period] = dict(calls)
                costs = Counter(self.baseline.cost_periods[period])
                if self.codex is not None:
                    costs.update(self.codex.cost_periods[period])
                if self.claude is not None:
                    costs.update(self.claude.cost_periods[period])
                if self.cline is not None:
                    for key in [key for key in costs if key[0] == "Cline"]:
                        del costs[key]
                    costs.update(self.cline.cost_periods[period])
                if self.dsh is not None:
                    for key in [key for key in costs if key[0] == "DeepSeek Harness"]:
                        del costs[key]
                    costs.update(self.dsh.cost_periods[period])
                combined_cost_periods[period] = dict(costs)
            last_event = (
                self.codex.last_event.astimezone(SHANGHAI).strftime("%H:%M:%S")
                if self.codex is not None and self.codex.last_event
                else "无新增"
            )
            claude_last_event = (
                self.claude.last_event.astimezone(SHANGHAI).strftime("%m-%d %H:%M:%S")
                if self.claude is not None and self.claude.last_event
                else "无新增"
            )
            snapshot = UsageSnapshot(
                periods=combined_periods,
                call_periods=combined_call_periods,
                cost_periods=combined_cost_periods,
                updated_at=datetime.now(SHANGHAI),
                report_time=self.baseline.refreshed_at.astimezone(SHANGHAI),
                source_status=(
                    (
                        f"Codex 增量事件：{self.codex.fingerprint_count()}，最新 {last_event}"
                        if self.codex is not None
                        else "Codex：未检测到，已跳过"
                    ),
                    (
                        f"{claude_status}，尾读 {len(self.claude.seen)} 条，最新 {claude_last_event}"
                        if self.claude is not None
                        else claude_status
                    ),
                    self.cline.status if self.cline is not None else "Cline：未检测到，已跳过",
                    (
                        f"DeepSeek Harness：{self.dsh.status}，错误 {self.dsh.errors}"
                        if self.dsh is not None
                        else "DeepSeek Harness：未检测到，已跳过"
                    ),
                    (
                        self.deepseek_api.status
                        if self.deepseek_api is not None
                        else "Sub2API：未检测到，已跳过"
                    ),
                    *tuple(dict.fromkeys(self.source_warnings)),
                ),
            )
        except Exception as exc:
            previous = self.get_snapshot()
            snapshot = UsageSnapshot(
                periods=previous.periods if previous else {period: {} for period in PERIODS},
                call_periods=previous.call_periods
                if previous
                else {period: {} for period in PERIODS},
                cost_periods=previous.cost_periods
                if previous
                else {period: {} for period in PERIODS},
                updated_at=datetime.now(SHANGHAI),
                report_time=previous.report_time
                if previous
                else datetime(1970, 1, 1, tzinfo=SHANGHAI),
                source_status=previous.source_status if previous else (),
                error=f"{type(exc).__name__}: {exc}",
            )
        with self.lock:
            self.snapshot = snapshot
        return snapshot

    def _run(self) -> None:
        initial_cache_saved = False
        while not self.stop_event.is_set():
            started = time.monotonic()
            self.refresh_once()
            if not initial_cache_saved:
                self._save_snapshot_cache()
                initial_cache_saved = True
            remaining = REFRESH_SECONDS - (time.monotonic() - started)
            self.stop_event.wait(max(0.05, remaining))

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="usage-live")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.5)
        self._save_snapshot_cache()
        self._close_trackers()

    def get_snapshot(self) -> UsageSnapshot | None:
        with self.lock:
            return self.snapshot


class FloatingRankRow:
    def __init__(self, parent: tk.Widget, rank: int, transparent: str):
        self.frame = tk.Frame(parent, bg=transparent)
        self.frame.pack(fill="x", pady=1)
        self.frame.grid_columnconfigure(
            0,
            minsize=RANK_COLUMN_WIDTH + 2 + RANK_LEFT_SHIFT,
        )
        self.frame.grid_columnconfigure(1, minsize=MODEL_COLUMN_WIDTH + 3)
        self.frame.grid_columnconfigure(4, minsize=TOKEN_COLUMN_WIDTH)
        self.frame.grid_columnconfigure(5, minsize=COST_COLUMN_WIDTH, weight=1)
        self.rank_canvas = tk.Canvas(
            self.frame,
            bg=transparent,
            width=RANK_COLUMN_WIDTH,
            height=ROW_HEIGHT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.rank_canvas.grid(row=0, column=0, padx=(0, 2), sticky="w")
        self.rank_text = AdaptiveCanvasText(
            self.rank_canvas,
            text=str(rank),
            font_name=CASCADIA_MONO_FONT,
            font_size=BODY_FONT_SIZE,
            position=(2, ROW_MIDDLE),
            anchor="lm",
        )
        self.model_badge_canvas = tk.Canvas(
            self.frame,
            bg="#4C8DFF",
            width=MODEL_COLUMN_WIDTH + MODEL_CALL_LEFT_SHIFT,
            height=44,
            highlightthickness=0,
            borderwidth=0,
        )
        self.model_badge_canvas.place(
            x=(
                RANK_COLUMN_WIDTH
                + 2
                + RANK_LEFT_SHIFT
                - MODEL_CALL_LEFT_SHIFT
            ),
            y=(ROW_HEIGHT - 44) // 2,
        )
        self.model_badge_text_id = self.model_badge_canvas.create_text(
            (MODEL_COLUMN_WIDTH + MODEL_CALL_LEFT_SHIFT) // 2,
            22,
            text="等待数据",
            font=("Microsoft YaHei UI", -MODEL_BADGE_FONT_SIZE, "bold"),
            fill="#FFFFFF",
            anchor="center",
        )
        self.call_canvas = tk.Canvas(
            self.frame,
            width=CALL_COLUMN_WIDTH,
            height=ROW_HEIGHT,
            bg=transparent,
            highlightthickness=0,
            borderwidth=0,
        )
        self.call_canvas.grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, VALUE_COLUMN_GAP + MODEL_CALL_LEFT_SHIFT),
        )
        self.call_text = AdaptiveCanvasText(
            self.call_canvas,
            text="0",
            font_name=CASCADIA_MONO_FONT,
            font_size=BODY_FONT_SIZE,
            position=(2, ROW_MIDDLE),
            anchor="lm",
        )
        self.delta_canvas = tk.Canvas(
            self.frame,
            bg=transparent,
            width=DELTA_COLUMN_WIDTH,
            height=ROW_HEIGHT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.delta_canvas.grid(
            row=0,
            column=3,
            sticky="e",
            padx=(0, VALUE_COLUMN_GAP),
        )
        self.delta_text = AdaptiveCanvasText(
            self.delta_canvas,
            text="",
            font_name=CASCADIA_MONO_FONT,
            font_size=DELTA_FONT_SIZE,
            position=(DELTA_COLUMN_WIDTH - 2, ROW_MIDDLE),
            anchor="rm",
        )
        self.delta_text.solid_color = "#20D878"
        self.token_canvas = tk.Canvas(
            self.frame,
            bg=transparent,
            width=TOKEN_COLUMN_WIDTH,
            height=ROW_HEIGHT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.token_canvas.grid(
            row=0,
            column=4,
            sticky="e",
            padx=(0, VALUE_COLUMN_GAP),
        )
        self.token_text = AdaptiveCanvasText(
            self.token_canvas,
            text="0",
            font_name=CASCADIA_MONO_FONT,
            font_size=BODY_FONT_SIZE,
            position=(TOKEN_COLUMN_WIDTH - 2, ROW_MIDDLE),
            anchor="rm",
        )
        self.cost_canvas = tk.Canvas(
            self.frame,
            bg=transparent,
            width=COST_COLUMN_WIDTH,
            height=ROW_HEIGHT,
            highlightthickness=0,
            borderwidth=0,
        )
        self.cost_canvas.grid(row=0, column=5, sticky="e")
        self.cost_text = AdaptiveCanvasText(
            self.cost_canvas,
            text="$0.00",
            font_name=CASCADIA_MONO_FONT,
            font_size=COST_FONT_SIZE,
            position=(COST_COLUMN_WIDTH - 2, ROW_MIDDLE),
            anchor="rm",
        )
        self.delta_hide_job = None
        self.call_color_job = None
        self.call_animation_jobs = []
        self.call_incoming_text = None
        self.call_value = 0
        self.call_foreground = None
        self.token_color_job = None
        self.token_animation_jobs = []
        self.token_incoming_text = None
        self.token_value = 0
        self.token_foreground = None
        self.cost_color_job = None
        self.cost_animation_jobs = []
        self.cost_incoming_text = None
        self.cost_value: float | None = None
        self.cost_foreground = None
        self.current_key: tuple[str, str] | None = None

    def update(
        self,
        key: tuple[str, str] | None,
        value: int,
        delta: int,
        call_value: int,
        call_delta: int,
        cost_value: float,
        cost_delta: float,
        delta_visible_ms: int = LIVE_DELTA_VISIBLE_MS,
    ) -> None:
        platform, model = key if key else ("—", "暂无数据")
        key_changed = key != self.current_key
        if key_changed and delta <= 0:
            self._clear_delta()
        self.current_key = key
        self.model_badge_canvas.configure(
            bg=PLATFORM_COLORS.get(platform, "#8B7CF6")
        )
        self.model_badge_canvas.itemconfigure(
            self.model_badge_text_id,
            text=compact_model_name(model),
        )
        self._update_token_value(
            value,
            animate=not key_changed and delta > 0,
            foreground=self.token_foreground,
            force=key_changed,
        )
        self._update_call_value(
            call_value,
            animate=not key_changed and call_delta > 0,
            foreground=self.call_foreground,
            force=key_changed,
        )
        self._update_cost_value(
            cost_value,
            animate=not key_changed and cost_delta > 0,
            foreground=self.cost_foreground,
            force=key_changed,
        )
        if delta > 0:
            self._show_delta(delta, delta_visible_ms)

    @staticmethod
    def _create_incoming_text(
        canvas: tk.Canvas,
        reference: AdaptiveCanvasText,
        text: str,
        position: tuple[int, int],
        anchor: str,
    ) -> AdaptiveCanvasText:
        incoming = AdaptiveCanvasText(
            canvas,
            text=text,
            font_name=CASCADIA_MONO_FONT,
            font_size=reference.font_size,
            position=position,
            anchor=anchor,
        )
        incoming.solid_color = "#20D878"
        if reference.last_background is not None and reference.last_root is not None:
            incoming.render(reference.last_background, reference.last_root)
        canvas.coords(incoming.image_id, 0, ROW_HEIGHT)
        return incoming

    def _cancel_token_animation(self) -> None:
        for job in self.token_animation_jobs:
            try:
                self.frame.after_cancel(job)
            except tk.TclError:
                pass
        self.token_animation_jobs.clear()
        if self.token_incoming_text is not None:
            self.token_canvas.delete(self.token_incoming_text.image_id)
            self.token_incoming_text = None
        self.token_canvas.coords(self.token_text.image_id, 0, 0)
        self.token_text.render_cached()

    def _update_token_value(
        self,
        value: int,
        animate: bool,
        foreground: str | None,
        force: bool = False,
    ) -> None:
        value = int(value)
        self.token_foreground = foreground
        if value == self.token_value and not force:
            return
        self._cancel_token_animation()
        if self.token_color_job is not None:
            self.frame.after_cancel(self.token_color_job)
            self.token_color_job = None
        if not animate:
            self.token_value = value
            self.token_text.solid_color = foreground
            self.token_text.set_text(format_tokens(value))
            return

        incoming_text = self._create_incoming_text(
            self.token_canvas,
            self.token_text,
            format_tokens(value),
            (TOKEN_COLUMN_WIDTH - 2, ROW_MIDDLE),
            "rm",
        )
        self.token_incoming_text = incoming_text
        steps = 9

        def animate_step(step: int) -> None:
            progress = step / steps
            self.token_canvas.coords(
                self.token_text.image_id, 0, -round(ROW_HEIGHT * progress)
            )
            self.token_canvas.coords(
                incoming_text.image_id,
                0,
                ROW_HEIGHT - round(ROW_HEIGHT * progress),
            )
            if step < steps:
                job = self.frame.after(24, animate_step, step + 1)
                self.token_animation_jobs.append(job)
                return
            self.token_canvas.coords(self.token_text.image_id, 0, 0)
            self.token_canvas.delete(incoming_text.image_id)
            self.token_incoming_text = None
            self.token_value = value
            self.token_animation_jobs.clear()
            self.token_text.solid_color = "#20D878"
            self.token_text.set_text(format_tokens(value))
            self.token_color_job = self.frame.after(1100, self._restore_token_color)

        animate_step(1)

    def _restore_token_color(self) -> None:
        if self.token_incoming_text is not None:
            self.token_canvas.delete(self.token_incoming_text.image_id)
            self.token_incoming_text = None
        self.token_text.solid_color = self.token_foreground
        self.token_text.set_text(format_tokens(self.token_value))
        self.token_color_job = None

    def _cancel_call_animation(self) -> None:
        for job in self.call_animation_jobs:
            try:
                self.frame.after_cancel(job)
            except tk.TclError:
                pass
        self.call_animation_jobs.clear()
        if self.call_incoming_text is not None:
            self.call_canvas.delete(self.call_incoming_text.image_id)
            self.call_incoming_text = None
        self.call_canvas.coords(self.call_text.image_id, 0, 0)
        self.call_text.render_cached()

    def _update_call_value(
        self,
        value: int,
        animate: bool,
        foreground: str | None,
        force: bool = False,
    ) -> None:
        value = int(value)
        self.call_foreground = foreground
        if value == self.call_value and not force:
            return
        self._cancel_call_animation()
        if self.call_color_job is not None:
            self.frame.after_cancel(self.call_color_job)
            self.call_color_job = None
        if not animate:
            self.call_value = value
            self.call_text.solid_color = foreground
            self.call_text.set_text(format_tokens(value))
            return

        incoming_text = self._create_incoming_text(
            self.call_canvas,
            self.call_text,
            format_tokens(value),
            (2, ROW_MIDDLE),
            "lm",
        )
        self.call_incoming_text = incoming_text
        steps = 9

        def animate_step(step: int) -> None:
            progress = step / steps
            self.call_canvas.coords(
                self.call_text.image_id, 0, -round(ROW_HEIGHT * progress)
            )
            self.call_canvas.coords(
                incoming_text.image_id,
                0,
                ROW_HEIGHT - round(ROW_HEIGHT * progress),
            )
            if step < steps:
                job = self.frame.after(24, animate_step, step + 1)
                self.call_animation_jobs.append(job)
                return
            self.call_canvas.coords(self.call_text.image_id, 0, 0)
            self.call_canvas.delete(incoming_text.image_id)
            self.call_incoming_text = None
            self.call_value = value
            self.call_animation_jobs.clear()
            self.call_text.solid_color = "#20D878"
            self.call_text.set_text(format_tokens(value))
            self.call_color_job = self.frame.after(1100, self._restore_call_color)

        animate_step(1)

    def _restore_call_color(self) -> None:
        if self.call_incoming_text is not None:
            self.call_canvas.delete(self.call_incoming_text.image_id)
            self.call_incoming_text = None
        self.call_text.solid_color = self.call_foreground
        self.call_text.set_text(format_tokens(self.call_value))
        self.call_color_job = None

    def _cancel_cost_animation(self) -> None:
        for job in self.cost_animation_jobs:
            try:
                self.frame.after_cancel(job)
            except tk.TclError:
                pass
        self.cost_animation_jobs.clear()
        if self.cost_incoming_text is not None:
            self.cost_canvas.delete(self.cost_incoming_text.image_id)
            self.cost_incoming_text = None
        self.cost_canvas.coords(self.cost_text.image_id, 0, 0)
        self.cost_text.render_cached()

    def _update_cost_value(
        self,
        value: float | None,
        animate: bool,
        foreground: str | None,
        force: bool = False,
    ) -> None:
        value = None if value is None else float(value)
        self.cost_foreground = foreground
        if value == self.cost_value and not force:
            return
        self._cancel_cost_animation()
        if self.cost_color_job is not None:
            self.frame.after_cancel(self.cost_color_job)
            self.cost_color_job = None
        if not animate:
            self.cost_value = value
            self.cost_text.solid_color = foreground
            self.cost_text.set_text(format_cost(value))
            return

        incoming_text = self._create_incoming_text(
            self.cost_canvas,
            self.cost_text,
            format_cost(value),
            (COST_COLUMN_WIDTH - 2, ROW_MIDDLE),
            "rm",
        )
        self.cost_incoming_text = incoming_text
        steps = 9

        def animate_step(step: int) -> None:
            progress = step / steps
            self.cost_canvas.coords(
                self.cost_text.image_id, 0, -round(ROW_HEIGHT * progress)
            )
            self.cost_canvas.coords(
                incoming_text.image_id,
                0,
                ROW_HEIGHT - round(ROW_HEIGHT * progress),
            )
            if step < steps:
                job = self.frame.after(24, animate_step, step + 1)
                self.cost_animation_jobs.append(job)
                return
            self.cost_canvas.coords(self.cost_text.image_id, 0, 0)
            self.cost_canvas.delete(incoming_text.image_id)
            self.cost_incoming_text = None
            self.cost_value = value
            self.cost_animation_jobs.clear()
            self.cost_text.solid_color = "#20D878"
            self.cost_text.set_text(format_cost(value))
            self.cost_color_job = self.frame.after(1100, self._restore_cost_color)

        animate_step(1)

    def _restore_cost_color(self) -> None:
        if self.cost_incoming_text is not None:
            self.cost_canvas.delete(self.cost_incoming_text.image_id)
            self.cost_incoming_text = None
        self.cost_text.solid_color = self.cost_foreground
        self.cost_text.set_text(format_cost(self.cost_value))
        self.cost_color_job = None

    def _show_delta(
        self,
        delta: int,
        visible_ms: int = LIVE_DELTA_VISIBLE_MS,
    ) -> None:
        if self.delta_hide_job is not None:
            self.frame.after_cancel(self.delta_hide_job)
        self.delta_text.set_text(f"+{int(delta):,}")
        self.delta_hide_job = self.frame.after(
            max(1, int(visible_ms)),
            self._clear_delta,
        )

    def _clear_delta(self) -> None:
        self.delta_text.set_text("")
        self.delta_hide_job = None

    def set_foreground(self, foreground: str) -> None:
        self.set_solid_color(foreground)

    def set_solid_color(self, color: str | None) -> None:
        self.call_foreground = color
        self.token_foreground = color
        self.cost_foreground = color
        for text in (
            self.rank_text,
            self.call_text,
            self.token_text,
            self.cost_text,
        ):
            text.solid_color = color
            text.render_cached()
        self.delta_text.solid_color = "#20D878"
        self.delta_text.render_cached()

    def adaptive_texts(self) -> tuple[AdaptiveCanvasText, ...]:
        return (
            self.rank_text,
            self.call_text,
            self.delta_text,
            self.token_text,
            self.cost_text,
        )

class LiveUsageApp:
    def __init__(self, engine: UsageEngine, screenshot_path: Path | None = None):
        self.engine = engine
        self.ui_scale = apply_ui_scale(load_ui_scale())
        self.row_count = load_row_count()
        self.refresh_seconds = apply_refresh_seconds(load_refresh_seconds())
        self.refresh_after_id: str | None = None
        self.topmost_after_id: str | None = None
        self.period = "cumulative"
        self.transparent = "#010101"
        self.drag_origin: tuple[int, int] | None = None
        self.previous_values = {period: {} for period in PERIODS}
        self.previous_calls = {period: {} for period in PERIODS}
        self.previous_costs = {period: {} for period in PERIODS}
        self.startup_snapshot = self.engine.get_snapshot()
        self.startup_values = {
            period: dict(self.startup_snapshot.periods.get(period, {}))
            if self.startup_snapshot is not None
            else {}
            for period in PERIODS
        }
        self.startup_calls = {
            period: dict(self.startup_snapshot.call_periods.get(period, {}))
            if self.startup_snapshot is not None
            else {}
            for period in PERIODS
        }
        self.startup_costs = {
            period: dict(self.startup_snapshot.cost_periods.get(period, {}))
            if self.startup_snapshot is not None
            else {}
            for period in PERIODS
        }
        self.startup_reconcile_pending = self.startup_snapshot is not None
        self.period_changed = False
        self.last_background_check = 0.0
        self.manual_foreground = False
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_TITLE)
        self.root.overrideredirect(True)
        self.root.configure(bg=self.transparent)
        self.root.geometry(
            f"{WINDOW_WIDTH}x{window_height_for_rows(self.row_count)}"
        )
        self.root.attributes("-topmost", True)
        if os.name == "nt":
            self.root.wm_attributes("-transparentcolor", self.transparent)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.screenshot_path = screenshot_path
        self._build()
        self._update_period_styles()
        if self.engine.get_snapshot() is not None:
            self.manual_foreground = True
            self._refresh_ui(schedule=False)
            self.manual_foreground = False
        self._position_top_right()
        self.root.update_idletasks()
        self._apply_adaptive_foregrounds()
        self.root.deiconify()
        self.root.lift()
        self._ensure_topmost()
        self.engine.start()
        self._schedule_refresh(initial=True)
        if screenshot_path:
            self.root.after(3500, self._save_screenshot)

    def _build(self) -> None:
        self.shell = tk.Frame(self.root, bg=self.transparent)
        self.shell.pack(fill="both", expand=True, padx=3, pady=3)
        self.header = tk.Frame(self.shell, bg=self.transparent)
        header = self.header
        header.pack(fill="x", pady=(0, 2))
        self.title_canvas = tk.Canvas(
            header,
            bg=self.transparent,
            width=230,
            height=40,
            highlightthickness=0,
            borderwidth=0,
        )
        self.title_canvas.pack(side="left")
        self.title_text = AdaptiveCanvasText(
            self.title_canvas,
            text=f"AI TOKEN TOP {self.row_count}",
            font_name=CASCADIA_MONO_FONT,
            font_size=TITLE_FONT_SIZE,
            position=(1, 20),
            anchor="lm",
        )
        self.live_canvas = tk.Canvas(
            header,
            bg=self.transparent,
            width=98,
            height=40,
            highlightthickness=0,
            borderwidth=0,
        )
        self.live_canvas.pack(side="right", padx=(5, 0))
        self.live_text = AdaptiveCanvasText(
            self.live_canvas,
            text="AUTO ●",
            font_name=YAHEI_BOLD_FONT,
            font_size=24,
            position=(96, 20),
            anchor="rm",
        )
        self.period_frame = tk.Frame(header, bg=self.transparent)
        self.period_frame.pack(side="right", padx=(12, 5))
        self.period_texts = {}
        for period in PERIODS:
            canvas = tk.Canvas(
                self.period_frame,
                bg=self.transparent,
                width=68,
                height=40,
                highlightthickness=0,
                borderwidth=0,
                cursor="hand2",
            )
            canvas.pack(side="left")
            text = AdaptiveCanvasText(
                canvas,
                text=PERIOD_LABELS[period],
                font_name=YAHEI_BOLD_FONT,
                font_size=24,
                position=(34, 20),
                anchor="mm",
            )
            canvas.bind(
                "<Button-1>",
                lambda _event, value=period: self._set_period(value),
            )
            self.period_texts[period] = text
        self.rows_container = tk.Frame(self.shell, bg=self.transparent)
        self.rows_container.pack(fill="x")
        self.cards = [
            FloatingRankRow(self.rows_container, rank, self.transparent)
            for rank in range(1, self.row_count + 1)
        ]
        self.footer_frame = tk.Frame(self.shell, bg=self.transparent)
        self.footer_frame.pack(fill="x", pady=(2, 0))
        self.color_toggle_canvas = tk.Canvas(
            self.footer_frame,
            bg=self.transparent,
            width=68,
            height=32,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.color_toggle_canvas.pack(side="left")
        self.color_toggle_text = AdaptiveCanvasText(
            self.color_toggle_canvas,
            text="自动",
            font_name=YAHEI_BOLD_FONT,
            font_size=20,
            position=(2, 16),
            anchor="lm",
        )
        self.color_toggle_canvas.bind("<Button-1>", self._toggle_foreground)
        self.color_toggle_canvas.bind("<Button-3>", self._show_menu)
        self.increase_column_canvas = tk.Canvas(
            self.footer_frame,
            bg=self.transparent,
            width=FOOTER_CONTROL_WIDTH,
            height=32,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.increase_column_canvas.pack(side="left")
        self.increase_column_text = AdaptiveCanvasText(
            self.increase_column_canvas,
            text="增加列",
            font_name=YAHEI_FONT,
            font_size=20,
            position=(FOOTER_CONTROL_WIDTH // 2, 16),
            anchor="mm",
        )
        self.increase_column_canvas.bind(
            "<Button-1>",
            lambda _event: self._change_row_count(1),
        )
        self.increase_column_canvas.bind("<Button-3>", self._show_menu)
        self.increase_column_canvas.bind(
            "<Control-MouseWheel>",
            self._scale_with_wheel,
        )
        self.decrease_column_canvas = tk.Canvas(
            self.footer_frame,
            bg=self.transparent,
            width=FOOTER_CONTROL_WIDTH,
            height=32,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.decrease_column_canvas.pack(side="left")
        self.decrease_column_text = AdaptiveCanvasText(
            self.decrease_column_canvas,
            text="减少列",
            font_name=YAHEI_FONT,
            font_size=20,
            position=(FOOTER_CONTROL_WIDTH // 2, 16),
            anchor="mm",
        )
        self.decrease_column_canvas.bind(
            "<Button-1>",
            lambda _event: self._change_row_count(-1),
        )
        self.decrease_column_canvas.bind("<Button-3>", self._show_menu)
        self.decrease_column_canvas.bind(
            "<Control-MouseWheel>",
            self._scale_with_wheel,
        )
        self.footer_canvas = tk.Canvas(
            self.footer_frame,
            bg=self.transparent,
            width=FOOTER_COLUMN_WIDTH,
            height=32,
            highlightthickness=0,
            borderwidth=0,
        )
        self.footer_canvas.pack(side="right")
        self.footer_text = AdaptiveCanvasText(
            self.footer_canvas,
            text=f"{format_refresh_seconds(self.refresh_seconds)}s",
            font_name=YAHEI_FONT,
            font_size=20,
            position=(FOOTER_COLUMN_WIDTH - 2, 16),
            anchor="rm",
        )
        for widget in (
            self.shell,
            self.header,
            self.title_canvas,
            self.live_canvas,
            self.rows_container,
            self.footer_frame,
            self.footer_canvas,
        ):
            self._bind_window_actions(widget)
        for card in self.cards:
            for widget in card.frame.winfo_children():
                self._bind_window_actions(widget)
        self.menu = tk.Menu(self.root, tearoff=0)
        for period in PERIODS:
            self.menu.add_command(
                label=PERIOD_LABELS[period],
                command=lambda value=period: self._set_period(value),
            )
        self.menu.add_command(label="打开完整报告", command=self._open_report)
        self.menu.add_separator()
        self.menu.add_command(
            label="增加列",
            command=lambda: self._change_row_count(1),
        )
        self.menu.add_command(
            label="减少列",
            command=lambda: self._change_row_count(-1),
        )
        self.refresh_menu = tk.Menu(self.menu, tearoff=0)
        self.refresh_interval_var = tk.DoubleVar(value=self.refresh_seconds)
        for seconds in REFRESH_OPTIONS:
            self.refresh_menu.add_radiobutton(
                label=f"{format_refresh_seconds(seconds)} 秒",
                variable=self.refresh_interval_var,
                value=seconds,
                command=lambda value=seconds: self._set_refresh_seconds(value),
            )
        self.menu.add_cascade(label="调整刷新时间", menu=self.refresh_menu)
        self.menu.add_separator()
        self.menu.add_command(label="缩小界面", command=lambda: self._change_scale(-UI_SCALE_STEP))
        self.menu.add_command(label="放大界面", command=lambda: self._change_scale(UI_SCALE_STEP))
        self.menu.add_command(label="恢复默认大小", command=self._reset_scale)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.close)

    def _bind_window_actions(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag)
        widget.bind("<Button-3>", self._show_menu)
        widget.bind("<Control-MouseWheel>", self._scale_with_wheel)

    def _scale_with_wheel(self, event) -> str:
        self._change_scale(UI_SCALE_STEP if event.delta > 0 else -UI_SCALE_STEP)
        return "break"

    def _change_scale(self, amount: float) -> None:
        self._set_scale(self.ui_scale + amount)

    def _reset_scale(self) -> None:
        self._set_scale(DEFAULT_UI_SCALE)

    def _set_scale(self, value: float) -> None:
        value = round(min(MAX_UI_SCALE, max(MIN_UI_SCALE, value)), 2)
        if value == self.ui_scale:
            return
        x, y = self.root.winfo_x(), self.root.winfo_y()
        save_ui_scale(value)
        self.ui_scale = apply_ui_scale(value)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.geometry(
            f"{WINDOW_WIDTH}x{window_height_for_rows(self.row_count)}+{x}+{y}"
        )
        self._build()
        self._update_period_styles()
        self.manual_foreground = True
        self._refresh_ui(schedule=False)
        self.manual_foreground = False
        self.root.update_idletasks()
        self._apply_adaptive_foregrounds()

    def _change_row_count(self, amount: int) -> None:
        value = clamp_row_count(self.row_count + amount)
        if value == self.row_count:
            return
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.row_count = value
        save_row_count(value)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.geometry(
            f"{WINDOW_WIDTH}x{window_height_for_rows(value)}+{x}+{y}"
        )
        self._build()
        self._update_period_styles()
        self.manual_foreground = True
        self._refresh_ui(schedule=False)
        self.manual_foreground = False
        self.root.update_idletasks()
        self._apply_adaptive_foregrounds()

    def _set_refresh_seconds(self, value: float) -> None:
        value = apply_refresh_seconds(value)
        if value == self.refresh_seconds:
            return
        self.refresh_seconds = value
        save_refresh_seconds(value)
        self._refresh_ui(schedule=False)
        self._schedule_refresh()

    def _schedule_refresh(self, initial: bool = False) -> None:
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
        delay_ms = 100 if initial else max(50, round(self.refresh_seconds * 1000))
        self.refresh_after_id = self.root.after(delay_ms, self._refresh_ui)

    def _ensure_topmost(self) -> None:
        try:
            if self.root.state() == "withdrawn":
                self.root.deiconify()
            if os.name == "nt":
                import ctypes
                import ctypes.wintypes

                user32 = ctypes.windll.user32
                user32.GetAncestor.argtypes = (
                    ctypes.wintypes.HWND,
                    ctypes.wintypes.UINT,
                )
                user32.GetAncestor.restype = ctypes.wintypes.HWND
                user32.SetWindowPos.argtypes = (
                    ctypes.wintypes.HWND,
                    ctypes.wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.wintypes.UINT,
                )
                user32.SetWindowPos.restype = ctypes.wintypes.BOOL
                hwnd = user32.GetAncestor(
                    ctypes.wintypes.HWND(self.root.winfo_id()),
                    2,
                )
                if hwnd:
                    user32.SetWindowPos(
                        hwnd,
                        ctypes.wintypes.HWND(-1),
                        0,
                        0,
                        0,
                        0,
                        0x0001 | 0x0002 | 0x0010,
                    )
            else:
                self.root.attributes("-topmost", True)
            self.topmost_after_id = self.root.after(3000, self._ensure_topmost)
        except tk.TclError:
            self.topmost_after_id = None

    def _position_top_right(self) -> None:
        self.root.update_idletasks()
        requested_geometry = os.environ.get("TOKENWATCHER_WINDOW_GEOMETRY", "").strip()
        if re.fullmatch(r"\d+x\d+[+-]\d+[+-]\d+", requested_geometry):
            self.root.geometry(requested_geometry)
            return
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = max(0, self.root.winfo_screenwidth() - width - 22)
        y = 44
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set_period(self, period: str) -> None:
        if period == self.period:
            return
        self.period = period
        self.period_changed = True
        self._update_period_styles()

    def _update_period_styles(self) -> None:
        for period, text in self.period_texts.items():
            text.set_text(
                f"• {PERIOD_LABELS[period]}"
                if period == self.period
                else PERIOD_LABELS[period]
            )

    def _capture_background(self):
        user32 = None
        dwmapi = None
        hwnd = 0
        capture_exclusion_applied = False
        try:
            from PIL import ImageGrab

            width = self.root.winfo_width()
            height = self.root.winfo_height()
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            right = x + width
            bottom = y + height
            if os.name == "nt":
                import ctypes
                import ctypes.wintypes

                user32 = ctypes.windll.user32
                dwmapi = ctypes.windll.dwmapi
                hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
                # Exclude the overlay only while sampling its background. Keeping
                # this flag set would also remove it from normal user screenshots.
                capture_exclusion_applied = bool(
                    hwnd
                    and user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
                )
                dwmapi.DwmFlush()
                rect = ctypes.wintypes.RECT()
                if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    get_dpi_for_window = getattr(
                        user32,
                        "GetDpiForWindow",
                        None,
                    )
                    dpi_scale = (
                        max(1.0, get_dpi_for_window(hwnd) / 96.0)
                        if get_dpi_for_window is not None
                        else 1.0
                    )
                    x, y, right, bottom = (
                        round(rect.left / dpi_scale),
                        round(rect.top / dpi_scale),
                        round(rect.right / dpi_scale),
                        round(rect.bottom / dpi_scale),
                    )
            image = ImageGrab.grab(
                (x, y, right, bottom),
                all_screens=True,
            ).convert("RGB")
            if image.size != (width, height):
                image = image.resize((width, height))
            return image
        except Exception:
            return None
        finally:
            if capture_exclusion_applied and user32 is not None:
                user32.SetWindowDisplayAffinity(hwnd, 0)
                if dwmapi is not None:
                    dwmapi.DwmFlush()

    def _adaptive_texts(self) -> tuple[AdaptiveCanvasText, ...]:
        texts = [
            self.title_text,
            self.live_text,
            *self.period_texts.values(),
            self.color_toggle_text,
            self.increase_column_text,
            self.decrease_column_text,
            self.footer_text,
        ]
        for card in self.cards:
            texts.extend(card.adaptive_texts())
        return tuple(texts)

    def _apply_adaptive_foregrounds(self) -> None:
        texts = self._adaptive_texts()
        self.root.update_idletasks()
        image = self._capture_background()
        if image is None:
            return
        prepared = [(text, text.prepare(image, self.root)) for text in texts]
        buffered = [
            (text, rendered, text.prepare_photo(rendered))
            for text, rendered in prepared
        ]
        for text, rendered, photo in buffered:
            text.apply_buffered(rendered, photo, image, self.root)
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()

    def _toggle_foreground(self, _event=None) -> None:
        self.manual_foreground = not self.manual_foreground
        if self.manual_foreground:
            target = "#000000"
            for text in self._adaptive_texts():
                text.solid_color = target
                text.render_cached()
            for card in self.cards:
                card.set_foreground(target)
            self.color_toggle_text.set_text("手动黑")
        else:
            for text in self._adaptive_texts():
                text.solid_color = None
            for card in self.cards:
                card.set_solid_color(None)
            self.color_toggle_text.set_text("自动")
            self._apply_adaptive_foregrounds()

    def _start_drag(self, event) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event) -> None:
        if not self.drag_origin:
            return
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _show_menu(self, event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def _open_report(self) -> None:
        path = self.engine.report_dir / "REPORT.html"
        if path.exists() and os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]

    def _refresh_ui(self, schedule: bool = True) -> None:
        snapshot = self.engine.get_snapshot()
        if snapshot:
            startup_reconcile = bool(
                self.startup_reconcile_pending
                and snapshot is not self.startup_snapshot
                and not snapshot.error
            )
            top = snapshot.top(self.period, self.row_count)
            previous = (
                self.startup_values[self.period]
                if startup_reconcile
                else self.previous_values[self.period]
            )
            previous_calls = (
                self.startup_calls[self.period]
                if startup_reconcile
                else self.previous_calls[self.period]
            )
            previous_costs = (
                self.startup_costs[self.period]
                if startup_reconcile
                else self.previous_costs[self.period]
            )
            for index, card in enumerate(self.cards):
                if index < len(top):
                    key, value = top[index]
                    delta = observed_growth(
                        value,
                        previous,
                        key,
                        include_new_key=startup_reconcile,
                    )
                    call_value = snapshot.call_periods.get(self.period, {}).get(key, 0)
                    call_delta = call_value - previous_calls.get(
                        key,
                        0 if startup_reconcile else call_value,
                    )
                    cost_value = snapshot.cost_periods.get(self.period, {}).get(key)
                    previous_cost = previous_costs.get(
                        key,
                        0.0 if startup_reconcile else None,
                    )
                    cost_delta = (
                        cost_value - previous_cost
                        if cost_value is not None and previous_cost is not None
                        else 0.0
                    )
                    card.update(
                        key,
                        value,
                        0 if self.period_changed else delta,
                        call_value,
                        0 if self.period_changed else call_delta,
                        cost_value,
                        0.0 if self.period_changed else cost_delta,
                        STARTUP_DELTA_VISIBLE_MS
                        if startup_reconcile
                        else LIVE_DELTA_VISIBLE_MS,
                    )
                else:
                    card.update(None, 0, 0, 0, 0, None, 0.0)
            for period in PERIODS:
                self.previous_values[period] = dict(snapshot.periods.get(period, {}))
                self.previous_calls[period] = dict(
                    snapshot.call_periods.get(period, {})
                )
                self.previous_costs[period] = dict(
                    snapshot.cost_periods.get(period, {})
                )
            if startup_reconcile:
                self.startup_reconcile_pending = False
            self.period_changed = False
            top_total = sum(value for _, value in top)
            source_text = (
                f"{PERIOD_LABELS[self.period]}前{row_count_label(self.row_count)} "
                f"Σ {format_tokens(top_total)}  ·  "
                f"{snapshot.updated_at.strftime('%H:%M:%S.%f')[:-3]}  ·  "
                f"{format_refresh_seconds(self.refresh_seconds)} 秒"
            )
            if snapshot.error:
                self.live_text.set_text("AUTO ×")
            else:
                self.live_text.set_text("AUTO ●")
            self.footer_text.set_text(source_text)
            if (
                not self.manual_foreground
                and time.monotonic() - self.last_background_check >= 1.0
            ):
                self.last_background_check = time.monotonic()
                self._apply_adaptive_foregrounds()
        if schedule:
            self._schedule_refresh()

    def _save_screenshot(self) -> None:
        if not self.screenshot_path:
            return
        try:
            image = self._compose_visual_snapshot()
            self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(self.screenshot_path)
        finally:
            self.close()

    def _compose_visual_snapshot(self):
        from PIL import Image, ImageColor, ImageDraw

        width = self.root.winfo_width()
        height = self.root.winfo_height()
        background = next(
            (
                text.last_background
                for text in self._adaptive_texts()
                if text.last_background is not None
            ),
            None,
        )
        if background is None:
            background = Image.new("RGB", (width, height), "white")
        image = background.resize((width, height)).convert("RGBA")
        for text in self._adaptive_texts():
            if text.last_image is None:
                continue
            x = text.canvas.winfo_rootx() - self.root.winfo_rootx()
            y = text.canvas.winfo_rooty() - self.root.winfo_rooty()
            image.alpha_composite(text.last_image, (x, y))

        draw = ImageDraw.Draw(image)
        badge_font = _load_image_font(
            YAHEI_BOLD_FONT,
            MODEL_BADGE_FONT_SIZE,
        )
        for card in self.cards:
            canvas = card.model_badge_canvas
            x = canvas.winfo_rootx() - self.root.winfo_rootx()
            y = canvas.winfo_rooty() - self.root.winfo_rooty()
            badge_width = canvas.winfo_width()
            badge_height = canvas.winfo_height()
            draw.rectangle(
                (x, y, x + badge_width - 1, y + badge_height - 1),
                fill=ImageColor.getrgb(str(canvas.cget("bg"))),
            )
            draw.text(
                (x + badge_width // 2, y + badge_height // 2),
                str(canvas.itemcget(card.model_badge_text_id, "text")),
                font=badge_font,
                fill="#FFFFFF",
                anchor="mm",
            )

        return image.convert("RGB")

    def close(self) -> None:
        for attribute in ("refresh_after_id", "topmost_after_id"):
            job = getattr(self, attribute, None)
            if job is None:
                continue
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, attribute, None)
        self.engine.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def snapshot_payload(snapshot: UsageSnapshot) -> dict:
    def rows(period: str):
        return [
            {
                "platform": key[0],
                "model": key[1],
                "calls": snapshot.call_periods.get(period, {}).get(key, 0),
                "total_tokens": value,
                "estimated_cost_usd": snapshot.cost_periods.get(period, {}).get(key),
            }
            for key, value in snapshot.top(period)
        ]

    return {
        "updated_at_shanghai": snapshot.updated_at.isoformat(),
        "report_time_shanghai": snapshot.report_time.isoformat(),
        "call_counts": {
            period: snapshot.call_count(period) for period in PERIODS
        },
        **{f"top3_{period}": rows(period) for period in PERIODS},
        "source_status": list(snapshot.source_status),
        "error": snapshot.error,
    }


def main() -> int:
    enable_dpi_awareness()
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--snapshot-json", nargs="?", const="-")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="Optional directory containing summary.json and report CSV files.",
    )
    args = parser.parse_args()
    engine = UsageEngine(args.report_dir)
    if args.self_test or args.snapshot_json is not None:
        try:
            snapshot = engine.refresh_once()
            payload = snapshot_payload(snapshot)
            output = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.snapshot_json not in (None, "-"):
                try:
                    write_text_atomic(Path(args.snapshot_json), output)
                except OSError:
                    return 2
            elif not emit_stdout(output):
                return 2
            return 0 if not snapshot.error else 1
        finally:
            engine.stop()
    instance_mutex = acquire_single_instance_mutex()
    if instance_mutex is None:
        return 0
    try:
        LiveUsageApp(engine, screenshot_path=args.screenshot).run()
    finally:
        release_single_instance_mutex(instance_mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

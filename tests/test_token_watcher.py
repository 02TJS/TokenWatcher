from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "token_watcher.py"
SPEC = importlib.util.spec_from_file_location("token_watcher", MODULE_PATH)
assert SPEC and SPEC.loader
token_watcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = token_watcher
SPEC.loader.exec_module(token_watcher)


class FakeWatcher:
    def __init__(self) -> None:
        self.available = True
        self.changes: set[Path] = set()
        self.resync_required = False

    def emit(self, path: Path) -> None:
        self.changes.add(path)

    def drain(self) -> set[Path]:
        changes = set(self.changes)
        self.changes.clear()
        return changes

    def lose_changes(self) -> None:
        self.changes.clear()
        self.resync_required = True

    def consume_resync_required(self) -> bool:
        required = self.resync_required
        self.resync_required = False
        return required

    def close(self) -> None:
        return


class TokenWatcherTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows notification API test")
    def test_directory_watcher_keeps_listening_after_overflow_error(self) -> None:
        import ctypes

        watcher = object.__new__(token_watcher.DirectoryChangeWatcher)
        watcher._closed = token_watcher.threading.Event()
        watcher._resync_required = token_watcher.threading.Event()
        watcher._handle = object()
        watcher.available = True

        class FakeReadDirectoryChanges:
            argtypes = None
            restype = None

            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, *_args) -> int:
                self.calls += 1
                if self.calls == 1:
                    ctypes.set_last_error(1022)
                    return 0
                watcher._closed.set()
                ctypes.set_last_error(995)
                return 0

        read_changes = FakeReadDirectoryChanges()
        kernel32 = type("FakeKernel32", (), {})()
        kernel32.ReadDirectoryChangesW = read_changes
        watcher._kernel32 = kernel32

        watcher._run_windows()

        self.assertEqual(read_changes.calls, 2)
        self.assertTrue(watcher.consume_resync_required())

    @staticmethod
    def _codex_lines(
        session_id: str,
        total: int,
        timestamp: datetime,
        cumulative: int | None = None,
    ) -> str:
        info = {"last_token_usage": {"total_tokens": total}}
        if cumulative is not None:
            info["total_token_usage"] = {"total_tokens": cumulative}
        return "\n".join(
            (
                json.dumps({"type": "session_meta", "payload": {"id": session_id}}),
                json.dumps(
                    {"type": "turn_context", "payload": {"model": "gpt-test"}}
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "timestamp": timestamp.isoformat(),
                        "payload": {
                            "type": "token_count",
                            "info": info,
                        },
                    }
                ),
            )
        ) + "\n"

    @staticmethod
    def _claude_line(
        message_id: str,
        total: int,
        timestamp: datetime,
        *,
        cached: int = 0,
        cache_created: int = 0,
        output: int = 0,
    ) -> str:
        return json.dumps(
            {
                "type": "assistant",
                "timestamp": timestamp.isoformat(),
                "sessionId": "claude-session",
                "message": {
                    "id": message_id,
                    "model": "claude-test",
                    "usage": {
                        "input_tokens": total,
                        "cache_read_input_tokens": cached,
                        "cache_creation_input_tokens": cache_created,
                        "output_tokens": output,
                    },
                },
            }
        ) + "\n"

    def test_format_tokens_uses_exact_grouped_value(self) -> None:
        self.assertEqual(token_watcher.format_tokens(20_043_264_243), "20,043,264,243")

    def test_format_cost_uses_usd_with_two_decimal_places(self) -> None:
        self.assertEqual(token_watcher.format_cost(4863.511915), "$4,863.51")
        self.assertEqual(token_watcher.format_cost(None), "—")

    def test_live_usage_cost_uses_cache_and_long_context_prices(self) -> None:
        short = token_watcher.usage_cost_usd(
            "gpt-5.6-sol",
            {
                "input_tokens": 100_000,
                "cached_input_tokens": 80_000,
                "output_tokens": 1_000,
            },
            source="codex",
            context_window=200_000,
        )
        long = token_watcher.usage_cost_usd(
            "gpt-5.6-sol",
            {
                "input_tokens": 300_000,
                "cached_input_tokens": 250_000,
                "output_tokens": 2_000,
            },
            source="codex",
            context_window=400_000,
        )
        opus = token_watcher.usage_cost_usd(
            "claude-opus-4.8",
            {
                "input_tokens": 10_000,
                "cache_read_input_tokens": 20_000,
                "cache_creation_input_tokens": 2_000,
                "output_tokens": 1_000,
            },
            source="claude",
        )
        terra = token_watcher.usage_cost_usd(
            "gpt-5.6-terra",
            {
                "input_tokens": 100_000,
                "cached_input_tokens": 80_000,
                "output_tokens": 1_000,
            },
            source="codex",
            context_window=200_000,
        )
        self.assertAlmostEqual(short, 0.17)
        self.assertAlmostEqual(long, 0.84)
        self.assertAlmostEqual(opus, 0.0975)
        self.assertAlmostEqual(terra, 0.085)
        self.assertIsNone(
            token_watcher.usage_cost_usd(
                "unpriced-model", {}, source="codex"
            )
        )

    def test_text_foreground_inverts_plain_light_and_dark_backgrounds(self) -> None:
        light = token_watcher.choose_text_foreground([(245, 245, 245)] * 20)
        dark = token_watcher.choose_text_foreground([(20, 20, 20)] * 20)
        self.assertEqual(light, "#000000")
        self.assertEqual(dark, "#FFFFFF")

    def test_text_foreground_chooses_best_worst_case_contrast(self) -> None:
        pixels = (
            [(250, 250, 250)] * 30
            + [(190, 220, 250)] * 10
            + [(255, 220, 40)] * 10
        )
        self.assertEqual(token_watcher.choose_text_foreground(pixels), "#000000")

    def test_adaptive_text_uses_one_solid_color_across_a_split_background(self) -> None:
        from PIL import Image

        background = Image.new("RGB", (80, 40), "white")
        for x in range(40, 80):
            for y in range(40):
                background.putpixel((x, y), (0, 0, 0))
        rendered = token_watcher.render_solid_contrast_text(
            background,
            "W",
            token_watcher.CASCADIA_MONO_FONT,
            36,
            (40, 20),
            "mm",
        )
        colors = {
            pixel[:3]
            for pixel in rendered.getdata()
            if pixel[3] > 0
        }
        self.assertEqual(len(colors), 1)
        self.assertTrue(colors <= {(0, 0, 0), (255, 255, 255)})

    def test_saturated_backgrounds_choose_uniform_black_or_white(self) -> None:
        from PIL import Image

        cases = (
            ((255, 0, 0), (0, 0, 0)),
            ((0, 255, 0), (0, 0, 0)),
            ((0, 0, 255), (255, 255, 255)),
        )
        for background_color, expected in cases:
            rendered = token_watcher.render_solid_contrast_text(
                Image.new("RGB", (80, 40), background_color),
                "W",
                token_watcher.CASCADIA_MONO_FONT,
                36,
                (40, 20),
                "mm",
            )
            colors = {
                pixel[:3]
                for pixel in rendered.getdata()
                if pixel[3] > 0
            }
            self.assertEqual(colors, {expected})

    def test_adaptive_refresh_replaces_prepared_layers_without_hiding(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        method = source.split(
            "    def _apply_adaptive_foregrounds(self) -> None:", 1
        )[1].split("\n    def ", 1)[0]
        self.assertNotIn(".hide()", method)
        self.assertIn("prepared =", method)
        self.assertIn("buffered =", method)
        self.assertIn("apply_buffered", method)

    def test_white_background_renders_crisp_opaque_black_text(self) -> None:
        from PIL import Image

        background = Image.new("RGB", (250, 56), "white")
        rendered = token_watcher.render_solid_contrast_text(
            background,
            "9,999,999,999",
            token_watcher.CASCADIA_MONO_FONT,
            token_watcher.BODY_FONT_SIZE,
            (248, token_watcher.ROW_MIDDLE),
            "rm",
        )
        opaque_black = sum(
            1 for pixel in rendered.getdata() if pixel == (0, 0, 0, 255)
        )
        self.assertGreater(opaque_black, 600)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("stroke_width=1", source)
        self.assertIn("GetWindowRect", source)
        self.assertIn("GetDpiForWindow", source)
        self.assertIn("SetWindowDisplayAffinity", source)
        self.assertIn("0x00000011", source)
        self.assertIn("DwmFlush", source)
        self.assertIn("rect.right / dpi_scale", source)
        self.assertIn("_compose_visual_snapshot", source)
        self.assertIn("image.alpha_composite(text.last_image", source)

    def test_overlay_layout_uses_large_borderless_text(self) -> None:
        self.assertEqual(token_watcher.WINDOW_WIDTH, 852)
        self.assertGreaterEqual(token_watcher.BODY_FONT_SIZE, 26)
        self.assertGreaterEqual(token_watcher.TITLE_FONT_SIZE, 28)
        self.assertEqual(
            token_watcher.MODEL_BADGE_FONT_SIZE,
            token_watcher.BODY_FONT_SIZE,
        )
        self.assertEqual(token_watcher.DELTA_FONT_SIZE, token_watcher.BODY_FONT_SIZE)
        self.assertEqual(token_watcher.COST_FONT_SIZE, token_watcher.BODY_FONT_SIZE)
        self.assertEqual(token_watcher.VALUE_COLUMN_GAP, 20)
        self.assertEqual(token_watcher.MODEL_CALL_LEFT_SHIFT, 16)
        self.assertEqual(token_watcher.RANK_LEFT_SHIFT, 16)
        self.assertEqual(token_watcher.DELTA_COLUMN_WIDTH, 132)
        row_width = (
            token_watcher.RANK_COLUMN_WIDTH
            + 2
            + token_watcher.RANK_LEFT_SHIFT
            + token_watcher.MODEL_COLUMN_WIDTH
            + 3
            + token_watcher.CALL_COLUMN_WIDTH
            + token_watcher.VALUE_COLUMN_GAP
            + token_watcher.MODEL_CALL_LEFT_SHIFT
            + token_watcher.DELTA_COLUMN_WIDTH
            + token_watcher.VALUE_COLUMN_GAP
            + token_watcher.TOKEN_COLUMN_WIDTH
            + token_watcher.VALUE_COLUMN_GAP
            + token_watcher.COST_COLUMN_WIDTH
        )
        self.assertLessEqual(row_width, token_watcher.WINDOW_WIDTH - 6)
        self.assertGreaterEqual(token_watcher.ROW_HEIGHT, 56)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('-MODEL_BADGE_FONT_SIZE, "bold"', source)
        self.assertIn("MODEL_BADGE_FONT_SIZE,\n        )", source)
        self.assertNotIn("PLATFORM_COLUMN_WIDTH", source)
        self.assertIn("self.model_badge_canvas", source)
        self.assertIn(
            "width=MODEL_COLUMN_WIDTH + MODEL_CALL_LEFT_SHIFT",
            source,
        )
        self.assertIn("+ RANK_LEFT_SHIFT\n                - MODEL_CALL_LEFT_SHIFT", source)
        self.assertIn(
            "(MODEL_COLUMN_WIDTH + MODEL_CALL_LEFT_SHIFT) // 2",
            source,
        )
        self.assertIn("VALUE_COLUMN_GAP + MODEL_CALL_LEFT_SHIFT", source)
        self.assertIn("self.delta_canvas", source)
        self.assertIn('self.delta_text.set_text(f"+{int(delta):,}")', source)
        self.assertIn("self.cost_canvas", source)
        self.assertIn('self.root.overrideredirect(True)', source)
        self.assertIn('highlightthickness=0', source)
        self.assertIn('borderwidth=0', source)
        self.assertIn('TOKENWATCHER_WINDOW_GEOMETRY', source)
        self.assertIn("import re", source)
        self.assertTrue(
            token_watcher.re.fullmatch(r"\d+x\d+[+-]\d+[+-]\d+", "860x260+3270+1640")
        )

    def test_ui_scale_is_clamped_persisted_and_applied(self) -> None:
        original_scale = token_watcher.WINDOW_WIDTH / token_watcher.BASE_UI_METRICS[
            "WINDOW_WIDTH"
        ]
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                settings_path = Path(temporary_directory) / "ui_settings.json"
                token_watcher.save_ui_scale(1.15, settings_path)
                self.assertEqual(token_watcher.load_ui_scale(settings_path), 1.15)
                settings_path.write_text(
                    json.dumps({"scale": 99}),
                    encoding="utf-8",
                )
                self.assertEqual(
                    token_watcher.load_ui_scale(settings_path),
                    token_watcher.MAX_UI_SCALE,
                )
            token_watcher.apply_ui_scale(0.8)
            self.assertEqual(
                token_watcher.WINDOW_WIDTH,
                round(token_watcher.BASE_UI_METRICS["WINDOW_WIDTH"] * 0.8),
            )
            self.assertEqual(token_watcher.BODY_FONT_SIZE, 21)
            source = MODULE_PATH.read_text(encoding="utf-8")
            self.assertIn("<Control-MouseWheel>", source)
            self.assertIn('label="缩小界面"', source)
            self.assertIn('label="放大界面"', source)
            self.assertIn('label="恢复默认大小"', source)
        finally:
            token_watcher.apply_ui_scale(original_scale)

    def test_ui_settings_preserve_scale_row_count_and_refresh_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_path = Path(temporary_directory) / "ui_settings.json"
            self.assertEqual(
                token_watcher.load_row_count(settings_path),
                token_watcher.DEFAULT_ROW_COUNT,
            )
            token_watcher.save_ui_scale(1.15, settings_path)
            token_watcher.save_row_count(5, settings_path)
            token_watcher.save_refresh_seconds(0.1, settings_path)
            self.assertEqual(token_watcher.load_ui_scale(settings_path), 1.15)
            self.assertEqual(token_watcher.load_row_count(settings_path), 5)
            self.assertEqual(
                token_watcher.load_refresh_seconds(settings_path),
                0.1,
            )

            token_watcher.save_row_count(999, settings_path)
            self.assertEqual(
                token_watcher.load_row_count(settings_path),
                token_watcher.MAX_ROW_COUNT,
            )
            self.assertEqual(token_watcher.load_ui_scale(settings_path), 1.15)
            self.assertEqual(token_watcher.load_refresh_seconds(settings_path), 0.1)
            token_watcher.save_row_count(-999, settings_path)
            self.assertEqual(
                token_watcher.load_row_count(settings_path),
                token_watcher.MIN_ROW_COUNT,
            )

            token_watcher.save_refresh_seconds(999, settings_path)
            self.assertEqual(
                token_watcher.load_refresh_seconds(settings_path),
                token_watcher.MAX_REFRESH_SECONDS,
            )
            token_watcher.save_refresh_seconds(-999, settings_path)
            self.assertEqual(
                token_watcher.load_refresh_seconds(settings_path),
                token_watcher.MIN_REFRESH_SECONDS,
            )

    def test_refresh_time_is_adjustable_and_shared_by_engine_and_ui(self) -> None:
        original_refresh = token_watcher.REFRESH_SECONDS
        try:
            self.assertEqual(token_watcher.apply_refresh_seconds(0.25), 0.25)
            self.assertEqual(token_watcher.REFRESH_SECONDS, 0.25)
            self.assertEqual(token_watcher.format_refresh_seconds(0.25), "0.25")
            source = MODULE_PATH.read_text(encoding="utf-8")
            self.assertIn('label="增加列"', source)
            self.assertIn('label="减少列"', source)
            self.assertIn('label="调整刷新时间"', source)
            self.assertIn("for seconds in REFRESH_OPTIONS", source)
            self.assertIn("self.refresh_seconds * 1000", source)
            self.assertNotIn("self.root.after(500, self._refresh_ui)", source)
        finally:
            token_watcher.apply_refresh_seconds(original_refresh)

    def test_row_count_controls_drive_dynamic_layout(self) -> None:
        original_scale = token_watcher.WINDOW_WIDTH / token_watcher.BASE_UI_METRICS[
            "WINDOW_WIDTH"
        ]
        try:
            token_watcher.apply_ui_scale(token_watcher.DEFAULT_UI_SCALE)
            default_height = token_watcher.window_height_for_rows(
                token_watcher.DEFAULT_ROW_COUNT
            )
            self.assertEqual(default_height, token_watcher.WINDOW_HEIGHT)
            self.assertEqual(
                token_watcher.window_height_for_rows(
                    token_watcher.DEFAULT_ROW_COUNT + 2
                ),
                default_height + (2 * token_watcher.ROW_HEIGHT),
            )
            self.assertEqual(
                token_watcher.window_height_for_rows(999),
                default_height
                + (
                    token_watcher.MAX_ROW_COUNT
                    - token_watcher.DEFAULT_ROW_COUNT
                )
                * token_watcher.ROW_HEIGHT,
            )
            self.assertEqual(token_watcher.row_count_label(3), "三")
            self.assertEqual(token_watcher.row_count_label(10), "十")
            source = MODULE_PATH.read_text(encoding="utf-8")
            self.assertIn('text="增加列"', source)
            self.assertIn('text="减少列"', source)
            self.assertIn("self._change_row_count(1)", source)
            self.assertIn("self._change_row_count(-1)", source)
            self.assertIn(
                "range(1, self.row_count + 1)",
                source,
            )
        finally:
            token_watcher.apply_ui_scale(original_scale)

    def test_usage_snapshot_top_accepts_a_dynamic_limit(self) -> None:
        now = datetime.now(timezone.utc)
        periods = {period: {} for period in token_watcher.PERIODS}
        periods["cumulative"] = {
            ("Codex", f"model-{index}"): index for index in range(1, 7)
        }
        snapshot = token_watcher.UsageSnapshot(
            periods=periods,
            call_periods={period: {} for period in token_watcher.PERIODS},
            updated_at=now,
            report_time=now,
            source_status=(),
        )
        self.assertEqual(len(snapshot.top("cumulative")), 3)
        self.assertEqual(len(snapshot.top("cumulative", 5)), 5)
        self.assertEqual(snapshot.top("cumulative", 1)[0][1], 6)

    def test_growth_animations_keep_green_accent(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("def _create_incoming_text(", source)
        self.assertIn("font_size=reference.font_size", source)
        self.assertNotIn("font_size: int = BODY_FONT_SIZE", source)
        self.assertNotIn('font=("Cascadia Mono", 11, "bold")', source)
        self.assertNotIn('font=("Cascadia Mono", 13, "bold")', source)
        self.assertIn('self.token_text.solid_color = "#20D878"', source)
        self.assertIn('self.call_text.solid_color = "#20D878"', source)
        self.assertIn('self.cost_text.solid_color = "#20D878"', source)
        self.assertIn('self.delta_text.solid_color = "#20D878"', source)

    def test_incoming_animation_inherits_scaled_reference_font(self) -> None:
        reference = Mock()
        reference.font_size = 36
        reference.last_background = None
        reference.last_root = None
        canvas = Mock()
        with patch.object(
            token_watcher,
            "AdaptiveCanvasText",
            autospec=True,
        ) as text_class:
            incoming = Mock()
            incoming.image_id = 7
            text_class.return_value = incoming
            result = token_watcher.FloatingRankRow._create_incoming_text(
                canvas,
                reference,
                "123",
                (20, 10),
                "rm",
            )
        self.assertIs(result, incoming)
        self.assertEqual(text_class.call_args.kwargs["font_size"], 36)

    def test_delta_column_fits_six_digit_increment(self) -> None:
        from PIL import ImageFont

        original_scale = token_watcher.WINDOW_WIDTH / token_watcher.BASE_UI_METRICS[
            "WINDOW_WIDTH"
        ]
        try:
            for scale in (
                token_watcher.MIN_UI_SCALE,
                token_watcher.DEFAULT_UI_SCALE,
                1.05,
                token_watcher.MAX_UI_SCALE,
            ):
                token_watcher.apply_ui_scale(scale)
                font = ImageFont.truetype(
                    token_watcher.CASCADIA_MONO_FONT,
                    token_watcher.DELTA_FONT_SIZE,
                )
                left, _top, right, _bottom = font.getbbox("+999,999")
                self.assertLessEqual(
                    right - left,
                    token_watcher.DELTA_COLUMN_WIDTH - 4,
                )
        finally:
            token_watcher.apply_ui_scale(original_scale)

    def test_active_periods(self) -> None:
        now = date(2026, 7, 13)
        self.assertEqual(
            token_watcher.active_periods(now, now),
            ("cumulative", "month", "week", "today"),
        )
        self.assertEqual(
            token_watcher.active_periods(date(2026, 7, 12), now),
            ("cumulative", "month"),
        )

    def test_sub2api_database_config_is_read_without_exposing_password(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                """server:\n  port: 8080\ndatabase:\n  host: 127.0.0.1\n  port: 5432\n  user: postgres\n  password: 'secret#value'\n  dbname: sub2api\nredis:\n  host: 127.0.0.1\n""",
                encoding="utf-8",
            )
            config = token_watcher.load_sub2api_database_config(config_path)
            self.assertEqual(config["password"], "secret#value")
            self.assertEqual(config["dbname"], "sub2api")

    def test_deepseek_api_poller_reads_tokens_and_calls_from_sub2api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = root / "config.yaml"
            psql_path = root / "psql.exe"
            config_path.write_text(
                """database:\n  host: 127.0.0.1\n  port: 5432\n  user: postgres\n  password: secret-value\n  dbname: sub2api\n""",
                encoding="utf-8",
            )
            psql_path.write_bytes(b"")
            now = datetime.now(token_watcher.SHANGHAI)
            yesterday = now.date() - timedelta(days=1)
            output = "\n".join(
                (
                    f"deepseek-v4-flash\t{now.date()}\t100\t20\t10\t16\t146\t3\t{now.isoformat()}",
                    f"deepseek-v4-pro\t{yesterday}\t50\t10\t3\t5\t68\t1\t{(now - timedelta(days=1)).isoformat()}",
                )
            )
            captured = {}

            def fake_runner(command, **kwargs):
                captured["command"] = command
                captured["env"] = kwargs["env"]
                return type(
                    "Result",
                    (),
                    {"returncode": 0, "stdout": output, "stderr": ""},
                )()

            poller = token_watcher.DeepSeekApiPoller(
                config_path=config_path,
                psql_path=psql_path,
                runner=fake_runner,
            )
            flash_key = ("DeepSeek API", "deepseek-v4-flash")
            pro_key = ("DeepSeek API", "deepseek-v4-pro")
            self.assertEqual(poller.periods["today"][flash_key], 146)
            self.assertEqual(poller.periods["cumulative"][pro_key], 68)
            self.assertEqual(poller.call_periods["today"][flash_key], 3)
            expected_cost = (
                50 * 0.435 + 10 * 0.87 + 3 * 0.435 + 5 * 0.003625
            ) / 1_000_000
            self.assertAlmostEqual(
                poller.cost_periods["cumulative"][pro_key], expected_cost
            )
            self.assertIn("4 次", poller.status)
            self.assertNotIn("secret-value", captured["command"])
            self.assertEqual(captured["env"]["PGPASSWORD"], "secret-value")
            self.assertIn("cache_read_tokens", poller.QUERY)

    def test_midnight_rollover_clears_calendar_periods_only(self) -> None:
        key = ("Codex", "gpt-test")
        periods = {
            period: Counter({key: 10}) for period in token_watcher.PERIODS
        }
        reset = token_watcher.rollover_periods(
            periods,
            date(2026, 7, 19),
            date(2026, 7, 20),
        )
        self.assertEqual(reset, ("today", "week"))
        self.assertEqual(periods["cumulative"][key], 10)
        self.assertEqual(periods["month"][key], 10)
        self.assertFalse(periods["week"])
        self.assertFalse(periods["today"])

    def test_month_boundary_at_midnight_clears_today_week_and_month(self) -> None:
        key = ("Codex", "gpt-test")
        periods = {
            period: Counter({key: 10}) for period in token_watcher.PERIODS
        }
        reset = token_watcher.rollover_periods(
            periods,
            date(2026, 5, 31),
            date(2026, 6, 1),
        )
        self.assertEqual(reset, ("today", "week", "month"))
        self.assertEqual(periods["cumulative"][key], 10)
        self.assertFalse(periods["month"])

    def test_missing_report_creates_empty_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_dir = Path(temporary_directory)
            baseline = token_watcher.load_baseline(report_dir)
            self.assertEqual(baseline.report_dir, report_dir)
            self.assertEqual(baseline.report_mtime, 0.0)
            self.assertFalse(baseline.periods["cumulative"])

    def test_baseline_loads_model_and_daily_costs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_dir = Path(temporary_directory)
            now = datetime.now(token_watcher.SHANGHAI)
            (report_dir / "summary.json").write_text(
                json.dumps({"refreshed_at_shanghai": now.isoformat()}),
                encoding="utf-8",
            )
            (report_dir / "model_cost.csv").write_text(
                "platform,model,estimated_cost_usd\n"
                "Codex,gpt-5.6-sol,12.5\n",
                encoding="utf-8",
            )
            (report_dir / "daily_cost_by_platform_model.csv").write_text(
                "date,platform,model,estimated_cost_usd\n"
                f"{now.date()},Codex,gpt-5.6-sol,1.25\n",
                encoding="utf-8",
            )
            baseline = token_watcher.load_baseline(report_dir)
            key = ("Codex", "gpt-5.6-sol")
            self.assertEqual(baseline.cost_periods["cumulative"][key], 12.5)
            self.assertEqual(baseline.cost_periods["today"][key], 1.25)

    def test_report_lookup_walks_up_from_directory_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            runtime = root / "TokenWatcher" / "TokenWatcher.runtime"
            runtime.mkdir(parents=True)
            report_dir = root / "outputs" / token_watcher.REPORT_FOLDER_NAME
            report_dir.mkdir(parents=True)
            (report_dir / "model_total.csv").write_text(
                "platform,model,total_tokens\nCodex,gpt-test,1\n",
                encoding="utf-8",
            )
            with patch.object(token_watcher.sys, "frozen", True, create=True), patch.object(
                token_watcher.sys, "executable", str(runtime / "TokenWatcher.exe")
            ), patch.object(token_watcher.Path, "cwd", return_value=runtime):
                self.assertEqual(token_watcher.find_report_dir(), report_dir)

    def test_usage_snapshot_cache_is_loaded_before_background_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "usage_snapshot_cache.json"
            now = datetime.now(timezone.utc)
            periods = {period: {} for period in token_watcher.PERIODS}
            call_periods = {period: {} for period in token_watcher.PERIODS}
            cost_periods = {period: {} for period in token_watcher.PERIODS}
            periods["cumulative"][("Codex", "gpt-test")] = 123
            call_periods["cumulative"][("Codex", "gpt-test")] = 4
            cost_periods["cumulative"][("Codex", "gpt-test")] = 12.34
            snapshot = token_watcher.UsageSnapshot(
                periods=periods,
                call_periods=call_periods,
                cost_periods=cost_periods,
                updated_at=now,
                report_time=now,
                source_status=("cached",),
            )
            writer = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=cache_path,
            )
            writer.snapshot = snapshot
            writer.stop()

            reader = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=cache_path,
            )
            loaded = reader.get_snapshot()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(
                loaded.periods["cumulative"][("Codex", "gpt-test")],
                123,
            )
            self.assertEqual(
                loaded.call_periods["cumulative"][("Codex", "gpt-test")],
                4,
            )
            self.assertEqual(
                loaded.cost_periods["cumulative"][("Codex", "gpt-test")],
                12.34,
            )

    def test_snapshot_json_creates_missing_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "nested" / "snapshot.json"
            now = datetime.now(timezone.utc)
            snapshot = token_watcher.UsageSnapshot(
                periods={period: {} for period in token_watcher.PERIODS},
                call_periods={period: {} for period in token_watcher.PERIODS},
                cost_periods={period: {} for period in token_watcher.PERIODS},
                updated_at=now,
                report_time=now,
                source_status=(),
            )

            class FakeEngine:
                def refresh_once(self):
                    return snapshot

                def stop(self):
                    return None

            with patch.object(
                token_watcher.sys,
                "argv",
                ["token_watcher.py", "--snapshot-json", str(output_path)],
            ), patch.object(token_watcher, "UsageEngine", return_value=FakeEngine()):
                self.assertEqual(token_watcher.main(), 1)
            self.assertTrue(output_path.exists())

    def test_snapshot_cache_clears_today_after_shanghai_midnight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "usage_snapshot_cache.json"
            key = ("Codex", "gpt-test")
            today = datetime.now(token_watcher.SHANGHAI).date()
            yesterday = today - timedelta(days=1)
            previous = datetime.combine(
                yesterday,
                datetime.min.time(),
                tzinfo=token_watcher.SHANGHAI,
            )
            periods = {
                period: {key: 123} for period in token_watcher.PERIODS
            }
            calls = {
                period: {key: 4} for period in token_watcher.PERIODS
            }
            costs = {
                period: {key: 1.25} for period in token_watcher.PERIODS
            }
            snapshot = token_watcher.UsageSnapshot(
                periods=periods,
                call_periods=calls,
                cost_periods=costs,
                updated_at=previous,
                report_time=previous,
                source_status=("cached",),
            )
            payload = {
                "version": token_watcher.USAGE_SNAPSHOT_CACHE_VERSION,
                "period_date": yesterday.isoformat(),
                "report_dir": str(root.resolve()),
                "snapshot": token_watcher.usage_snapshot_to_json(snapshot),
            }
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            reader = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=cache_path,
            )
            loaded = reader.get_snapshot()
            assert loaded is not None
            self.assertEqual(loaded.periods["cumulative"][key], 123)
            self.assertFalse(loaded.periods["today"])
            self.assertFalse(loaded.call_periods["today"])
            self.assertFalse(loaded.cost_periods["today"])

    def test_report_preview_is_available_when_snapshot_cache_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "summary.json").write_text(
                json.dumps(
                    {"refreshed_at_shanghai": "2026-07-14T02:00:00+08:00"}
                ),
                encoding="utf-8",
            )
            (root / "model_total.csv").write_text(
                "platform,model,total_tokens\nCodex,gpt-preview,456\n",
                encoding="utf-8",
            )
            engine = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=root / "missing-cache.json",
            )
            preview = engine.get_snapshot()
            self.assertIsNotNone(preview)
            assert preview is not None
            self.assertEqual(
                preview.periods["cumulative"][("Codex", "gpt-preview")],
                456,
            )
            self.assertIn("Baseline report preview", preview.source_status[0])

    def test_usage_snapshot_cache_does_not_rewrite_unchanged_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "usage_snapshot_cache.json"
            now = datetime.now(timezone.utc)
            snapshot = token_watcher.UsageSnapshot(
                periods={period: {} for period in token_watcher.PERIODS},
                call_periods={period: {} for period in token_watcher.PERIODS},
                updated_at=now,
                report_time=now,
                source_status=(),
            )
            first = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=cache_path,
            )
            first.snapshot = snapshot
            first.stop()

            second = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=cache_path,
            )
            with patch.object(token_watcher.os, "replace") as replace:
                second.stop()
            replace.assert_not_called()

    def test_usage_snapshot_cache_is_scoped_to_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_report = root / "first"
            second_report = root / "second"
            first_report.mkdir()
            second_report.mkdir()
            cache_path = root / "usage_snapshot_cache.json"
            now = datetime.now(timezone.utc)
            snapshot = token_watcher.UsageSnapshot(
                periods={period: {} for period in token_watcher.PERIODS},
                call_periods={period: {} for period in token_watcher.PERIODS},
                updated_at=now,
                report_time=now,
                source_status=(),
            )
            writer = token_watcher.UsageEngine(
                report_dir=first_report,
                snapshot_cache_path=cache_path,
            )
            writer.snapshot = snapshot
            writer.stop()

            reader = token_watcher.UsageEngine(
                report_dir=second_report,
                snapshot_cache_path=cache_path,
            )
            self.assertIsNone(reader.get_snapshot())

    def test_background_loop_saves_snapshot_only_after_first_refresh(self) -> None:
        class StopAfterThreeWaits:
            def __init__(self) -> None:
                self.waits = 0

            def is_set(self) -> bool:
                return self.waits >= 3

            def wait(self, _timeout: float) -> bool:
                self.waits += 1
                return False

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            engine = token_watcher.UsageEngine(
                report_dir=root,
                snapshot_cache_path=root / "usage_snapshot_cache.json",
            )
            engine.stop_event = StopAfterThreeWaits()
            with patch.object(engine, "refresh_once"), patch.object(
                engine, "_save_snapshot_cache"
            ) as save:
                engine._run()
            self.assertEqual(save.call_count, 1)

    def test_codex_cold_files_are_not_polled_and_changes_are_event_driven(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "13"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            cold = session_dir / "cold.jsonl"
            hot = session_dir / "hot.jsonl"
            cold.write_text(self._codex_lines("cold", 1, now), encoding="utf-8")
            hot.write_text(self._codex_lines("hot", 10, now), encoding="utf-8")
            old = time.time() - 3600
            os.utime(cold, (old, old))
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=2), watcher=watcher
                )

            self.assertFalse(tracker.states[cold].watching)
            self.assertTrue(tracker.states[hot].watching)
            original_stat = token_watcher.Path.stat
            touched: list[Path] = []

            def counted_stat(path: Path, *args, **kwargs):
                touched.append(path)
                return original_stat(path, *args, **kwargs)

            with patch.object(token_watcher.Path, "rglob", side_effect=AssertionError), patch.object(
                token_watcher.Path, "stat", counted_stat
            ):
                tracker.poll()
            self.assertNotIn(cold, touched)
            self.assertNotIn(hot, touched)

            with cold.open("a", encoding="utf-8") as handle:
                handle.write(self._codex_lines("cold", 20, now + timedelta(seconds=1)))
            watcher.emit(cold)
            tracker.poll()
            self.assertTrue(tracker.states[cold].watching)
            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 31
            )

    def test_new_empty_codex_file_remains_watched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "13"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )
            new_file = session_dir / "new-empty.jsonl"
            new_file.touch()
            watcher.emit(new_file)
            tracker.poll()
            self.assertTrue(tracker.states[new_file].watching)

            new_file.write_text(
                self._codex_lines("new", 30, now + timedelta(seconds=1)),
                encoding="utf-8",
            )
            watcher.emit(new_file)
            tracker.poll()
            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 30
            )

    def test_codex_notification_loss_resyncs_cold_and_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "22"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            cold = session_dir / "cold.jsonl"
            cold.write_text(self._codex_lines("cold", 1, now), encoding="utf-8")
            old = time.time() - 3600
            os.utime(cold, (old, old))
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )
            self.assertFalse(tracker.states[cold].watching)

            with cold.open("a", encoding="utf-8") as handle:
                handle.write(self._codex_lines("cold", 20, now + timedelta(seconds=1)))
            new_file = session_dir / "new.jsonl"
            new_file.write_text(
                self._codex_lines("new", 30, now + timedelta(seconds=2)),
                encoding="utf-8",
            )
            watcher.lose_changes()
            tracker.poll()

            self.assertTrue(tracker.states[cold].watching)
            self.assertIn(new_file, tracker.states)
            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 51
            )
            with patch.object(token_watcher.Path, "rglob", side_effect=AssertionError):
                tracker.poll()

    def test_codex_repeated_cumulative_snapshots_are_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "14"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            original = session_dir / "original.jsonl"
            forked = session_dir / "forked.jsonl"
            original.write_text(
                self._codex_lines("shared-session", 10, now, cumulative=10),
                encoding="utf-8",
            )
            forked.write_text(
                self._codex_lines(
                    "shared-session",
                    10,
                    now + timedelta(seconds=1),
                    cumulative=10,
                )
                + self._codex_lines(
                    "shared-session",
                    20,
                    now + timedelta(seconds=2),
                    cumulative=30,
                ),
                encoding="utf-8",
            )
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )

            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 30
            )
            self.assertEqual(
                tracker.call_periods["cumulative"][("Codex", "gpt-test")], 2
            )

    def test_codex_subagent_replayed_parent_history_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "08" / "01"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            parent = session_dir / "a-parent.jsonl"
            child = session_dir / "z-child.jsonl"
            parent.write_text(
                self._codex_lines(
                    "parent-session",
                    10,
                    now,
                    cumulative=10,
                ),
                encoding="utf-8",
            )
            child.write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "child-session",
                                    "parent_thread_id": "parent-session",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": (now + timedelta(seconds=1)).isoformat(),
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {"total_tokens": 10},
                                        "total_token_usage": {"total_tokens": 10},
                                    },
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": (now + timedelta(seconds=2)).isoformat(),
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {"total_tokens": 20},
                                        "total_token_usage": {"total_tokens": 30},
                                    },
                                },
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=FakeWatcher()
                )

            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 30
            )
            self.assertEqual(
                tracker.call_periods["cumulative"][("Codex", "gpt-test")], 2
            )

    def test_codex_subagent_without_turn_context_inherits_parent_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "27"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            child = session_dir / "a-child.jsonl"
            parent = session_dir / "z-parent.jsonl"
            child.write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "child-session",
                                    "parent_thread_id": "parent-session",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": now.isoformat(),
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {"total_tokens": 25}
                                    },
                                },
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            parent.write_text(
                self._codex_lines(
                    "parent-session",
                    10,
                    now + timedelta(seconds=1),
                ),
                encoding="utf-8",
            )

            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=FakeWatcher()
                )

            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 35
            )
            self.assertNotIn(
                ("Codex", "<unknown>"), tracker.periods["cumulative"]
            )
            self.assertEqual(tracker.states[child].model, "gpt-test")
            self.assertFalse(tracker.pending_usage)

    def test_codex_fork_rewritten_history_is_seeded_without_counting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "14"
            session_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            baseline_time = now - timedelta(hours=1)
            root_session = "root-session"
            original = session_dir / "rollout-2026-07-14T00-00-00-original.jsonl"
            forked = session_dir / "rollout-2026-07-14T01-00-00-forked.jsonl"
            original.write_text(
                self._codex_lines(
                    root_session,
                    10,
                    now - timedelta(hours=2),
                    cumulative=10,
                ),
                encoding="utf-8",
            )
            child_meta = json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "child-session",
                        "forked_from_id": root_session,
                    },
                }
            ) + "\n"
            forked.write_text(
                child_meta
                + self._codex_lines(
                    root_session,
                    10,
                    now,
                    cumulative=10,
                )
                + self._codex_lines(
                    root_session,
                    20,
                    now + timedelta(seconds=1),
                    cumulative=30,
                ),
                encoding="utf-8",
            )
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    baseline_time, watcher=watcher
                )

            self.assertEqual(
                tracker.periods["cumulative"][("Codex", "gpt-test")], 20
            )
            self.assertEqual(
                tracker.call_periods["cumulative"][("Codex", "gpt-test")], 1
            )

    def test_codex_cache_skips_unchanged_jsonl_files_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "14"
            session_dir.mkdir(parents=True)
            cache_path = home / ".tokenwatcher" / "codex_fingerprint_cache.json"
            now = datetime.now(timezone.utc)
            log_path = session_dir / "rollout-2026-07-14T00-00-00-cache.jsonl"
            log_path.write_text(
                self._codex_lines("cache-session", 10, now, cumulative=10),
                encoding="utf-8",
            )
            with patch.object(token_watcher.Path, "home", return_value=home):
                first = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            first.close()
            self.assertTrue(cache_path.exists())

            original_open = token_watcher.Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path.suffix.lower() == ".jsonl":
                    raise AssertionError(f"unexpected JSONL read: {path}")
                return original_open(path, *args, **kwargs)

            with patch.object(token_watcher.Path, "home", return_value=home), patch.object(
                token_watcher.Path, "open", guarded_open
            ):
                second = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            self.assertEqual(second.states[log_path].offset, log_path.stat().st_size)
            self.assertEqual(
                second.periods["cumulative"][("Codex", "gpt-test")],
                10,
            )
            second.close()

    def test_codex_cache_tails_only_bytes_appended_after_cached_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "14"
            session_dir.mkdir(parents=True)
            cache_path = home / ".tokenwatcher" / "codex_fingerprint_cache.json"
            now = datetime.now(timezone.utc)
            log_path = session_dir / "rollout-2026-07-14T00-00-00-tail.jsonl"
            log_path.write_text(
                self._codex_lines("tail-session", 10, now, cumulative=10),
                encoding="utf-8",
            )
            with patch.object(token_watcher.Path, "home", return_value=home):
                first = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            first.close()
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    self._codex_lines(
                        "tail-session",
                        20,
                        now + timedelta(seconds=1),
                        cumulative=30,
                    )
                )

            with patch.object(token_watcher.Path, "home", return_value=home):
                second = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            self.assertEqual(
                second.periods["cumulative"][("Codex", "gpt-test")], 30
            )
            self.assertEqual(
                second.call_periods["cumulative"][("Codex", "gpt-test")], 2
            )
            second.close()

    def test_codex_cache_reuses_offsets_but_clears_delta_after_report_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "14"
            session_dir.mkdir(parents=True)
            cache_path = home / ".tokenwatcher" / "codex_fingerprint_cache.json"
            now = datetime.now(timezone.utc)
            log_path = session_dir / "session.jsonl"
            log_path.write_text(
                self._codex_lines("boundary-session", 10, now, cumulative=10),
                encoding="utf-8",
            )
            with patch.object(token_watcher.Path, "home", return_value=home):
                first = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            first.close()

            original_open = token_watcher.Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path.suffix.lower() == ".jsonl":
                    raise AssertionError(f"unexpected Codex JSONL read: {path}")
                return original_open(path, *args, **kwargs)

            with patch.object(token_watcher.Path, "home", return_value=home), patch.object(
                token_watcher.Path, "open", guarded_open
            ):
                second = token_watcher.CodexTailTracker(
                    now + timedelta(seconds=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            self.assertFalse(second.periods["cumulative"])
            self.assertFalse(second.seen_packed)
            self.assertFalse(second.seen)
            self.assertEqual(second.states[log_path].offset, log_path.stat().st_size)
            second.close()

    def test_codex_fingerprints_are_compact_binary_values(self) -> None:
        digest = token_watcher.codex_fingerprint_digest(("session", 123))
        self.assertIsInstance(digest, bytes)
        self.assertEqual(len(digest), 16)

    def test_old_codex_cache_is_rebuilt_for_cost_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "18"
            session_dir.mkdir(parents=True)
            cache_path = home / ".tokenwatcher" / "codex_fingerprint_cache.json"
            now = datetime.now(timezone.utc)
            path = session_dir / "session.jsonl"
            path.write_text(self._codex_lines("legacy", 1, now), encoding="utf-8")
            with patch.object(token_watcher.Path, "home", return_value=home):
                first = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            first.close()
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["version"] = token_watcher.CODEX_CACHE_VERSION - 1
            payload["fingerprints_b64"] = "AAECAwQFBgcICQoLDA0ODw=="
            cache_path.write_text(json.dumps(payload), encoding="utf-8")

            with patch.object(token_watcher.Path, "home", return_value=home):
                second = token_watcher.CodexTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            self.assertEqual(second.fingerprint_count(), 1)
            self.assertEqual(second.states[path].offset, path.stat().st_size)
            second.close()
            rebuilt = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["version"], token_watcher.CODEX_CACHE_VERSION)
            self.assertIn("cost_periods", rebuilt)

    def test_compact_codex_fingerprint_store_keeps_exact_membership(self) -> None:
        tracker = object.__new__(token_watcher.CodexTailTracker)
        tracker.seen_packed = b""
        tracker.seen = {
            bytes([index]) * 16 for index in range(32)
        }
        tracker._compact_fingerprints()
        self.assertFalse(tracker.seen)
        self.assertEqual(tracker.fingerprint_count(), 32)
        for index in range(32):
            self.assertTrue(tracker._has_fingerprint(bytes([index]) * 16))
        self.assertFalse(tracker._has_fingerprint(b"x" * 16))

    def test_codex_fallback_poll_is_throttled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            session_dir = home / ".codex" / "sessions" / "2026" / "07" / "18"
            session_dir.mkdir(parents=True)
            path = session_dir / "session.jsonl"
            now = datetime.now(timezone.utc)
            path.write_text(self._codex_lines("fallback", 1, now), encoding="utf-8")
            watcher = FakeWatcher()
            watcher.available = False
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.CodexTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )
            tracker.next_fallback_check = time.monotonic() + 60
            with patch.object(
                token_watcher.Path,
                "stat",
                side_effect=AssertionError("fallback poll was not throttled"),
            ):
                tracker.poll()

    def test_reference_file_caches_do_not_stat_every_refresh(self) -> None:
        today = datetime.now(token_watcher.SHANGHAI).date()
        claude_cache = token_watcher.ClaudeUsageCache()
        claude_cache.cached = (
            token_watcher.empty_periods(),
            "cached",
            datetime.now(token_watcher.SHANGHAI),
        )
        claude_cache.period_date = today
        claude_cache.next_check = time.monotonic() + 60
        with patch.object(
            token_watcher.Path,
            "stat",
            side_effect=AssertionError("unexpected Claude stats-cache stat"),
        ):
            self.assertEqual(claude_cache.read()[1], "cached")

        cline_cache = token_watcher.ClineTaskCache()
        cline_cache.cached = {
            "task": ("cline-test", 1, datetime.now(token_watcher.SHANGHAI))
        }
        cline_cache.next_check = time.monotonic() + 60
        with patch.object(
            token_watcher.Path,
            "stat",
            side_effect=AssertionError("unexpected Cline taskHistory stat"),
        ):
            self.assertIn("task", cline_cache.read())

    def test_claude_stats_and_active_periods_include_cached_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / ".claude"
            project_dir = root / "projects" / "project"
            project_dir.mkdir(parents=True)
            today = datetime.now(token_watcher.SHANGHAI).date()
            event_time = datetime.combine(
                today,
                datetime.min.time(),
                tzinfo=token_watcher.SHANGHAI,
            ) + timedelta(hours=12)
            stats_path = root / "stats-cache.json"
            stats_path.write_text(
                json.dumps(
                    {
                        "lastComputedDate": (today + timedelta(days=3)).isoformat(),
                        "modelUsage": {
                            "claude-test": {
                                "inputTokens": 100,
                                "outputTokens": 10,
                                "cacheReadInputTokens": 20,
                                "cacheCreationInputTokens": 5,
                            }
                        },
                        "dailyModelTokens": [
                            {
                                "date": today.isoformat(),
                                "tokensByModel": {"claude-test": 110},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (project_dir / "session.jsonl").write_text(
                self._claude_line(
                    "cached",
                    100,
                    event_time,
                    cached=20,
                    cache_created=5,
                    output=10,
                ),
                encoding="utf-8",
            )

            periods, status, boundary = token_watcher._parse_claude_usage(stats_path)
            key = ("Claude Code", "claude-test")
            self.assertEqual(periods["cumulative"][key], 135)
            self.assertEqual(periods["today"][key], 135)
            self.assertEqual(
                boundary.date(),
                today + timedelta(days=1),
            )
            self.assertIn("含缓存", status)

    def test_claude_tail_tokens_include_cache_reads_and_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            (project_dir / "session.jsonl").write_text(
                self._claude_line(
                    "cached",
                    5,
                    now,
                    cached=7,
                    cache_created=11,
                    output=3,
                ),
                encoding="utf-8",
            )
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.ClaudeTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=home / "claude.json",
                )
            self.assertEqual(
                tracker.periods["cumulative"][("Claude Code", "claude-test")],
                26,
            )
            tracker.close()

    def test_claude_runtime_changes_do_not_rescan_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            cold = project_dir / "cold.jsonl"
            cold.write_text(self._claude_line("cold", 1, now), encoding="utf-8")
            old = time.time() - 3600
            os.utime(cold, (old, old))
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.ClaudeTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )
            self.assertFalse(tracker.states[cold].watching)
            with patch.object(token_watcher.Path, "rglob", side_effect=AssertionError):
                with patch.object(
                    token_watcher.Path,
                    "stat",
                    side_effect=AssertionError("unexpected idle Claude stat"),
                ):
                    tracker.poll()

            new_file = project_dir / "new.jsonl"
            new_file.touch()
            watcher.emit(new_file)
            tracker.poll()
            self.assertTrue(tracker.states[new_file].watching)
            new_file.write_text(
                self._claude_line("new", 20, now + timedelta(seconds=1)),
                encoding="utf-8",
            )
            watcher.emit(new_file)
            tracker.poll()
            self.assertEqual(
                tracker.periods["cumulative"][("Claude Code", "claude-test")],
                21,
            )

    def test_claude_notification_loss_resyncs_cold_and_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            cold = project_dir / "cold.jsonl"
            cold.write_text(self._claude_line("cold", 1, now), encoding="utf-8")
            old = time.time() - 3600
            os.utime(cold, (old, old))
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.ClaudeTailTracker(
                    now - timedelta(days=1), watcher=watcher
                )
            self.assertFalse(tracker.states[cold].watching)

            with cold.open("a", encoding="utf-8") as handle:
                handle.write(self._claude_line("cold-next", 20, now + timedelta(seconds=1)))
            new_file = project_dir / "new.jsonl"
            new_file.write_text(
                self._claude_line("new", 30, now + timedelta(seconds=2)),
                encoding="utf-8",
            )
            watcher.lose_changes()
            tracker.poll()

            self.assertTrue(tracker.states[cold].watching)
            self.assertIn(new_file, tracker.states)
            self.assertEqual(
                tracker.periods["cumulative"][("Claude Code", "claude-test")],
                51,
            )
            with patch.object(token_watcher.Path, "rglob", side_effect=AssertionError):
                tracker.poll()

    def test_claude_cache_skips_unchanged_jsonl_files_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            cache_path = home / ".tokenwatcher" / "claude_tail_cache.json"
            now = datetime.now(timezone.utc)
            log_path = project_dir / "session.jsonl"
            log_path.write_text(
                self._claude_line("cached", 9, now),
                encoding="utf-8",
            )
            watcher = FakeWatcher()
            with patch.object(token_watcher.Path, "home", return_value=home):
                first = token_watcher.ClaudeTailTracker(
                    now - timedelta(days=1),
                    watcher=watcher,
                    cache_path=cache_path,
                )
            first.close()
            self.assertTrue(cache_path.exists())

            original_open = token_watcher.Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path.suffix.lower() == ".jsonl":
                    raise AssertionError(f"unexpected Claude JSONL read: {path}")
                return original_open(path, *args, **kwargs)

            with patch.object(token_watcher.Path, "home", return_value=home), patch.object(
                token_watcher.Path, "open", guarded_open
            ):
                second = token_watcher.ClaudeTailTracker(
                    now - timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=cache_path,
                )
            self.assertEqual(
                second.periods["cumulative"][("Claude Code", "claude-test")],
                9,
            )
            self.assertEqual(
                second.call_periods["cumulative"][("Claude Code", "claude-test")],
                1,
            )
            second.close()

    def test_claude_single_pass_uses_separate_token_and_call_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            log_path = project_dir / "session.jsonl"
            log_path.write_text(
                self._claude_line("old-token", 5, now - timedelta(hours=2))
                + self._claude_line("new-token", 7, now),
                encoding="utf-8",
            )
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.ClaudeTailTracker(
                    since=now - timedelta(hours=1),
                    call_since=now - timedelta(hours=3),
                    watcher=FakeWatcher(),
                    cache_path=home / "claude.json",
                )
            key = ("Claude Code", "claude-test")
            self.assertEqual(tracker.periods["cumulative"][key], 7)
            self.assertEqual(tracker.call_periods["cumulative"][key], 2)
            tracker.close()

    def test_claude_vendor_cost_uses_stats_cache_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            project_dir = home / ".claude" / "projects" / "project"
            project_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            log_path = project_dir / "session.jsonl"
            line = self._claude_line("priced", 1_000, now).replace(
                "claude-test", "claude-opus-4.8"
            )
            log_path.write_text(line, encoding="utf-8")
            with patch.object(token_watcher.Path, "home", return_value=home):
                tracker = token_watcher.ClaudeTailTracker(
                    since=now - timedelta(days=1),
                    cost_since=now + timedelta(days=1),
                    watcher=FakeWatcher(),
                    cache_path=home / "claude.json",
                )
            key = ("Claude Code", "claude-opus-4.8")
            self.assertAlmostEqual(
                tracker.cost_periods["cumulative"][key],
                0.005,
            )
            tracker.close()

    def test_cline_only_stats_changed_task_files_after_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            history = root / "state" / "taskHistory.json"
            tasks_root = root / "tasks"
            history.parent.mkdir()
            tasks_root.mkdir()
            now = datetime.now(timezone.utc)
            ts = int(now.timestamp() * 1000)
            tasks = {}
            task_paths = []
            for index in range(5):
                task_id = f"task-{index}"
                path = tasks_root / task_id / "ui_messages.json"
                path.parent.mkdir()
                event = {
                    "type": "say",
                    "say": "api_req_started",
                    "text": json.dumps({"tokensIn": 1}),
                    "ts": ts,
                    "modelInfo": {"modelId": "cline-test"},
                }
                path.write_text(json.dumps([event]), encoding="utf-8")
                tasks[task_id] = ("cline-test", 2, now)
                task_paths.append(path)
            watcher = FakeWatcher()
            with patch.object(token_watcher, "CLINE_HISTORY", history), patch.object(
                token_watcher, "CLINE_TASKS", tasks_root
            ):
                counter = token_watcher.ClineRequestCounter(
                    now - timedelta(days=1), watcher=watcher
                )
                counter.poll(tasks)
                original_stat = token_watcher.Path.stat
                touched: list[Path] = []

                def counted_stat(path: Path, *args, **kwargs):
                    touched.append(path)
                    return original_stat(path, *args, **kwargs)

                with patch.object(token_watcher.Path, "stat", counted_stat):
                    counter.poll(tasks)
                self.assertEqual(touched, [])

                changed = task_paths[0]
                data = json.loads(changed.read_text(encoding="utf-8"))
                data.append({**data[0], "ts": ts + 1})
                changed.write_text(json.dumps(data), encoding="utf-8")
                watcher.emit(changed)
                touched.clear()
                with patch.object(token_watcher.Path, "stat", counted_stat):
                    counter.poll(tasks)
                self.assertEqual(touched, [changed])
                self.assertEqual(
                    counter.periods["cumulative"][("Cline", "cline-test")], 6
                )


if __name__ == "__main__":
    unittest.main()

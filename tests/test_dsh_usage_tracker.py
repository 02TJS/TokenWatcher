from __future__ import annotations

import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "dsh_usage_tracker.py"
SPEC = importlib.util.spec_from_file_location("dsh_usage_tracker", MODULE_PATH)
assert SPEC and SPEC.loader
tracker_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tracker_module
SPEC.loader.exec_module(tracker_module)
DshTailTracker = tracker_module.DshTailTracker

NOW = datetime(2026, 3, 10, 12, tzinfo=timezone.utc)


class FakeWatcher:
    def __init__(self, available=True):
        self.available = available
        self.paths = set()
        self.resync = False
        self.closed = False

    def emit(self, path):
        self.paths.add(Path(path))

    def drain(self):
        result, self.paths = self.paths, set()
        return result

    def consume_resync_required(self):
        result, self.resync = self.resync, False
        return result

    def close(self):
        self.closed = True


def event(kind, data=None, **extra):
    return {"type": kind, "data": data or {}, "timestamp": NOW.isoformat(), **extra}


def header(seed=0):
    return event("header", {"header": {"id": "s", "createdAt": NOW.isoformat(), "seedLength": seed,
                                        "config": {"provider": "p", "model": "fallback"}}}, seq=0)


def request(turn=1, step=1, model="m"):
    return event("request", {"provider": "p", "model": model, "turn": turn, "step": step}, seq=1)


def chunk(usage, turn=1, step=1, seq=2):
    return event("assistant/chunk", {"chunk": {"type": "usage", "usage": usage}, "turn": turn, "step": step}, seq=seq)


def final(usage, turn=1, step=1, seq=3, model="m", with_source=True):
    message = {"usage": usage, "content": "ok"}
    if with_source:
        message["source"] = {"provider": "p", "model": model}
    return event("assistant/message", {"message": message, "turn": turn, "step": step}, seq=seq)


def write_lines(path, records, trailing=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(item) if not isinstance(item, str) else item for item in records)
    if trailing:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def raw_frame(payload: bytes) -> bytes:
    # Single-segment frame, one raw last block. Suitable for the structural scanner.
    descriptor = b"\xa0"  # 4-byte frame content size
    block_header = ((len(payload) << 3) | 1).to_bytes(3, "little")
    return tracker_module.ZSTD_MAGIC + descriptor + len(payload).to_bytes(4, "little") + block_header + payload


def frame_payload(frame: bytes) -> bytes:
    return frame[12:]


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sessions"
        self.cache = Path(self.temp.name) / "cache.json"
        self.watcher = FakeWatcher()

    def tearDown(self):
        self.temp.cleanup()

    def test_astra_reprices_cached_steps_without_rereading_logs(self):
        path = self.path()
        usage = {"inputTokens": 100000, "cacheReadTokens": 100000,
                 "cacheWriteTokens": 50000, "outputTokens": 10000}
        write_lines(path, [header(), request(model="gpt-6-astra"),
                           final(usage, model="gpt-6-astra")])
        old = self.tracker(prices={"unrelated": {"input": 1}})
        key = ("DeepSeek Harness", "gpt-6-astra")
        self.assertNotIn(key, old.cost_periods["cumulative"])
        offset = old._files[str(path)]["offset"]
        tokens = old.periods["cumulative"][key]
        old.close()
        with patch.object(DshTailTracker, "_read_raw", side_effect=AssertionError("reread")):
            updated = self.tracker()
        self.assertEqual(updated._files[str(path)]["offset"], offset)
        self.assertEqual(updated.periods["cumulative"][key], tokens)
        self.assertAlmostEqual(updated.cost_periods["cumulative"][key], 2.225)
        updated.close()

    def test_standard_pricing_can_disable_promotions(self):
        path = self.path()
        priced_event = final({"inputTokens": 100_000}, model="gpt-5.6-sol")
        priced_event["timestamp"] = "2026-08-22T12:00:00+00:00"
        write_lines(
            path,
            [
                header(),
                request(model="gpt-5.6-sol"),
                priced_event,
            ],
        )
        promotional = DshTailTracker(
            root=self.root,
            watcher=self.watcher,
            cache_path=self.cache,
            now=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        standard = DshTailTracker(
            root=self.root,
            watcher=self.watcher,
            cache_path=Path(self.temp.name) / "standard-cache.json",
            now=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
            include_promotions=False,
        )
        key = ("DeepSeek Harness", "gpt-5.6-sol")
        self.assertAlmostEqual(promotional.cost_periods["cumulative"][key], 0.4)
        self.assertAlmostEqual(standard.cost_periods["cumulative"][key], 0.5)

    def path(self, a="a", b="b", zstd=False):
        return self.root / a / b / ("session.jsonl.zstd" if zstd else "session.jsonl")

    def test_v4_session_log_name_is_discovered_and_counted(self):
        path = self.root / "a" / "b" / "session.v4.jsonl.zstd"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = (
            json.dumps(header())
            + "\n"
            + json.dumps(final({"inputTokens": 17, "outputTokens": 3}))
            + "\n"
        ).encode()
        if tracker_module._zstandard is None:
            self.skipTest("zstandard not installed")
        path.write_bytes(tracker_module._zstandard.ZstdCompressor().compress(records))
        tracker = self.tracker()
        self.assertIn(str(path.resolve()), tracker._files)
        self.assertEqual(
            tracker.periods["cumulative"][("DeepSeek Harness", "m")],
            20,
        )

    def tracker(self, **kwargs):
        return DshTailTracker(root=self.root, watcher=self.watcher, cache_path=self.cache,
                              now=lambda: NOW, **kwargs)

    def cumulative(self, model="m"):
        return self.current.periods["cumulative"][("DeepSeek Harness", model)]

    def test_usage_chunk_final_replacement_and_reasoning_not_double_counted(self):
        path = self.path()
        write_lines(path, [header(), request(), chunk({"inputTokens": 4, "outputTokens": 3}),
                           final({"inputTokens": 10, "outputTokens": 5, "reasoningTokens": 4})])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 15)
        self.assertEqual(self.current.call_periods["cumulative"][("DeepSeek Harness", "m")], 1)

    def test_usage_only_failure_uses_route_fallback(self):
        path = self.path()
        write_lines(path, [header(), request(model="route"), chunk({"inputTokens": 7}, turn=4, step=2)])
        self.current = self.tracker()
        self.assertEqual(self.cumulative("route"), 7)

    def test_fork_seed_deduplicates_parent_events(self):
        write_lines(self.path(), [header(seed=3), final({"inputTokens": 99}, seq=2),
                                  final({"inputTokens": 5}, turn=2, seq=3)])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 5)

    @unittest.skipIf(tracker_module._zstandard is None, "zstandard not installed")
    def test_zstd_frame_without_content_size_uses_stream_decoder(self):
        path = self.path(zstd=True)
        path.parent.mkdir(parents=True)
        records = (json.dumps(header()) + "\n" + json.dumps(final({"inputTokens": 5})) + "\n").encode()
        frame = tracker_module._zstandard.ZstdCompressor(
            write_checksum=True,
            write_content_size=False,
        ).compress(records)
        path.write_bytes(frame)
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 5)
        self.assertEqual(self.current.errors, 0)

    def test_zstd_multiframe_incremental_and_torn_tail(self):
        path = self.path(zstd=True)
        path.parent.mkdir(parents=True)
        first = raw_frame((json.dumps(header()) + "\n").encode())
        second = raw_frame((json.dumps(request()) + "\n" + json.dumps(final({"inputTokens": 5})) + "\n").encode())
        third = raw_frame((json.dumps(final({"inputTokens": 8}, turn=2)) + "\n").encode())
        path.write_bytes(first + second + third[:-4])
        self.current = self.tracker(frame_decoder=frame_payload)
        self.assertEqual(self.cumulative(), 5)
        old_offset = self.current._files[str(path.resolve())]["offset"]
        with path.open("ab") as handle:
            handle.write(third[-4:])
        self.watcher.emit(path)
        self.current.poll()
        self.assertGreater(self.current._files[str(path.resolve())]["offset"], old_offset)
        self.assertEqual(self.cumulative(), 13)

    def test_raw_partial_line_and_append_only_read_new_bytes(self):
        path = self.path()
        write_lines(path, [header(), request(), final({"inputTokens": 2})], trailing=False)
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 0)
        with path.open("ab") as handle:
            handle.write(b"\n" + (json.dumps(final({"inputTokens": 3}, turn=2)) + "\n").encode())
        reads = []
        original_open = Path.open
        def observed_open(instance, *args, **kwargs):
            handle = original_open(instance, *args, **kwargs)
            if instance == path and "r" in str(args[0] if args else kwargs.get("mode", "r")):
                original_read = handle.read
                def read(size=-1):
                    reads.append(size)
                    return original_read(size)
                handle.read = read
            return handle
        self.watcher.emit(path)
        with patch.object(Path, "open", observed_open):
            self.current.poll()
        self.assertEqual(self.cumulative(), 5)
        self.assertTrue(reads and reads[-1] < path.stat().st_size)

    def test_unchanged_restart_stats_but_does_not_open_artifact(self):
        path = self.path()
        write_lines(path, [header(), request(), final({"inputTokens": 4})])
        first = self.tracker()
        first.close()
        original_open = Path.open
        def guarded_open(instance, *args, **kwargs):
            if instance.resolve() == path.resolve():
                raise AssertionError("unchanged artifact opened")
            return original_open(instance, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            self.current = self.tracker()
        self.assertEqual(self.cumulative(), 4)

    def test_same_named_files_are_independent(self):
        write_lines(self.path("a", "one"), [header(), request(), final({"inputTokens": 2})])
        write_lines(self.path("a", "two"), [header(), request(), final({"inputTokens": 3})])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 5)
        self.assertEqual(len(self.current._files), 2)

    def test_equal_size_rewrite_retracts_old_contribution(self):
        path = self.path()
        write_lines(path, [header(), request(), final({"inputTokens": 8})])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 8)
        old = path.read_text()
        path.write_text(old.replace('"inputTokens": 8', '"inputTokens": 3'))
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
        self.watcher.emit(path)
        self.current.poll()
        self.assertEqual(self.cumulative(), 3)

    def test_resync_reconciles_once_then_cold_idle_does_not_stat_or_scan(self):
        path = self.path()
        write_lines(path, [header(), request(), final({"inputTokens": 1})])
        self.current = self.tracker()
        self.watcher.resync = True
        with patch.object(self.current, "_known_paths", wraps=self.current._known_paths) as scan:
            self.current.poll()
            self.current.poll()
            self.assertEqual(scan.call_count, 1)
        with patch.object(Path, "stat", side_effect=AssertionError("cold stat")):
            self.current.poll()

    def test_compaction_summary_counts_once_by_seq(self):
        summary = event("compaction/summary", {"llmStreamCall": True, "usage": {"inputTokens": 6, "outputTokens": 2},
                                               "provider": "p", "model": "helper"}, seq=9)
        write_lines(self.path(), [header(), summary, summary])
        self.current = self.tracker()
        self.assertEqual(self.cumulative("helper"), 8)
        self.assertEqual(self.current.call_periods["cumulative"][("DeepSeek Harness", "helper")], 1)

    def test_title_usage_and_excluded_provider_are_not_double_counted(self):
        title = event(
            "session/title-llm-usage",
            {
                "requestSeq": 7,
                "titleProvider": "title",
                "route": {"provider": "direct", "model": "title-model"},
                "usage": {"inputTokens": 6, "outputTokens": 2},
            },
            seq=8,
        )
        excluded = final(
            {"inputTokens": 99},
            turn=2,
            seq=9,
            model="db-model",
        )
        excluded["data"]["message"]["source"]["provider"] = "sub2api"
        write_lines(self.path(), [header(), title, excluded])
        self.current = self.tracker(excluded_providers=("sub2api",))
        self.assertEqual(self.cumulative("title-model"), 8)
        self.assertEqual(self.cumulative("db-model"), 0)

    def test_bad_usage_and_bad_json_skip_only_records(self):
        write_lines(self.path(), [header(), request(), "{bad", final({"inputTokens": -1}),
                                  final({"inputTokens": 4}, turn=2)])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 4)
        self.assertGreaterEqual(self.current.errors, 1)

    def test_cache_persistence_and_cost_components(self):
        prices = {"m": {"input": 1, "cached": 2, "cache_write": 3, "output": 4}}
        write_lines(self.path(), [header(), request(), final({"inputTokens": 10, "cacheReadTokens": 20,
                                                               "cacheWriteTokens": 30, "outputTokens": 40})])
        self.current = self.tracker(prices=prices)
        self.assertEqual(self.cumulative(), 100)
        self.assertAlmostEqual(self.current.cost_periods["cumulative"][("DeepSeek Harness", "m")], 300 / 1_000_000)
        self.current.close()
        restored = self.tracker(prices=prices)
        self.assertEqual(restored.periods["cumulative"][("DeepSeek Harness", "m")], 100)

    def test_ignores_paths_outside_exact_layout(self):
        write_lines(self.root / "session.jsonl", [header(), final({"inputTokens": 99})])
        write_lines(self.root / "a" / "b" / "c" / "session.jsonl", [header(), final({"inputTokens": 99})])
        write_lines(self.path(), [header(), request(), final({"inputTokens": 2})])
        self.current = self.tracker()
        self.assertEqual(self.cumulative(), 2)
        outside = Path(self.temp.name) / "session.jsonl"
        write_lines(outside, [header(), final({"inputTokens": 99})])
        self.watcher.emit(outside)
        self.current.poll()
        self.assertEqual(self.cumulative(), 2)


if __name__ == "__main__":
    unittest.main()

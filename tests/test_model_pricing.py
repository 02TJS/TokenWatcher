from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "model_pricing.py"
SPEC = importlib.util.spec_from_file_location("model_pricing", MODULE_PATH)
assert SPEC and SPEC.loader
pricing = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pricing
SPEC.loader.exec_module(pricing)

UTC = timezone.utc


class ModelPricingTests(unittest.TestCase):
    def test_aliases_resolve_without_changing_unknown_models(self) -> None:
        self.assertEqual(
            pricing.canonical_model("claude-opus-4.8"),
            "claude-opus-4-8",
        )
        self.assertEqual(
            pricing.canonical_model("deepseek-v4-flash-0731"),
            "deepseek-v4-flash",
        )
        self.assertEqual(
            pricing.canonical_model("deepseek-v4-pro[1m]"),
            "deepseek-v4-pro",
        )
        self.assertEqual(pricing.canonical_model("unknown-new-model"), "unknown-new-model")

    def test_deepseek_cutover_and_peak_boundaries_use_utc(self) -> None:
        before = datetime(2026, 8, 16, 15, 59, 59, tzinfo=UTC)
        cutoff = datetime(2026, 8, 16, 16, 0, 0, tzinfo=UTC)
        monday_0059 = datetime(2026, 8, 17, 0, 59, 59, tzinfo=UTC)
        monday_0100 = datetime(2026, 8, 17, 1, 0, 0, tzinfo=UTC)
        monday_0400 = datetime(2026, 8, 17, 4, 0, 0, tzinfo=UTC)
        monday_0600 = datetime(2026, 8, 17, 6, 0, 0, tzinfo=UTC)
        monday_1000 = datetime(2026, 8, 17, 10, 0, 0, tzinfo=UTC)
        saturday_0100 = datetime(2026, 8, 22, 1, 0, 0, tzinfo=UTC)

        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", before), "legacy")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", cutoff), "offpeak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", monday_0059), "offpeak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", monday_0100), "peak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", monday_0400), "offpeak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", monday_0600), "peak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", monday_1000), "offpeak")
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", saturday_0100), "offpeak")

    def test_deepseek_legacy_peak_and_offpeak_costs(self) -> None:
        usage = dict(
            input_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=0,
            output_tokens=1_000_000,
        )
        legacy = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 16, 15, tzinfo=UTC),
            **usage,
        )
        peak = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 17, 1, tzinfo=UTC),
            **usage,
        )
        offpeak = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 22, 1, tzinfo=UTC),
            **usage,
        )
        self.assertAlmostEqual(legacy, 0.4228)
        self.assertAlmostEqual(peak, 1.774)
        self.assertAlmostEqual(offpeak, 0.887)

    def test_openai_56_historical_and_current_standard_prices(self) -> None:
        usage = dict(
            input_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=1_000_000,
        )
        terra_before = pricing.usage_cost_usd(
            "gpt-5.6-terra",
            event_time=datetime(2026, 7, 29, tzinfo=UTC),
            long_context=False,
            **usage,
        )
        terra_after = pricing.usage_cost_usd(
            "gpt-5.6-terra",
            event_time=datetime(2026, 7, 30, tzinfo=UTC),
            long_context=False,
            **usage,
        )
        sol_before_promotion = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 8, 20, tzinfo=UTC),
            long_context=False,
            include_promotions=True,
            **usage,
        )
        sol_standard = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 8, 27, tzinfo=UTC),
            long_context=False,
            **usage,
        )
        sol_promotion = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 8, 27, tzinfo=UTC),
            long_context=False,
            include_promotions=True,
            **usage,
        )
        self.assertEqual(terra_before, 17.5)
        self.assertEqual(terra_after, 14.0)
        self.assertEqual(sol_before_promotion, 35.0)
        self.assertEqual(sol_standard, 35.0)
        self.assertEqual(sol_promotion, 24.0)

    def test_grok_long_context_is_inclusive_at_200k(self) -> None:
        short = pricing.usage_cost_usd(
            "grok-4.5",
            input_tokens=199_999,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=1_000,
        )
        long = pricing.usage_cost_usd(
            "grok-4.5",
            input_tokens=200_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=1_000,
        )
        self.assertAlmostEqual(short, 0.405998)
        self.assertAlmostEqual(long, 0.812)

    def test_glm_prices_and_unpriced_models(self) -> None:
        glm = pricing.usage_cost_usd(
            "glm-5",
            input_tokens=100_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=0,
            output_tokens=10_000,
        )
        self.assertAlmostEqual(glm, 0.332)
        for model in (
            "<unknown>",
            "codex-auto-review",
            "gpt-5.6-col",
            "qwen3.8-chat",
            "made-up",
        ):
            self.assertIsNone(
                pricing.usage_cost_usd(
                    model,
                    input_tokens=1,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    output_tokens=0,
                )
            )

    def test_openai_long_context_boundary_uses_prompt_including_cached(self) -> None:
        usage = dict(cache_read_tokens=0, cache_write_tokens=0, output_tokens=0)
        at = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            input_tokens=272_000,
            **usage,
        )
        over = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            input_tokens=272_001,
            **usage,
        )
        self.assertAlmostEqual(at, 1.36)
        self.assertAlmostEqual(over, 2.72001)
        cache_crossed = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            input_tokens=200_000,
            cache_read_tokens=72_001,
            cache_write_tokens=0,
            output_tokens=0,
        )
        # 输入按 long_input、缓存命中按 long_cached 分别计价。
        self.assertAlmostEqual(cache_crossed, 2.072001)

    def test_deepseek_shanghai_and_utc_cutover_instants_agree(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        utc_instant = datetime(2026, 8, 16, 16, 0, 0, tzinfo=UTC)
        shanghai_instant = utc_instant.astimezone(shanghai)
        self.assertEqual(
            pricing.pricing_bucket("deepseek-v4-flash", shanghai_instant),
            pricing.pricing_bucket("deepseek-v4-flash", utc_instant),
        )
        self.assertEqual(
            pricing.pricing_bucket("deepseek-v4-flash", shanghai_instant),
            "offpeak",
        )
        before = datetime(2026, 8, 16, 23, 59, 59, tzinfo=shanghai)
        self.assertEqual(pricing.pricing_bucket("deepseek-v4-flash", before), "legacy")

    def test_promotion_only_applies_inside_guaranteed_window(self) -> None:
        usage = dict(
            input_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=1_000_000,
            include_promotions=True,
            long_context=False,
        )
        before = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 8, 20, 23, 59, 59, tzinfo=UTC),
            **usage,
        )
        start = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 8, 21, 0, 0, 0, tzinfo=UTC),
            **usage,
        )
        last_day = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 11, 21, 23, 59, 59, tzinfo=UTC),
            **usage,
        )
        after = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=datetime(2026, 11, 22, 0, 0, 0, tzinfo=UTC),
            **usage,
        )
        no_time = pricing.usage_cost_usd(
            "gpt-5.6-sol",
            event_time=None,
            **usage,
        )
        self.assertEqual(before, 35.0)
        self.assertEqual(start, 24.0)
        self.assertEqual(last_day, 24.0)
        self.assertEqual(after, 35.0)
        self.assertEqual(no_time, 35.0)

    def test_missing_cache_write_rate_fails_closed_as_unpriced(self) -> None:
        for model in ("gpt-5.4", "grok-4.5", "gpt-5.2-codex"):
            self.assertIsNone(
                pricing.usage_cost_usd(
                    model,
                    input_tokens=1_000,
                    cache_read_tokens=0,
                    cache_write_tokens=1,
                    output_tokens=0,
                )
            )

    def test_deepseek_cache_write_uses_cache_miss_rate(self) -> None:
        # 2026-08-17 是周一，UTC 02:00 处于峰时窗口。
        cost = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 17, 2, 0, 0, tzinfo=UTC),
            input_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=1_000_000,
            output_tokens=0,
        )
        self.assertAlmostEqual(cost, 0.44)
        offpeak = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 17, 5, 0, 0, tzinfo=UTC),
            input_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=1_000_000,
            output_tokens=0,
        )
        self.assertAlmostEqual(offpeak, 0.22)

    def test_alias_prices_through_canonical_model(self) -> None:
        dotted = pricing.usage_cost_usd(
            "claude-opus-4.8",
            input_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=0,
        )
        dashed = pricing.usage_cost_usd(
            "claude-opus-4-8",
            input_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=0,
        )
        self.assertEqual(dotted, dashed)
        self.assertEqual(dotted, 5.0)

    def test_deepseek_without_event_time_is_explicit_unpriced(self) -> None:
        self.assertIsNone(
            pricing.usage_cost_usd(
                "deepseek-v4-pro",
                input_tokens=1_000,
                cache_read_tokens=0,
                cache_write_tokens=0,
                output_tokens=0,
            )
        )
        self.assertEqual(
            pricing.pricing_bucket("deepseek-v4-pro", None),
            "unknown_time",
        )

    def test_deepseek_vision_exp_is_official_and_matches_flash_rates(self) -> None:
        usage = dict(
            input_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        peak = pricing.usage_cost_usd(
            "deepseek-v4-flash-vision-exp",
            event_time=datetime(2026, 8, 17, 2, 0, 0, tzinfo=UTC),
            **usage,
        )
        flash_peak = pricing.usage_cost_usd(
            "deepseek-v4-flash",
            event_time=datetime(2026, 8, 17, 2, 0, 0, tzinfo=UTC),
            **usage,
        )
        offpeak = pricing.usage_cost_usd(
            "deepseek-v4-flash-vision-exp",
            event_time=datetime(2026, 8, 17, 5, 0, 0, tzinfo=UTC),
            **usage,
        )
        self.assertEqual(peak, flash_peak)
        # 输入 + 缓存命中 + 缓存写入 + 输出
        self.assertAlmostEqual(offpeak, 1.107)
        self.assertAlmostEqual(peak, 2.214)

    def test_deepseek_pro_0813_is_version_alias_of_pro(self) -> None:
        usage = dict(
            input_tokens=1_000_000,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=1_000_000,
        )
        dated = pricing.usage_cost_usd(
            "deepseek-v4-pro-0813",
            event_time=datetime(2026, 8, 17, 2, 0, 0, tzinfo=UTC),
            **usage,
        )
        canonical = pricing.usage_cost_usd(
            "deepseek-v4-pro",
            event_time=datetime(2026, 8, 17, 2, 0, 0, tzinfo=UTC),
            **usage,
        )
        self.assertEqual(dated, canonical)
        self.assertEqual(pricing.canonical_model("deepseek-v4-pro-0813"), "deepseek-v4-pro")

    def test_gpt6_astra_standard_and_long_context(self) -> None:
        usage = dict(input_tokens=100_000, cache_read_tokens=100_000,
                     cache_write_tokens=50_000, output_tokens=10_000)
        self.assertAlmostEqual(pricing.usage_cost_usd("gpt-6-astra", **usage), 2.225)
        usage["input_tokens"] = 122_000  # exactly 272K: standard
        self.assertAlmostEqual(pricing.usage_cost_usd("gpt-6-astra", **usage), 2.445)
        usage["input_tokens"] += 1  # 272001: full request uses long tier
        self.assertAlmostEqual(pricing.usage_cost_usd("gpt-6-astra", **usage), 4.64002)
        self.assertAlmostEqual(pricing.usage_cost_usd(
            "gpt-6-astra", include_promotions=True,
            event_time=datetime(2026, 9, 5, tzinfo=UTC), **usage), 4.64002)
        self.assertIn("gpt-6-astra", pricing.AUDITED_MODELS)
        self.assertEqual(pricing.MODEL_VERIFIED_ON["gpt-6-astra"], "2026-09-05")
        # Do not silently price ambiguous family/other variant names as Astra.
        self.assertIsNone(pricing.usage_cost_usd("gpt-6", **usage))

    def test_audited_model_set_covers_new_official_skus(self) -> None:
        self.assertIn("deepseek-v4-flash-vision-exp", pricing.AUDITED_MODELS)
        self.assertIn("deepseek-v4-pro-0813", pricing.AUDITED_MODELS)
        self.assertEqual(
            len(pricing.AUDITED_MODELS),
            len(set(pricing.DEFAULT_PRICES) | set(pricing.UNPRICED_MODELS) | set(pricing.MODEL_ALIASES)),
        )


if __name__ == "__main__":
    unittest.main()

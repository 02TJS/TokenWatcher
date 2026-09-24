from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Mapping

PRICE_VERIFIED_ON = "2026-08-27"
# Per-model verification dates avoid claiming older model prices were rechecked.
MODEL_VERIFIED_ON = {"gpt-6-astra": "2026-09-05"}
OPENAI_LONG_CONTEXT_THRESHOLD = 272_000
XAI_LONG_CONTEXT_THRESHOLD = 200_000
DEEPSEEK_TIERED_EFFECTIVE_AT = datetime(2026, 8, 16, 16, tzinfo=timezone.utc)
OPENAI_56_TERRA_LUNA_CUT_AT = datetime(2026, 7, 30, tzinfo=timezone.utc)
OPENAI_56_SOL_PROMO_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)
# 官方文案：促销价“available at least through November 21, 2026”。
# 计价只在该保证窗口内启用促销折扣；窗口结束后回落到标准等价价，
# 且时间未知时不得臆断促销价。
OPENAI_56_SOL_PROMO_UNTIL = datetime(2026, 11, 22, tzinfo=timezone.utc)

MODEL_ALIASES = {
    "claude-opus-4.8": "claude-opus-4-8",
    "deepseek-v4-flash-0731": "deepseek-v4-flash",
    "deepseek-v4-pro[1m]": "deepseek-v4-pro",
    # 官方定价页 MODEL VERSION 列显示 DeepSeek-V4-Pro-0813 是 deepseek-v4-pro
    # 的版本名（与 DeepSeek-V4-Flash-0731 对应 deepseek-v4-flash 同规则）。
    "deepseek-v4-pro-0813": "deepseek-v4-pro",
}

# USD per 1M tokens. These are direct-provider, global/default-service prices.
# gpt-5.6-sol deliberately keeps the non-promotional standard-equivalent rate;
# the currently advertised temporary $4/$20 rate is recorded separately below.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    # https://developers.openai.com/api/docs/models/gpt-6-astra (2026-09-05)
    "gpt-6-astra": {
        "input": 10.0, "cached": 1.0, "cache_write": 12.5, "output": 50.0,
        "long_input": 20.0, "long_cached": 2.0,
        "long_cache_write": 25.0, "long_output": 75.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.2-codex": {"input": 1.75, "cached": 0.175, "output": 14.0},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.0},
    "gpt-5.4": {
        "input": 2.5,
        "cached": 0.25,
        "output": 15.0,
        "long_input": 5.0,
        "long_cached": 0.5,
        "long_output": 22.5,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.5},
    "gpt-5.5": {
        "input": 5.0,
        "cached": 0.5,
        "output": 30.0,
        "long_input": 10.0,
        "long_cached": 1.0,
        "long_output": 45.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.6-sol": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "output": 30.0,
        "long_input": 10.0,
        "long_cached": 1.0,
        "long_cache_write": 12.5,
        "long_output": 45.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.6-terra": {
        "input": 2.0,
        "cached": 0.2,
        "cache_write": 2.5,
        "output": 12.0,
        "long_input": 4.0,
        "long_cached": 0.4,
        "long_cache_write": 5.0,
        "long_output": 18.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.6-luna": {
        "input": 0.2,
        "cached": 0.02,
        "cache_write": 0.25,
        "output": 1.2,
        "long_input": 0.4,
        "long_cached": 0.04,
        "long_cache_write": 0.5,
        "long_output": 1.8,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "claude-opus-4-8": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "cache_write_1h": 10.0,
        "output": 25.0,
    },
    "claude-opus-5": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "cache_write_1h": 10.0,
        "output": 25.0,
    },
    "claude-fable-5": {
        "input": 10.0,
        "cached": 1.0,
        "cache_write": 12.5,
        "cache_write_1h": 20.0,
        "output": 50.0,
    },
    "claude-sonnet-4.6": {
        "input": 3.0,
        "cached": 0.3,
        "cache_write": 3.75,
        "cache_write_1h": 6.0,
        "output": 15.0,
    },
    "deepseek-v4-flash": {
        "input": 0.22,
        "cached": 0.007,
        "cache_write": 0.22,
        "output": 0.66,
        "peak_input": 0.44,
        "peak_cached": 0.014,
        "peak_cache_write": 0.44,
        "peak_output": 1.32,
    },
    "deepseek-v4-pro": {
        "input": 0.66,
        "cached": 0.022,
        "cache_write": 0.66,
        "output": 1.98,
        "peak_input": 1.32,
        "peak_cached": 0.044,
        "peak_cache_write": 1.32,
        "peak_output": 3.96,
    },
    # 官方定价页公开模型列：deepseek-v4-flash / deepseek-v4-pro /
    # deepseek-v4-flash-vision-exp；vision-exp 价目与 flash 完全一致。
    "deepseek-v4-flash-vision-exp": {
        "input": 0.22,
        "cached": 0.007,
        "cache_write": 0.22,
        "output": 0.66,
        "peak_input": 0.44,
        "peak_cached": 0.014,
        "peak_cache_write": 0.44,
        "peak_output": 1.32,
    },
    "glm-4.7": {"input": 0.6, "cached": 0.11, "output": 2.2},
    "glm-5": {"input": 1.0, "cached": 0.2, "output": 3.2},
    "grok-4.5": {
        "input": 2.0,
        "cached": 0.3,
        "output": 6.0,
        "long_input": 4.0,
        "long_cached": 0.6,
        "long_output": 12.0,
        "long_threshold": float(XAI_LONG_CONTEXT_THRESHOLD),
        "long_inclusive": 1.0,
    },
}

# Official legacy prices used only before an explicit change boundary.
LEGACY_PRICES: dict[str, dict[str, float]] = {
    "gpt-5.6-sol": {
        "input": 5.0,
        "cached": 0.5,
        "cache_write": 6.25,
        "output": 30.0,
        "long_input": 10.0,
        "long_cached": 1.0,
        "long_cache_write": 12.5,
        "long_output": 45.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "deepseek-v4-flash": {
        "input": 0.14,
        "cached": 0.0028,
        "cache_write": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input": 0.435,
        "cached": 0.003625,
        "cache_write": 0.435,
        "output": 0.87,
    },
    "gpt-5.6-terra": {
        "input": 2.5,
        "cached": 0.25,
        "cache_write": 3.125,
        "output": 15.0,
        "long_input": 5.0,
        "long_cached": 0.5,
        "long_cache_write": 6.25,
        "long_output": 22.5,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
    "gpt-5.6-luna": {
        "input": 1.0,
        "cached": 0.1,
        "cache_write": 1.25,
        "output": 6.0,
        "long_input": 2.0,
        "long_cached": 0.2,
        "long_cache_write": 2.5,
        "long_output": 9.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    },
}

# The current official Standard-tier advertised rate is temporary and guaranteed
# only until 2026-11-21. It is never used in the report's non-promotional
# standard-equivalent total; live opt-in callers must pass an event time so the
# promotion is only applied inside the guaranteed window.
PROMOTIONAL_PRICES: dict[str, dict[str, float]] = {
    "gpt-5.6-sol": {
        "input": 4.0,
        "cached": 0.4,
        "cache_write": 5.0,
        "output": 20.0,
        "long_input": 8.0,
        "long_cached": 0.8,
        "long_cache_write": 10.0,
        "long_output": 30.0,
        "long_threshold": float(OPENAI_LONG_CONTEXT_THRESHOLD),
    }
}

UNPRICED_MODELS = {
    "<unknown>",
    "codex-auto-review",
    "gpt-5.6-col",
    "qwen3.8-chat",
}

# 全部经审计的模型名：官方现价 + 历史价 + 别名 + 明确未计价。
# 报告与验收使用该集合而非硬编码数量，新模型出现时自动扩展。
AUDITED_MODELS = (
    frozenset(DEFAULT_PRICES) | frozenset(UNPRICED_MODELS) | frozenset(MODEL_ALIASES)
)

PRICE_SOURCES = {
    "OpenAI": "https://developers.openai.com/api/docs/pricing",
    "Anthropic": "https://platform.claude.com/docs/en/about-claude/pricing.md",
    "DeepSeek": "https://api-docs.deepseek.com/quick_start/pricing/",
    "Zhipu BigModel": "https://docs.z.ai/guides/overview/pricing",
    "xAI": "https://docs.x.ai/developers/models/grok-4.5",
}


def canonical_model(model: str) -> str:
    cleaned = str(model or "").strip().casefold()
    return MODEL_ALIASES.get(cleaned, cleaned)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def deepseek_is_peak(value: datetime) -> bool:
    current = _utc(value)
    assert current is not None
    hour = current.hour + current.minute / 60 + current.second / 3600
    return current.weekday() < 5 and (1 <= hour < 4 or 6 <= hour < 10)


def pricing_bucket(model: str, event_time: datetime | None) -> str:
    canonical = canonical_model(model)
    current = _utc(event_time)
    if canonical in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"):
        if current is None:
            return "unknown_time"
        if current < DEEPSEEK_TIERED_EFFECTIVE_AT:
            return "legacy"
        return "peak" if deepseek_is_peak(current) else "offpeak"
    if canonical == "gpt-5.6-sol":
        if current is not None and current < OPENAI_56_SOL_PROMO_AT:
            return "legacy"
    if canonical in ("gpt-5.6-terra", "gpt-5.6-luna"):
        if current is not None and current < OPENAI_56_TERRA_LUNA_CUT_AT:
            return "legacy"
    return "current"


def resolve_price(
    model: str,
    *,
    prices: Mapping[str, Mapping[str, float]] | None = None,
    event_time: datetime | None = None,
    bucket: str | None = None,
    include_promotions: bool = False,
) -> dict[str, float] | None:
    canonical = canonical_model(model)
    if canonical in UNPRICED_MODELS:
        return None
    selected_bucket = bucket or pricing_bucket(canonical, event_time)
    if selected_bucket == "unknown_time":
        return None
    if selected_bucket == "legacy" and canonical in LEGACY_PRICES:
        return dict(LEGACY_PRICES[canonical])
    source = prices or DEFAULT_PRICES
    raw = source.get(model) or source.get(canonical)
    if raw is None:
        return None
    price = {str(key): float(value) for key, value in raw.items()}
    if include_promotions and canonical == "gpt-5.6-sol":
        current = _utc(event_time)
        if (
            current is not None
            and OPENAI_56_SOL_PROMO_AT <= current < OPENAI_56_SOL_PROMO_UNTIL
        ):
            price = dict(PROMOTIONAL_PRICES[canonical])
    if selected_bucket == "peak":
        for field in ("input", "cached", "cache_write", "output"):
            peak_field = f"peak_{field}"
            if peak_field in price:
                price[field] = price[peak_field]
    return price


def usage_cost_usd(
    model: str,
    *,
    input_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
    prices: Mapping[str, Mapping[str, float]] | None = None,
    event_time: datetime | None = None,
    bucket: str | None = None,
    long_context: bool | None = None,
    include_promotions: bool = False,
) -> float | None:
    values = (input_tokens, cache_read_tokens, cache_write_tokens, output_tokens)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        return None
    price = resolve_price(
        model,
        prices=prices,
        event_time=event_time,
        bucket=bucket,
        include_promotions=include_promotions,
    )
    if price is None:
        return None
    if long_context is None:
        threshold = price.get("long_threshold")
        if threshold is None:
            long_context = False
        else:
            prompt_tokens = input_tokens + cache_read_tokens + cache_write_tokens
            long_context = (
                prompt_tokens >= threshold
                if price.get("long_inclusive")
                else prompt_tokens > threshold
            )
    prefix = "long_" if long_context and "long_input" in price else ""
    token_fields = (
        (input_tokens, f"{prefix}input"),
        (cache_read_tokens, f"{prefix}cached"),
        (cache_write_tokens, f"{prefix}cache_write"),
        (output_tokens, f"{prefix}output"),
    )
    total = 0.0
    for tokens, field in token_fields:
        if not tokens:
            continue
        rate = price.get(field)
        if rate is None or not math.isfinite(rate) or rate < 0:
            return None
        total += tokens * rate
    return total / 1_000_000


__all__ = [
    "AUDITED_MODELS",
    "DEFAULT_PRICES",
    "DEEPSEEK_TIERED_EFFECTIVE_AT",
    "LEGACY_PRICES",
    "MODEL_ALIASES",
    "OPENAI_56_SOL_PROMO_AT",
    "OPENAI_56_SOL_PROMO_UNTIL",
    "OPENAI_56_TERRA_LUNA_CUT_AT",
    "PRICE_SOURCES",
    "PRICE_VERIFIED_ON",
    "PROMOTIONAL_PRICES",
    "UNPRICED_MODELS",
    "canonical_model",
    "deepseek_is_peak",
    "pricing_bucket",
    "resolve_price",
    "usage_cost_usd",
]

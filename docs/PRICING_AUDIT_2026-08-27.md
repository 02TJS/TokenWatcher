# TokenWatcher 官方价格核验（2026-08-27）

本文件覆盖 `usage_snapshot_cache.json` 累计快照中实际出现的全部模型名。金额单位均为 **USD / 1M tokens**。默认采用厂商直连 API 的当前公开 Standard/global 按量价；Batch、Flex、Fast/Priority、区域附加费、订阅套餐及协议折扣不混入。带生效时间或峰谷规则的模型必须按事件时间计价。

## 当前价格矩阵

| TokenWatcher 模型名 | 厂商 / 规范模型 | 输入 / Cache miss | 缓存命中 | 缓存写入 | 输出 | 长上下文 / 峰谷 | 状态 |
|---|---|---:|---:|---:|---:|---|---|
| `gpt-5.2-codex` | OpenAI / 同名 | 1.75 | 0.175 | 未单列 | 14.00 | 无阶梯 | 官方 SKU |
| `gpt-5.3-codex` | OpenAI / 同名 | 1.75 | 0.175 | 未单列 | 14.00 | 无阶梯 | 官方 SKU |
| `gpt-5.4` | OpenAI / 同名 | 2.50 | 0.25 | 未单列 | 15.00 | prompt >272K：5.00 / 0.50 / 22.50 | 官方 SKU |
| `gpt-5.4-mini` | OpenAI / 同名 | 0.75 | 0.075 | 未单列 | 4.50 | 无阶梯 | 官方 SKU |
| `gpt-5.5` | OpenAI / 同名 | 5.00 | 0.50 | 未单列 | 30.00 | prompt >272K：10.00 / 1.00 / 45.00 | 官方 SKU |
| `gpt-5.6-sol` | OpenAI / 同名 | 5.00 | 0.50 | 6.25 | 30.00 | prompt >272K：10.00 / 1.00 / 12.50 / 45.00 | 官方 SKU；报告按非促销标准等价价。当前公开促销 Standard-tier 价另列为 4.00 / 0.40 / 5.00 / 20.00，至少持续至 2026-11-21 |
| `gpt-5.6-terra` | OpenAI / 同名 | 2.00 | 0.20 | 2.50 | 12.00 | prompt >272K：4.00 / 0.40 / 5.00 / 18.00 | 官方 SKU |
| `gpt-5.6-luna` | OpenAI / 同名 | 0.20 | 0.02 | 0.25 | 1.20 | prompt >272K：0.40 / 0.04 / 0.50 / 1.80 | 官方 SKU |
| `gpt-5.6-col` | 无可核验公开 SKU | — | — | — | — | — | 未计价，不猜测映射 |
| `codex-auto-review` | OpenAI 内部/功能标签 | — | — | — | — | — | 未计价，不映射到公开 Codex SKU |
| `claude-opus-4-8` | Anthropic / 同名 | 5.00 | 0.50 | 5m 6.25；1h 10.00 | 25.00 | 1M 全窗口标准价不变 | 官方 SKU |
| `claude-opus-4.8` | Anthropic / `claude-opus-4-8` | 5.00 | 0.50 | 5m 6.25；1h 10.00 | 25.00 | 同上 | 本地点号别名 |
| `claude-opus-5` | Anthropic / 同名 | 5.00 | 0.50 | 5m 6.25；1h 10.00 | 25.00 | 1M 全窗口标准价不变 | 官方 SKU |
| `claude-fable-5` | Anthropic / 同名 | 10.00 | 1.00 | 5m 12.50；1h 20.00 | 50.00 | 1M 全窗口标准价不变 | 官方 SKU |
| `claude-sonnet-4.6` | Anthropic / 同名 | 3.00 | 0.30 | 5m 3.75；1h 6.00 | 15.00 | 1M 全窗口标准价不变 | 官方 SKU |
| `deepseek-v4-flash` | DeepSeek / 同名 | 谷 0.22；峰 0.44 | 谷 0.007；峰 0.014 | 未单列，作为 cache miss | 谷 0.66；峰 1.32 | 工作日 UTC 01:00–04:00、06:00–10:00 为峰时 | 官方 SKU |
| `deepseek-v4-flash-0731` | DeepSeek / `deepseek-v4-flash` | 同上 | 同上 | 同上 | 同上 | 同上 | 官方版本别名 |
| `deepseek-v4-pro` | DeepSeek / 同名 | 谷 0.66；峰 1.32 | 谷 0.022；峰 0.044 | 未单列，作为 cache miss | 谷 1.98；峰 3.96 | 工作日 UTC 01:00–04:00、06:00–10:00 为峰时 | 官方 SKU |
| `deepseek-v4-pro[1m]` | DeepSeek / `deepseek-v4-pro` | 同上 | 同上 | 同上 | 同上 | 同上；官方 Pro 本身即 1M context | 本地上下文标签别名 |
| `deepseek-v4-flash-vision-exp` | DeepSeek / 同名 | 谷 0.22；峰 0.44 | 谷 0.007；峰 0.014 | 未单列，作为 cache miss | 谷 0.66；峰 1.32 | 工作日 UTC 01:00–04:00、06:00–10:00 为峰时 | 官方 SKU（定价页第三列，与 flash 同价；图片按输入 token 计费） |
| `deepseek-v4-pro-0813` | DeepSeek / `deepseek-v4-pro` | 同上 | 同上 | 同上 | 同上 | 同上 | 官方版本别名（定价页 MODEL VERSION = DeepSeek-V4-Pro-0813） |
| `glm-4.7` | Z.AI / 同名 | 0.60 | 0.11 | Cached Input Storage 当前限时免费 | 2.20 | 200K context | 官方 SKU |
| `glm-5` | Z.AI / 同名 | 1.00 | 0.20 | Cached Input Storage 当前限时免费 | 3.20 | 200K context | 官方 SKU |
| `grok-4.5` | xAI / 同名 | 2.00 | 0.30 | 未单列 | 6.00 | prompt >=200K：4.00 / 0.60 / 12.00 | 官方 SKU |
| `<unknown>` | 无法识别 | — | — | — | — | — | 未计价，不猜测 |

## 时间版本

- OpenAI `gpt-5.6-terra`、`gpt-5.6-luna`：2026-07-30 调价；此前分别为 2.50/0.25/3.125/15 与 1.00/0.10/1.25/6（输入/缓存命中/缓存写入/输出）。官方只公布日期，计价边界按该日 00:00 UTC 记录并在报告中披露。
- OpenAI `gpt-5.6-sol`：2026-08-21 开始公开促销价，之前及非促销标准等价口径为 5.00/0.50/6.25/30，促销价为 4.00/0.40/5.00/20；长上下文分别应用 2x 输入与 1.5x 输出。为满足报告固定规范，成本汇总不采用促销折扣；促销价作为独立审计信息保留。引擎仅在官方保证窗口（2026-08-21 00:00 UTC 起、2026-11-21 止）内且事件时间已知时才应用促销价，窗口外或时间未知一律回落标准等价价。
- DeepSeek 新峰谷价：2026-08-16 16:00 UTC（上海 2026-08-17 00:00）明确生效。此前 Flash 为 0.14/0.0028/0.28，Pro 为 0.435/0.003625/0.87（cache miss/cache hit/output）。生效后按每次事件的 UTC 星期与时段选择峰/谷价。
- Anthropic 上述模型、OpenAI 5.2/5.3/5.4/5.5、Z.AI GLM 及 xAI Grok 在本地实际使用区间内没有发现需要拆分的公开价格变更。

## 官方来源

- OpenAI：https://developers.openai.com/api/docs/pricing
- OpenAI 模型页：https://developers.openai.com/api/docs/models/gpt-5.2-codex 、`gpt-5.3-codex`、`gpt-5.4`、`gpt-5.4-mini`、`gpt-5.5`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`
- OpenAI 变更日志：https://developers.openai.com/api/docs/changelog
- Anthropic：https://platform.claude.com/docs/en/about-claude/pricing.md
- DeepSeek：https://api-docs.deepseek.com/quick_start/pricing/ 与 https://api-docs.deepseek.com/updates/
- Z.AI：https://docs.z.ai/guides/overview/pricing
- xAI：https://docs.x.ai/developers/models/grok-4.5

## 计算约束

1. 原始模型名必须保留用于审计，别名只影响选价。
2. 缺少官方价格或某个非零 token bucket 的单价时返回“未计价”，不得按 0 或相近模型处理。
3. Reasoning tokens 已包含在供应商的 output token 中时不得再次相加。
4. DeepSeek 峰谷、OpenAI 调价及所有长上下文规则均按单请求事件时间/上下文判断，禁止对整日聚合 token 误触发长上下文。
5. TokenWatcher 正常运行仍只尾读新增日志并使用 sub2api 高水位游标；价格版本更新只允许一次受控缓存迁移，不改变增量设计。

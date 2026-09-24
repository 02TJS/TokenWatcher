# GPT-6 Astra 价格更新（2026-09-05）

官方来源：
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/pricing

单位：USD / 1M tokens，Standard API 等价价，不采用 Batch、Flex、Fast 或区域附加费。

| 模型 | 输入 | 缓存命中 | 缓存写入 | 输出 |
|---|---:|---:|---:|---:|
| gpt-6-astra，prompt ≤272000 | 10 | 1 | 12.5 | 50 |
| gpt-6-astra，prompt >272000 | 20 | 2 | 25 | 75 |

阈值逐请求判断，输入由非缓存输入、缓存命中和缓存写入组成；缓存 token 仍按各自单价计费。推理输出包含在 output 内，不重复相加。不将含糊的 gpt-6 或其他变体名称擅自映射到 Astra。

GPT-6 核验日期独立记录为 2026-09-05；其余模型保留原核验日期，避免声称重新核验所有模型。

增量约束：DSH 使用已缓存的逐步骤 usage 在启动时重新计价，保留文件偏移，无需清空 DSH 缓存或重读全部历史。sub2api 原有日聚合丢失了 GPT-6 的长上下文分档，价格 schema 更新后执行一次受控数据库重建，随后继续严格 id > cursor。Codex 历史成本由规定的一键报告刷新更新，不手工修改报告产物。

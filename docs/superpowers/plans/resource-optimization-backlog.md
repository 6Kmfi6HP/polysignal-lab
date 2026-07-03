# Resource Optimization Backlog

> 2026-07-03 修订：前 6 轮微优化未解决实际资源问题，已按实测证据重新定位根因并修复。

## 复盘：为什么前 6 轮优化无效

前 6 轮优化（`652b1c9`…`ffe31db`）全部针对评估热路径上 **微秒级 CPU 开销**（O(N) 扫描、Pydantic 拷贝/getattr、computed_field 遍历）。但运行时实测显示真实的资源消耗是 **I/O 与累积**，两者不在同一量级：

| 实测指标（2026-07-03，运行 ~4h） | 数值 | 微优化可影响？ |
|---|---|---|
| 进程 RSS | 558 MB → 3.9 GB | 否 |
| `markets.jsonl` 增长 | ~909 KB/min（1.29 GB 累积） | 否 |
| `rejected_signals.jsonl` + `nautilus_decisions.jsonl` | 695 MB + 437 MB（各 ~338k 行） | 否 |
| SQLite | 2.14 GB（99.6% 为 nautilus_decision/rejected_signals 行） | 否 |
| CPU | ~70–97% | 边际（µs 级节省 vs 每 tick 全量评估 + 持久化） |

处置：4 个提交保留（`652b1c9` 反向索引、`95e6a81` 有界 deque、`95aeb5f` 浅拷贝、`9de5473` trades deque），4 个提交回退（`3f42fbe`/`8b91267` 在 registry 模式下引入 last-trade 冻结与缓存过期正确性缺陷、`ffe31db` 依赖前者、`74e81fc` 文档结论与实测矛盾）。

## 根因与修复（按实测证据）

| # | 根因 | 证据 | 修复 | 提交 |
|---|------|------|------|------|
| 1 | `MarketUniverseService.refresh_once` 每 10s 对每个活跃市场无条件追加 ~10KB 完整 Gamma payload 到 `markets.jsonl` | 实测 +909 KB/min；文件 1.29 GB，135k 行几乎全为重复 payload | 与 registry 中副本比较，仅在市场新增或内容变化时追加；SQLite upsert 行为不变 | `76d25a9` |
| 2 | 每个 quote tick 触发全量策略评估，并将相同的拒绝决策（98% `DUPLICATE_SIGNAL`）逐条写入 SQLite + JSONL，入市窗口内 ~220 写/秒 | 338k rejected_signals 行 + 339k nautilus_decision 行/天；热路径上 json.dumps + 带锁 SQLite insert | `ObservabilityActor` 对相同 (strategy, market, side, reason) 的拒绝记录做 60s TTL 抑制；accepted 决策永不抑制（设计规范中已预留的 "rejected decision sampling"） | `e3138e0` |
| 3 | Nautilus Cache 默认 `tick_capacity=10000`：每 instrument 保留 1 万 quote + 1 万 trade tick，市场轮换每小时订阅 ~128 个新 instrument 且缓存从不清除 | RSS 4h 内 558 MB → 3.9 GB；策略从不读取 cache tick 历史（数据来自 NautilusBookDataProvider） | `TradingNodeConfig` 显式设置 `cache=CacheConfig(tick_capacity=100, bar_capacity=100)` | `a6ac3f2` |

## 保留的微优化（正确但非根因）

| # | 优化项 | 提交 |
|---|--------|------|
| 1 | instrument_id → condition_id O(1) 反向索引 | `652b1c9` |
| 2 | 策略跟踪列表 → deque(maxlen=1000) | `95e6a81` |
| 3 | update_trade 深拷贝 → 浅拷贝 | `95aeb5f` |
| 4 | trades 列表切片 → deque(maxlen=512) | `9de5473` |

## 遗留观察项（未修复，待部署后验证）

- 每 tick 全量策略评估仍是 CPU 大头（评估频率由设计决定，降频会改变信号时序，需产品决策，不在本次范围）。
- `PolymarketMarketRegistry` / `NautilusBookDataProvider` 的 per-token dict 随轮换缓慢增长（MB/天量级，远小于已修复项）。
- 修复 3 的效果需在重建镜像部署后用 `docker exec polysignal-lab grep VmRSS /proc/1/status` 连续采样验证；修复 1/2 可直接观察 `logs/*.jsonl` 增速。

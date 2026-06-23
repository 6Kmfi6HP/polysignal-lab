# PolySignal Lab × PolyBullLabs 策略交叉对比 & 修正计划

> 基准版本: refs/polymarket-arbitrage-bot (PolyBullLabs) — 以该项目的策略实现方式为正确参照。
> 日期: 2026-06-23

---

## 目录

1. [VWAP Momentum 差异分析](#1-vwap-momentum-差异分析)
2. [PTB Diff 差异分析](#2-ptb-diff-差异分析)
3. [Late Consensus 差异分析](#3-late-consensus-差异分析)
4. [修正计划优先级总表](#4-修正计划优先级总表)
5. [行动计划](#5-行动计划)

---

## 1. VWAP Momentum 差异分析

### 映射关系

| 维度 | PolyBullLabs (refs) | PolySignal Lab |
|------|---------------------|----------------|
| 策略文件 | `btc-binary-VWAP-Momentum-bot/main.py` | `src/polysignal_lab/strategies/vwap_momentum.py` |
| 计算器 | `IndicatorCalculator` (类方法) | `TradeHistory` (实例方法) |
| 决策流 | Dashboard → Signal generation → Entry execution | `evaluate()` → SignalCandidate |
| 配置 | `config.json` / environment | `VWAPMomentumConfig` (Pydantic) |

### 🔴 HIGH: 动量计算算法差异 (Momentum) [P0]

**Refs 正确实现:**
```python
# IndicatorCalculator.calc_momentum()
# 时间带算法: 取 ~window_sec 秒前的价格均值 ±1.5s 带
band_start = now - window - avg_band    # avg_band=1.5s
band_end   = now - window + avg_band
band_prices = [t.price for t in trades if band_start <= t.timestamp <= band_end]
avg_price_ago = mean(band_prices) if band_prices
return (current_price - avg_price_ago) / avg_price_ago * 100  # %
# 默认窗口: 120s, 阈值 > 5%
```

**我们的实现:**
```python
# TradeHistory.momentum()
# 简单首尾比较: 取窗口内第一条和最后一条交易
p0 = trades[0].price
p1 = trades[-1].price
return (p1 - p0) / p0  # 分数值
# 默认窗口: 60s, 阈值 > 0.01 (1%)
```

**差异:** 这是两种完全不同的算法。Refs 问的是"现在价格相比 ~120s 前（一个3秒时间带）的平均价格变化了多少"，而我们问的是"窗口期内第一个交易价格到最后一个交易价格的变化率"。前者是测量从特定过去时间点开始的动量变化（用均值平滑噪声），后者是窗口内的总趋势（可能被噪音主导）。

**影响:** 结合动量窗口差异(120s vs 60s)和阈值差异(5% vs 1%)，我们的策略会发出大量 refs 不会触发的假阳性信号。

**修正:**
1. 重写 `TradeHistory.momentum()` 为时间带算法（±1.5s 带，算术均值）
2. 改 `momentum_window_sec` 从 60 → 120
3. 改 `min_momentum` 从 0.01 → 0.05（修复算法后校准）

### 🔴 HIGH: 最大偏离度阈值实质上被禁用 [P0]

**Refs 正确实现:**
- `max_dev = 5` → 5% 偏离度上限
- 过滤掉偏离 VWAP 太远的价格（可能是极端动量反转信号）

**我们的实现:**
- `max_deviation_pct: 1.0` → 100%，在二元期权市场（价格范围 0.01-0.99）上不可能达到
- 这个上限检查从来不 reject 任何信号

**修正:** `max_deviation_pct: float = 0.05`（对应 refs 的 5%）

### 🟡 MEDIUM: VWAP 计算细节 — 交易数据来源及 Z-Score

1. 使用 `size=1.0` 而非真实成交量 → VWAP 接近等权均值。建议获取真实成交量。
2. Z-score 过滤器（`min_z_score: 1.2`）是额外添加的，refs 没有这个检查。可能导致本应通过的信号被拒。建议验证或移除。
3. 时间窗口边界检查: refs 用 `time_left > no_entry_cutoff`（严格大于），我们用 `seconds_to_close <= no_entry_before_end_sec`（小于等于）。当相等时行为不同。

### 🟢 LOW: 其他差异

- `_can_enter` 永久护板 vs refs 可重入机制（session-scoped，市场轮转时重设）
- 缺少 Win Rate Table（历史 CSV 胜率表）
- 缺少 Chainlink BTC 价格/对冲管理（我们的架构在下层处理）

---

## 2. PTB Diff 差异分析

### 映射关系

| 维度 | PolyBullLabs (refs) | PolySignal Lab |
|------|---------------------|----------------|
| 策略文件 | `5min-15min-PTB-bot/polymarket_auto_trade.py` | `src/polysignal_lab/strategies/ptb_diff.py` |
| 触发规则 | 4 条硬编码规则 (R1-R4) | 可配置 trigger list |
| 概率检查 | 用 token ask 当作概率值 | `directional_probability` 是二元值 |
| TP/SL | `_planned_take_profit_stop_loss()` | `compute_tp_sl_thresholds()` |
| 数据源 | Chainlink BTC + Binance BTC fallback | `snapshot.spot.price` (抽象化) |

### 🔴 HIGH: 概率检查逻辑完全不同 [P0]

**Refs 正确实现:**
```python
# 使用 token ask 价格直接作为市场隐含概率
prob = up_entry_price  # or down_entry_price
if C1_MIN_PROB <= prob <= C1_MAX_PROB:  # e.g. 0.80 <= 0.85 <= 0.92
    triggered = True
```
核心逻辑：市场的 token 价格就是概率，检查是否在 [min_prob, max_prob] 带内。**没有下限检查意味着我们会在 refs 拒绝的信号上进场。**

**我们的实现:**
```python
directional_probability = 1.0 if diff > 0 and side == UP else 0.0  # 永远 1.0
probability_edge = max(0.0, directional_probability - entry_price)
if probability_edge < min_probability_edge:  # e.g. 0.08
    return []
```

**差异:** 
- `directional_probability` 是二元值（1.0/0.0），不反映市场隐含概率
- `probability_edge = 1.0 - entry_price` 捕捉的是"折扣"而非"概率置信度"
- **没有下限等价**: refs 0.80 下限拒绝 token 价格 0.50 的信号，我们的 edge=1.0-0.50=0.50 > 0.08 → PASS

**修正:** 在 `PTBTriggerConfig` 中添加 `min_token_price: float = 0.80` 和 `max_token_price`（已有），改为范围检查。

### 🔴 HIGH: Diff 价格源使用 Binance 而非 Chainlink [P0]

**Refs:** `diff = chainlink_btc - ptb` — Polymarket BTC 市场用 **Chainlink BTC/USD 预言机**结算。Chainlink 是多个交易所的聚合价。

**我们的实现:** `diff = snapshot.spot.price - snapshot.price_to_beat` — 使用 **Binance BTC/USDT** 现货价格。

**影响:** Binance 和 Chainlink 之间通常有 $10-50 差价，剧烈波动时更大。这导致 diff 幅度和方向都可能错误。

**修正:** 将 Chainlink BTC/USD 价格集成到数据管道中，在 PTB 策略中优先使用。

### 🟡 MEDIUM: TP/SL 计算 — 公式一致但参数差异导致风控行为变形 [P1]

**公式完全一致 ✅**。但参数不同导致实质性行为差异：

| 参数 | Refs | Ours | 影响 |
|------|------|------|------|
| STOP_LOSS_PROB_PCT | 0.15 (15%) | 0.20 (20%) | 止损更宽 |
| TAKE_PROFIT_RR | 1.0 | 3.0 | RR=3 导致大多数仓位 TP 立即触达封顶值 |
| TAKE_PROFIT_CAP | 0.99 | 0.95 | 封顶更低 |

**示例:** entry=0.85
- Refs: SL=0.7225, TP=0.9775 ✓
- Ours: SL=0.68, TP=min(0.95, 0.85+0.17*3)=0.95。重平衡后 stop=0.8167。**4% 回撤即触发止损 vs refs 的 15%。**

**修正:** 对齐默认值: `stop_loss_prob_pct=0.15`, `take_profit_rr=1.0`, `take_profit_cap=0.99`

### 🟡 MEDIUM: 缺少退出架构 — 连续 TP/SL 监控 [P1]

**Refs:** 同一主循环连续监控仓位，实时检查 token 价格 vs 动态 TP/SL 水平。TP/SL 以 entry 价格为中心重算。

**我们的实现:** 退出委托给 Paper Trading 模型，使用固定绝对价格（`take_profit_price=0.90`, `stop_loss_price=0.35`），非入口相对价格。

**影响:** 没有持续的价格监控，TP/SL 无法在分辨率前触发。固定价格与动态计算的价格完全不同。

**修正:** 架构性需求 — 添加持续仓位监控组件，或在信号层嵌入动态 TP/SL 价格供执行层使用。

### 🟡 MEDIUM: 重试/追单/超时逻辑缺失 [P2]

Refs 包含完整的执行生命周期管理：重试(step=+1%)、滑点检查(5%)、超时取消(8s)。这些都是执行层职责。需确认 Paper Trading 是否实现。

### 🟢 LOW: 其他差异
- 陈旧数据默认值差异 (2s vs 1.2s)
- 触发规则默认值差异 (diff≥$80 vs diff≥$30)
- 入场价格 ask 选择方式更好 (ours 始终用 ask，更准确)
- Confidence score 是额外添加功能

---

## 3. Late Consensus 差异分析

### 映射关系

| 维度 | PolyBullLabs (refs) | PolySignal Lab |
|------|---------------------|----------------|
| 策略文件 | `up-down-spread-bot/src/strategy.py` | `src/polysignal_lab/strategies/late_consensus.py` |
| 类名 | `LateEntryStrategy` | `LateConsensusStrategy` |
| 8 步流程 | ✅ | ✅ (大部分) |
| 配置 | JSON / 固定值 | `LateConsensusConfig` (Pydantic) |

### 🔴 HIGH: Flip Guard 概念误译 (Flip Stop vs Side-Change Guard) [P0]

**Refs 的 flip-stop — 价格阈值退出:**
```python
# main.py (执行层回调):
if strategy and our_price <= strategy.flip_stop_price:  # 0.48
    exit_reason = 'flip_stop'  # 价格跌破 0.48 → 紧急退出
```

**我们的 flip_guard — 侧切换守卫:**
```python
# late_consensus.py:
def _flip_guard_blocks(self, ...):
    # 20 秒内不允许从 UP 切换到 DOWN（入口阻止，非退出）
```

**差异:** 概念翻译错误。refs 的 flip_stop 是**价格触发退出条件**，我们的 flip_guard 是**侧切换频率限制**。两者含义完全不同。我们的 flip_guard 本身是个有用功能，但它不替代 flip-stop。

**修正:**
1. 重命名 `_flip_guard_blocks()` → `_side_change_blocked()` 
2. 将 `flip_stop_price` (0.48) 作为退出条件嵌入信号 metrics
3. 执行层（Paper Wallet）在入场后持续监控价格是否跌破 flip_stop_price

### 🔴 HIGH: 纸面交易止损价使用了 0.35 而非 0.48 [P0]

策略配置 `flip_stop_price: 0.48` 但 Paper Trading exit model 使用 `stop_loss_price: 0.35`。0.13 的差距意味着每个亏损仓位多承担 ~13% 的下行风险。两者必须对齐。

### 🔴 HIGH: 5m 市场的时间窗口未缩放 [P1]

**Refs:** `entry_window` 在 5m 市场自动从 240s 减到 120s（通过默认值计算和智能覆盖检测）。

**我们的实现:** 固定 `entry_window_sec = 240`，5m 市场仍用 240s。结果：在 5m 市场上从开市后 60s 开始进入（而非 refs 的 180s）。

**修正:** 
```python
market_interval_sec = ...  # 从 market 或 config 推导
default_window = 240 if market_interval_sec >= 900 else min(120, market_interval_sec - 10)
if market_interval_sec < 900 and config_window > market_interval_sec * 0.5:
    effective_window = default_window
```

### 🔴 HIGH: 仓位大小阈值未缩放 [P1]

**Refs:** 5m 市场的 sizing tier 自动缩为 60s/40s（scale = market_interval/900）。
**我们的实现:** 固定 180s/120s 阈值，5m 市场始终处于 12 合约激进档位。

**修正:** 类似 refs，用 `market_interval_sec / 900.0` 缩放阈值。

### 🟡 MEDIUM: Spot Move 检查 — 非 refs 原生逻辑

额外检查：需要 Binance 现货价格变动 ≥ $1（BTC）且方向支持所选 side。refs 没有此检查。会拒绝 refs 会接受的信号。需要确认设计的故意性。

### 🟡 MEDIUM: `max_spread` 命名冲突

Refs 的 `max_spread = 1.05` 是 ask 价格之和；我们的 `max_spread = 0.08` 是买卖价差（百分比）。同名不同义。

### 🟢 LOW: 其他差异
- `max_entry_price` 默认值 0.92 vs refs 0.93
- `max_investment_per_market` 通过 metrics 委托给下层（架构合理）
- Hedge 信号未包含在输出中
- 缺少两端时间戳同步检查

---

## 4. 修正计划优先级总表

| # | 优先级 | 策略 | 问题 | 影响 | 工作量 |
|---|--------|------|------|------|--------|
| P0 | 🔴 HIGH | VWAP | 动量算法完全不同（时间带 vs 首尾差）+ 窗口/阈值全错 | 信号准确性严重偏差 | ~40 行代码 + config |
| P0 | 🔴 HIGH | VWAP | 最大偏离度阈值 = 100%（实质上禁用）vs refs 5% | 不过滤极端偏离 | config |
| P0 | 🔴 HIGH | PTB | 概率检查逻辑错误（二元方向概率 vs 概率范围 0.80-0.92） | 缺失下限检查，伪信号 | ~50 行 + config schema |
| P0 | 🔴 HIGH | PTB | Diff 价格源用 Binance 而非 Chainlink | diff 幅度/方向可能错误 | 数据管道集成 |
| P0 | 🔴 HIGH | Late | Flip guard 概念误译（价格止损 vs 侧切换守卫） | 退出逻辑失效 | ~30 行 |
| P0 | 🔴 HIGH | Late | paper trading 止损价 0.35 而非 0.48 | 多承担 13% 下行风险 | config |
| P1 | 🟡 HIGH | PTB | TP/SL 参数偏离导致风控行为变形 (RR=3 vs 1, SL=20% vs 15%) | 过早止损 | config |
| P1 | 🟡 HIGH | Late | 5m 市场时间窗口未缩放 (240s 而非 120s) | 过早进入 | ~20 行 |
| P1 | 🟡 HIGH | Late | 仓位大小阈值未缩放 (180/120 固化而非 60/40) | 5m 激进仓位 | ~15 行 |
| P1 | 🟡 HIGH | PTB | 缺少连续 TP/SL 监控架构 | 无法执行概率空间止盈止损 | 架构性 |
| P2 | 🟡 MEDIUM | PTB | 重试/追单/超时逻辑缺失 | 订单执行韧性不足 | 执行层 |
| P2 | 🟡 MEDIUM | Late | Spot move 是非原生额外检查 | 可能拒绝有效信号 | 文档/配置化 |
| P2 | 🟡 MEDIUM | Late | `max_spread` 命名冲突（1.05 ask_sum vs 0.08 bid-ask spread） | 沟通歧义 | 重命名 |
| P2 | 🟡 MEDIUM | VWAP | Z-score 过滤器是额外添加 | 可能阻塞有效信号 | 验证/移除 |
| P3 | 🟢 LOW | VWAP | `_can_enter` 永久护板 vs refs session 级可重入 | 同一 market 不可重入 | 文档化 |
| P3 | 🟢 LOW | All | 陈数据检查默认值 2s vs refs 1.2s | 容忍度不同 | config |
| P3 | 🟢 LOW | Late | `max_entry_price` 默认值 0.92 vs 0.93 | 微差 | config |
| P3 | 🟢 LOW | VWAP | 缺少 Win Rate Table | 信号维度缺失 | ~50 行 |
| P3 | 🟢 LOW | PTB | 触发规则默认 diff≥$80 vs refs $30 | 敏感度不同 | config |

---

## 5. 行动计划

### Phase 1: 关键修复 (P0 — 信号逻辑 Bug)

**1. VWAP: 重写 momentum 算法 + 阈值修正**
- 改 `TradeHistory.momentum()` 为时间带算法（±1.5s 带，算术均值）
- `momentum_window_sec`: 60 → 120
- `min_momentum`: 0.01 → 0.05
- `max_deviation_pct`: 1.0 → 0.05
- `min_deviation_pct`: 确认 0.015 (1.5%) 是否匹配 refs 预期

**2. PTB: 修正概率检查逻辑 + 添加 Chainlink 数据源**
- `PTBTriggerConfig` 增加 `min_token_price: float = 0.80` 字段
- 改为 `min_token_price <= entry_price <= max_token_price` 范围检查
- 集成 Chainlink BTC/USD 价格到数据管道（`polymarket_clob_rest.py` 或新增 source）
- 在策略中优先使用 `chainlink_btc` 计算 diff

**3. Late Consensus: 修正 flip_guard 概念 + 止损价对齐**
- 重命名 `_flip_guard_blocks()` → `_side_change_blocked()`
- 将 `flip_stop_price: 0.48` 嵌入信号 metrics 供退出层使用
- 修改 `paper_trading.exit_model.stop_loss_price: 0.48`

### Phase 2: 架构修复 (P1 — 参数/风控)

**4. PTB: TP/SL 参数对齐 refs**
- `PTBExitConfig`: `stop_loss_prob_pct=0.15`, `take_profit_rr=1.0`, `take_profit_cap=0.99`

**5. Late: 5m 市场自适应缩放**
- 时间窗口: 添加 `market_interval_sec` 感知缩放
- 仓位大小: 缩放 `sizing_t1/sizing_t2` 阈值

**6. PTB: 连续 TP/SL 监控架构**
- 添加仓位价格监控组件，持续检查 token 价格 vs 动态 TP/SL
- TP/SL 水平在入场时根据 entry_price 计算

### Phase 3: 增强 (P2-P3 — 功能)

**7. VWAP: Z-score 过滤器验证/移除**
**8. Late: `max_spread` 重命名 (`max_book_spread`)**
**9. Late: Spot move 检查文档化 / 配置化**
**10. All: 陈旧数据参数对齐（2s→1.2s 或明确意图）**
**11. PTB: 执行层重试/追单/超时逻辑**
**12. VWAP: Win Rate Table 集成**

### 详细代码修改指南

见各子报告:
- `docs/superpowers/comparison-vwap-momentum.md`
- `.claude/worktrees/agent-a3a52d61a63b3bb36/docs/superpowers/comparison-ptb-diff.md`
- `.claude/worktrees/agent-a5842fcf042bb01ea/docs/superpowers/comparison-late-entry.md`

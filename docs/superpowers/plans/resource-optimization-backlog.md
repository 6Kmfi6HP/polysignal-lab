# Resource Optimization Backlog

> 首轮系统化资源优化。每个周期 = 发现 → RED(测试基准) → GREEN(实现) → 验证 → commit

| # | 优化项 | 发现方式 | 当前基准 | 预期收益 | 涉及模块 | 状态 | 提交 |
|---|--------|----------|----------|----------|----------|------|------|
| 1 | 添加 instrument_id → condition_id 反向索引，消除 O(N) 线性扫描 | 源码分析：`_condition_id_for_instrument` / `_token_id_for_instrument` 在每次回调中遍历所有 condition_id | ~10 次 O(N) 扫描/事件 × 每秒 ~1000 事件 | O(N) → O(1)，200 条件下约 200x 提速 | market_registry.py, native_strategy.py | 已合入 | `652b1c9` |

## Hotspot 1 详情

### 性能问题

- `_condition_id_for_instrument()`（`native_strategy.py:1382`）遍历 `registry._by_condition` 所有 key，每次调用 O(N)
- `_token_id_for_instrument()`（`native_strategy.py:1398`）同样 O(N)
- 每次回调调用 2 次：
  - 4 个市场数据回调（quote_tick, order_book_deltas, order_book, trade_tick）→ 8 次 O(N) 调用/事件
  - `_order_event()` 追加 2 次
  - 总计 ~10 次 O(N) 调用/事件

### 修复方案

1. `PolymarketMarketRegistry` 添加 `_by_instrument: dict[str, str]`（instrument_id → condition_id）
2. `register()` 中填充
3. 新增 `by_instrument()` 和 `token_id_for_instrument()` 方法
4. 替换 `_condition_id_for_instrument` 和 `_token_id_for_instrument` 为 O(1) 查找

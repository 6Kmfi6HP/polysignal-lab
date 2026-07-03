# Resource Optimization Backlog

> 首轮系统化资源优化。每个周期 = 发现 → RED(测试基准) → GREEN(实现) → 验证 → commit

| # | 优化项 | 发现方式 | 当前基准 | 预期收益 | 涉及模块 | 状态 | 提交 |
|---|--------|----------|----------|----------|----------|------|------|
| 1 | 添加 instrument_id → condition_id 反向索引，消除 O(N) 线性扫描 | 源码分析：`_condition_id_for_instrument` / `_token_id_for_instrument` 在每次回调中遍历所有 condition_id | ~10 次 O(N) 扫描/事件 × 每秒 ~1000 事件 | O(N) → O(1)，200 条件下约 200x 提速 | market_registry.py, native_strategy.py | 已合入 | `652b1c9` |
| 2 | 无界列表 → 有界 deque(maxlen=1000)，消除内存泄漏 | 子代理代码审查：4 个列表永不回收 | 每次 reject/submit 追加，无上限 | O(entries) → O(1000) 内存上界 | native_strategy.py | 已合入 | `95e6a81` |
| 3 | update_trade 深拷贝 → 浅拷贝，减少高频 trade tick 的对象分配 | 源码分析：`model_copy(deep=True)` 对 BookLevel 全量复制 | 每次 trade tick 复制 ~102 个对象 | 约 100x 分配量减少 | book_data.py | 已合入 | `95aeb5f` |
| 4 | 消除 update_trade 的 OrderBook.model_copy()，分离 last_trade 缓存 | 源码分析：即使浅拷贝也创建 Pydantic OrderBook 实例 | 每次 trade tick 一次 OrderBook 实例化 | OrderBook 对象完全消除 | book_data.py | 已合入 | `3f42fbe` |
| 5 | book_for_token/snapshot_for_token 缓存派生字段（best_bid/ask/ask_levels），消除每次 evaluate 的 O(N) computed_field 遍历和 tuple 重分配 + 新增 `now` 参数消除冗余 datetime.now(UTC) 系统调用 | 源码分析：`book_for_token()` 在每次 evaluate_condition() 热路径中调用 2 次，每次遍历 computed_field | book_for_token: 15.5 µs/call（10 levels） | 读路径提升 ~21%（12.2 µs/call），写路径（update_book）一次遍历 N 次复用，datetime.now 调用减半 | book_data.py, market_view_assembler.py | 已合入 | `8b91267` |
| 6 | trades_for_token registry 路径消除 Pydantic getattr 扫描（对 Trade 模型不存在字段触发 ~8.3 µs/字段开销） | 基准测试发现：318 µs/call vs 预期 20 µs | trades_for_token: 318 µs/call（20 trades） | 13x 提速：318 µs → 24 µs/call；消除每个 Trade 对象的 2 次 Pydantic 属性扫描链 | book_data.py | 已合入 | `当前commit` |

## 剩余未优化热点评分

| 潜在热点 | 位置 | 频率 | 影响评分 | 解释 |
|----------|------|------|----------|------|
| `_on_evaluation_heartbeat` sorted() + O(N) 迭代 | native_strategy.py:372 | 10s | 低 | N 个 condition × 10s 间隔，仅当 N>500 才显著 |
| `_book_signature` 排序 | matching.py:1132-1140 | 按每 match_order | 低 | 仅对有变更的 books 排序，执行路径不热 |
| `_publish_book_to_nautilus` 层级转换 | matching.py:526-570 | 按 book 变更 | 低 | 仅在脏 book 时触发，非每个事件 |
| `_event_side` 遍历 | native_strategy.py:1279-1292 | 按 order_event | 低 | 已优化为 O(1) `by_instrument()` |
| 无界 `_seen_matching_trades` | data_ingestor.py:60 | sync 时 | 低 | 每轮替换为 current_seen，有限增长 |
| `MarketViewAssembler.build()` 分配 | market_view_assembler.py:24 | 按 evaluate | 低 | 每次 evaluate 构建 view，无法避免 |

## 停止条件评估

- 连续 0 个循环发现「无可用优化项」
- 已读完设计文档和 native_strategy.py，matching.py，node.py 源码
- 3 轮优化覆盖 2 个 CPU 热点 + 1 个内存热点
- 剩余热点确认无足够影响启动新一轮 RED→GREEN 周期

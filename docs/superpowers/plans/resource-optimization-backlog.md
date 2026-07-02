# Resource Optimization Backlog

> 首轮系统化资源优化。每个周期 = 发现 → RED(测试基准) → GREEN(实现) → 验证 → commit

| # | 优化项 | 发现方式 | 当前基准 | 预期收益 | 涉及模块 | 状态 | 提交 |
|---|--------|----------|----------|----------|----------|------|------|
| 1 | 添加 instrument_id → condition_id 反向索引，消除 O(N) 线性扫描 | 源码分析：`_condition_id_for_instrument` / `_token_id_for_instrument` 在每次回调中遍历所有 condition_id | ~10 次 O(N) 扫描/事件 × 每秒 ~1000 事件 | O(N) → O(1)，200 条件下约 200x 提速 | market_registry.py, native_strategy.py | 已合入 | `652b1c9` |
| 2 | 无界列表 → 有界 deque(maxlen=1000)，消除内存泄漏 | 子代理代码审查：4 个列表永不回收 | 每次 reject/submit 追加，无上限 | O(entries) → O(1000) 内存上界 | native_strategy.py | 已合入 | `95e6a81` |

# Issue69 TUNGSTENITE 修复后信号停摆：修复计划

- **制定日期**：2026-08-18
- **依据**：`/tmp/handoff.J5lRft/handoff-issue69-fix-execution.md`
- **范围**：仅制定执行计划；本次不执行测试、不修改代码、不构建镜像、不部署

## 背景

TUNGSTENITE 修复已经根治 `code=1008 "no ping received"` 死亡螺旋，但运行约 12 分钟后出现信号停摆且不恢复，`GATE_ACCEPT` 长时间为 0，watchdog 也未能触发重启。

根因调查确认五层缺陷叠加，执行顺序必须为：

1. **P0**：watchdog latch 锁死
2. **P1**：市场轮换失败
3. **P1**：已解析市场 re-subscribe 导致新的 `code=1008` 死循环
4. **P2**：按需评估簿记撕裂与 DataEngine 去重空转

## 验收目标

最终必须恢复以下运行时不变量：

- 断路器窗口打开时抑制重启，但不永久锁死同一进程内的 watchdog。
- 断路器窗口冷却后，同一 watchdog 实例能够再次触发重启。
- 已 closed/resolved 的市场从 active condition set 移除。
- 新交易窗口能够被 Gamma discovery 找到、注册、加入 active set 并完成订阅。
- book recovery 不会对已 closed/resolved 市场重新订阅。
- 不再出现已解析市场触发的 `code=1008 invalid subscription payload` 死循环。
- `GATE_ACCEPT` 在市场轮换后持续恢复，而不是只在进程重启后短暂恢复。

---

# Step 1：P0 修复 watchdog latch 锁死

## 1.1 TDD：先写失败测试

目标文件：

- `tests/test_restart_circuit_breaker.py`

新增一个“同一进程、同一 watchdog 实例”的回归测试：

1. 配置 `max_restarts_in_window=3`、`restart_circuit_breaker_window_sec=1800`。
2. 预置两次窗口内的 restart timestamp。
3. 写入持续 `data_starvation` heartbeat。
4. 第一次 `poll_once()` 追加第三次记录，使断路器打开。
5. 断言没有调用 restart callback。
6. 将测试时钟推进超过 1800 秒，例如 1801 秒。
7. 再次调用同一个 watchdog 实例的 `poll_once()`。
8. 断言 restart callback 被调用一次，reason 为 `data_starvation`。

该测试必须覆盖“breaker open 后 latch 不应永久锁死”的路径，不能只测试进程启动时已有历史记录过期。

保留并继续验证现有测试：

- `test_circuit_breaker_opens_after_max_restarts_in_window`
- `test_circuit_breaker_resets_after_window_expires`
- `tests/test_liveness_watchdog.py` 中的 restart 与 fleet readiness 用例

## 1.2 最小实现变更

目标文件：

- `src/polysignal_lab/observability/liveness_watchdog.py`

实施内容：

1. 删除断路器打开分支中的：

   ```python
   self._restart_requested = True
   ```

2. 保留正常 restart 分支中的 latch 设置。
3. 在相关注释中明确说明：
   - latch 仅表示存在一个在途重启请求；
   - 断路器抑制由 `_circuit_breaker_open` 自身负责；
   - 滚动窗口冷却后，旧记录会被清理，watchdog 自动重新武装。
4. 不引入额外 timer、线程同步机制或新状态枚举。

## 1.3 Step 1 验证

```bash
python -m pytest tests/test_restart_circuit_breaker.py tests/test_liveness_watchdog.py -x
uv run basedpyright src/polysignal_lab/observability/liveness_watchdog.py
```

要求：相关测试全部通过，basedpyright 为 `0 errors`。

### baseline 注意事项

`.basedpyright/baseline.json` 运行 basedpyright 后可能自动改写。执行时：

1. 运行前保存 baseline 状态；
2. 运行 basedpyright；
3. 审查 baseline diff；
4. 若路径改名导致 key 变化，按新旧路径重映射 key；
5. 不使用 `git checkout` 粗暴恢复 baseline。

## 1.4 Step 1 完成门槛

- 同一 watchdog 实例能够经历 breaker open → 冷却 → 再次 restart。
- restart circuit breaker 与 liveness watchdog 测试通过。
- basedpyright 0 errors。
- 未修改 `@refs`、上游 NautilusTrader 或无关文件。

---

# Step 2：P1 修复市场轮换失败

Step 2 必须同时解决：

1. 已关闭市场没有从 active set 清退；
2. 新市场 discovery 长时间返回 `new=0`。

## 2.1 调查 registry 的 end_ts 更新链路

重点文件：

- `src/polysignal_lab/nautilus_runtime/strategy/condition_evaluation.py`
- `src/polysignal_lab/nautilus_runtime/strategy/lifecycle.py`
- `src/polysignal_lab/nautilus_runtime/market_catalog.py`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/data/market_discovery_helpers.py`

需要确认：

1. adapter 发出 `Market closed` 后是否产生新的 market metadata/universe 数据；
2. metadata 是否含正确的 `end_ts`；
3. metadata 是否真正调用 `registry.register()`；
4. 已存在 condition 是否会被新 metadata 覆盖；
5. Gamma discovery 是否能提供正确的 `end_ts`；
6. 时间字段是否存在时区、秒/毫秒或 listing/event window 混用问题。

重点检查 `_discover_new_conditions()` 当前只在 registry 中不存在时注册市场的行为。若 Gamma 返回了更新后的已知 condition，而 registry 仍保存旧 metadata，则 `retire_expired_condition()` 无法正确判断过期。

优先复用现有 `MarketPairMeta` / `MarketCatalog.register()` 更新机制，不在没有证据时增加平行 closed-state cache。

## 2.2 调查 active set 生命周期

重点路径：

- `lifecycle._active_unexpired_condition_ids()`
- `condition_evaluation.retire_expired_condition()`
- `custom_data_handlers.handle_market_universe()`
- `_discover_and_subscribe_new_markets()`

需要确认：

- `intersection_update()` 是否被旧 universe feed 绕过或误删有效 condition；
- `retire_expired_condition()` 是否真正对 active set 执行；
- 清退后是否清理 subscription/book generation/recovery/readiness 状态；
- `unsubscribe_exited=True` 时是否取消所有相关 instrument；
- heartbeat 是否按“先清退旧市场，再 discovery 新市场，最后订阅”的顺序执行。

## 2.3 调查 slot slug 与 Gamma slug

重点文件：

- `src/polysignal_lab/data/market_discovery_helpers.py`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `tests/test_market_discovery_and_feeds.py`
- `tests/test_issue69_market_discovery.py`

对比以下链路：

```text
build_current_slot_slugs()
    → _current_slot_slugs()
    → Gamma /events/slug/{slug} 或 /markets?slug={slug}
    → parse_gamma_markets()
    → match_crypto_updown()
    → is_allowed_active_market()
    → is_allowed_window()
```

必须验证：

- asset/timeframe 大小写与格式；
- UTC epoch slot base；
- current slot 与 next slot 覆盖范围；
- event slug 与 market slug 的实际差异；
- `endDate`、`eventEndTime` 等字段最终如何写入 `Market.end_ts`；
- `active_only`、`closed`、`is_allowed_window()` 是否错误过滤新市场；
- Gamma 请求是否携带 User-Agent，避免 403 被误判为空结果。

运行环境约束：容器使用 warp sidecar；Rust HTTP client 不走 HTTP proxy；Gamma API 请求必须带 User-Agent。

## 2.4 Step 2 测试

至少覆盖：

### 过期市场清退

- `end_ts < now` 的 condition 从 active set 移除；
- lifecycle state、recovery、readiness 状态被清理；
- `unsubscribe_exited=True` 时 instrument 被取消订阅；
- asset-condition projection 被刷新。

### registry metadata 更新

- 同一 condition 先注册旧 pair，再注册带新 `end_ts` 的 pair；
- registry 返回新 pair；
- retire 逻辑能够清退已过期 condition。

### 新市场注册与订阅

覆盖完整轮换场景：

1. 旧窗口在 active set；
2. 旧窗口过期并被移除；
3. discovery 返回新窗口；
4. 新 condition 被 registry 注册；
5. 新 condition 加入 active set；
6. 新 condition 被提交订阅。

### slug 与过滤

覆盖 current slot、next slot、stale grace、event/market slug、closed/resolved 过滤和 active market 保留。

## 2.5 Step 2 验证

```bash
python -m pytest tests/test_restart_circuit_breaker.py tests/test_liveness_watchdog.py -x
uv run basedpyright src/polysignal_lab/observability/liveness_watchdog.py
python -m pytest \
  tests/test_issue69_market_discovery.py \
  tests/test_market_discovery_and_feeds.py \
  tests/test_market_parsing.py \
  tests/test_nautilus_market_rotation.py \
  -x
```

Step 2 完成前必须证明：已关闭/已解析 condition 可清退，新 condition 可被发现、注册、加入 active set 并完成订阅。

---

# Step 3：P1 阻止已解析市场 re-subscribe

## 3.1 目标

在 book recovery 的 drain → delayed restore 路径中，已 resolved/closed 的 market 不得重新订阅。

重点文件：

- `src/polysignal_lab/nautilus_runtime/strategy/subscriptions.py`
  - `_refresh_market_instrument()`
  - `_flush_pending_book_restores()`
  - `_condition_ids_for_instrument()`
  - `unsubscribe_market_instrument()`
- `tests/test_issue69_two_phase_refresh.py`
- `tests/test_issue69_reconnect_cycles.py`
- `tests/test_nautilus_book_stall_resubscription.py`

## 3.2 实现边界

pending restore 以 instrument 为 key，closed/resolved 状态以 condition 为语义。执行时应沿用现有 registry mapping：

```text
pending instrument
    → registry token/instrument lookup
    → condition_id
    → registry.by_condition(condition_id)
    → end_ts / closed / resolved 判断
```

判断优先级：

1. `pair.end_ts is not None and now >= pair.end_ts` 时视为不可恢复；
2. 若 registry/metadata 已提供显式 closed/resolved 状态，一并判断；
3. 不通过 instrument 字符串猜测市场状态；
4. 不因查询异常静默把未知 condition 当作可恢复。

## 3.3 预期行为

在 `_flush_pending_book_restores()` 中，对 pending instrument：

- 已 closed/resolved：删除 pending entry，不调用 restore，不标记 global refresh，不产生 subscribe wire command；
- 仍有效：保持现有延迟、restore、retry/throttle 行为。

不要在本 Step 同时调整 `_BOOK_RECOVERY_RESTORE_DELAY_SEC`。DataEngine 去重延迟属于 Step 4 独立问题。

## 3.4 Step 3 测试

至少覆盖：

### 已解析市场不恢复

- 构造 `end_ts < now` 的 pair；
- 放入 pending restore；
- flush 后没有订阅调用；
- pending entry 被删除；
- 没有 global refresh timestamp。

### 有效市场仍恢复

- `end_ts > now` 的 pair 在延迟到期后仍能正常 subscribe；
- 现有两阶段 refresh 测试继续通过。

### 混合场景

同一 flush 中同时存在已解析和仍有效市场，断言前者跳过、后者正常恢复。

### retire 与 pending restore 竞态

先 drain，再 retire condition，最后 flush；已退出 market 不得被重新订阅。

## 3.5 Step 3 验证

```bash
python -m pytest tests/test_restart_circuit_breaker.py tests/test_liveness_watchdog.py -x
uv run basedpyright src/polysignal_lab/observability/liveness_watchdog.py
python -m pytest \
  tests/test_issue69_two_phase_refresh.py \
  tests/test_issue69_reconnect_cycles.py \
  tests/test_nautilus_book_stall_resubscription.py \
  -x
```

验收重点是：已解析 condition 不会生成 subscribe 调用，有效 condition 的恢复行为不受影响。

---

# Step 4：P2 缺陷按需重新评估

Step 4 不得提前于 Step 1–3 执行。watchdog 修复、市场轮换修复和已解析市场过滤可能已经绕过部分问题。

## 4.1 缺陷 2：condition 簿记撕裂

重新观察：

- `condition_phases`
- `awaiting_book_sides_by_condition`
- `book_generation_started_at_by_condition`
- `book_stalled_started_at_by_condition`
- `adapter_replay_started_at_by_condition`
- `first_bilateral_book_at_by_condition`

只有仍然出现以下不变量破坏时才修复：

```text
phase = AWAITING_FIRST_BOOK
但 generation / awaiting / total-stall 簿记为空
```

候选方向：

- 让 retire 清理 phase 与 generation 状态保持一致；或
- 在 condition 仍有效且需要重试时重新建立 generation；
- 先定义状态不变量，再补 regression/invariant test；
- 不为已关闭市场重新建立 generation。

## 4.2 缺陷 5：DataEngine 去重导致 recovery 空转

重新检查：

- book recovery 调度次数；
- 实际 unsubscribe wire command 数；
- 实际 subscribe wire command 数；
- drain 到 restore 的耗时；
- managed-book topic 是否仍有 subscriber；
- `0 wire command` recovery 占比。

只有 Step 1–3 后仍大量出现“recovery dispatched 但 wire command 为 0”时才修复。

候选顺序：

1. 先评估 `_BOOK_RECOVERY_RESTORE_DELAY_SEC` 的增加；
2. 用确定性测试验证 3–5 秒是否足够；
3. 若仍无效，再评估 unsubscribe → wait → subscribe 状态机；
4. 不修改上游 NautilusTrader；
5. 不以无限增大延迟作为最终方案。

---

# Step 5：Step 1–3 完成后的镜像与部署验证

本步骤不在计划制定阶段执行。

## 5.1 镜像

遵循 `docs/versioning.md`：

- 不使用 `latest`；
- 使用完整 commit SHA 或不可变 digest；
- 通过 `POLYSIGNAL_IMAGE_REF` 明确指定镜像；
- 两个后端服务使用同一完整镜像引用；
- 记录 Git commit、镜像 tag/digest、`/app/build-info.json` 和 Nautilus wheel 版本/SHA。

## 5.2 部署前状态

记录：

```bash
docker exec polysignal-lab cat /app/state/runtime_heartbeat.json
docker exec polysignal-lab cat /app/state/runtime_restart_history.json
```

同时记录：

- `last_data_at`；
- restart history；
- active/readiness condition 数量；
- `GATE_ACCEPT` 频率；
- 最近的 `code=1008` 日志；
- 容器健康状态。

## 5.3 连续观察 1 小时

### Watchdog

- breaker open 时抑制重启；
- 窗口过期后再次触发 restart request；
- `_restart_requested` 不永久锁死；
- restart history 正确按滚动窗口清理。

### 市场轮换

- `market_discovery_run` 持续执行；
- `new=0` 不再持续 1 小时以上；
- closed/resolved condition 从 active set 消失；
- 新 slot 被注册、加入 active set 并订阅。

### WebSocket/订阅

- 不再持续出现 `code=1008 invalid subscription payload`；
- 已解析市场不进入 re-subscribe；
- WS close/reconnect 不形成无退避死循环；
- 有效市场重连后仍能恢复 book。

### 信号

- `GATE_ACCEPT` 保持正常频率；
- 不再连续 30 分钟为 0；
- `last_data_at` 持续推进；
- readiness 不长期停留在全 fleet bookless；
- OoO/recovery 队列不无限增长。

---

# 约束与风险控制

- 不修改上游 NautilusTrader 代码。
- 不修改 `@refs` 目录。
- Gamma API 请求必须带 User-Agent。
- 容器通过 warp sidecar 出口；Rust HTTP client 不走 HTTP proxy。
- `.basedpyright/baseline.json` 改写后必须审查并重映射 key，不用 `git checkout` 恢复。
- Step 1–3 每个修复后都必须运行指定 watchdog 测试和 basedpyright。
- 不在 Step 1–3 中提前处理 P2 的 DataEngine 延迟问题。
- 不把“测试通过”当作运行时 1 小时验收的替代品。

## 严格执行顺序

```text
Step 1：TDD + watchdog latch 最小修复 + 测试/类型检查
  ↓
Step 2：市场清退、registry end_ts、active set、Gamma slug/discovery
  ↓
Step 3：book recovery 跳过已解析/已关闭市场
  ↓
Step 4：重新评估簿记撕裂和 DataEngine 去重空转
  ↓
Step 5：构建不可变镜像、部署并连续监控 1 小时
```

# Handoff — issue69 TUNGSTENITE 信号停摆修复（第 5 轮交接）

交接时间：2026-08-18 19:49 UTC（本地 02:49 +7）
交接人：前序监控 agent（已停止定时任务）
接收方：新监控/修复 agents

## 当前部署

| 项 | 值 |
| --- | --- |
| 容器 | `polysignal-lab`（compose），healthy，RestartCount=0 |
| 镜像 | `polysignal-lab:debug-issue69-fix`（本地 tag，37b813d7→最新 v2） |
| StartedAt | 2026-08-18T19:43:42Z |
| 命令 | `.env` 中 `POLYSIGNAL_IMAGE_REF=polysignal-lab:debug-issue69-fix` |
| 依赖 | WARP sidecar（polysignal-lab-warp，healthy） |

## 已完成修复（全部在分支 `fix/issue-69-workflow`，未提交）

1. **Step1 P0 watchdog latch 锁死**（`liveness_watchdog.py`）：删断路器分支 `_restart_requested=True`；测试 `test_breaker_recovers_after_window_cooldown_same_instance`
2. **Step2 P1 市场轮换**（`lifecycle.py:_discover_new_conditions` + `polymarket_market_discovery.py`）：已知 condition 始终 (re-)register（end_ts 更新）；Gamma 请求加 User-Agent
3. **Step3 P1 已解析市场 re-subscribe**（`subscriptions.py:_flush_pending_book_restores`）：跳过过期 condition 的 restore
4. **第4层 wire 订阅修复**（`subscriptions.py:subscribe_market_instrument`）：instrument 不在 Cache 时仍发订阅请求（保留 pending）— **部分有效**（让请求到达引擎，但 adapter 静默接受不加载）
5. **第5层 request_instruments 根治**（`lifecycle.py:_request_instrument_refresh`）：discovery 发现新 conditions 时调用 `strategy.request_instruments(venue, client_id)` — 19:00 边界验证成功（1100 订单/4min，新窗口无缝）
6. **第6层 stall 自愈**（`lifecycle.py:_data_stall_refresh_due` v2）：heartbeat 检测 awaiting_first_book **或** stale_book_recovery 状态 → 300s 节流 request_instruments

测试：`tests/test_issue69_market_discovery.py`（+7 新测试）、`tests/test_nautilus_strategy_base.py`（2 修改）等全量 127+ 通过；basedpyright 0 errors。

## 三层运行时根因（按发现顺序）

- **A. 轮换订阅死锁**：启动 load_ids 只预填当前+下一窗口；新窗口 instrument 永不加载 → 订阅 pending 死锁 → 数据饥饿重启。修复=request_instruments（5）。
- **B. WS 数据流周期性静默死亡**：每次 WS 连接存活 3-7 分钟后 Polymarket 静默停止推送（无 close frame）；dead-detection 需要 16+ 分钟才触发；重连后 "Restoring market subscription state" 恢复的仍是旧订阅列表 → 数据不恢复。
- **C. watchdog 断路器误伤**：断路器（21 次/1800s）会抑制重启（包括 compose 手动 restart 的计数？见下）。

## 待验证（新 agent 任务）

1. **stall 自愈 v2 闭环**：下次数据断流（预期连接建立后 3-7 分钟）→ `_data_stall_refresh_due` 应触发 request_instruments → adapter 重新加载 → ≤5 分钟恢复，**无需手动重启**。日志佐证：`market_discovery_run new=16` / `Subscribed` / 订单恢复。
2. **未提交代码风险**：所有修复在工作区未 commit（user 未授权提交）。新 agent 若重建镜像，确保工作区保持修复状态；`build-info.json` 已更新为 `1.0.0-debug.126+1258ec35fdca`（勿 git checkout 还原）。
3. **watchtower 干扰**：宿主 watchtower 检测 tag 变化会 recreate 容器（19:35 与 18:57 的"神秘重启"即此因；recreate 同时重置 RestartCount 与 load_ids 预填 — 需要区分"自愈"与"watchtower 隐式恢复"）。warp 容器有 disable label，polysignal-lab 没有 — 若需隔离验证可加 label。
4. **断路器计数**：`restart_circuit_breaker_open recent_count=21` — 需确认 compose/手动重启是否计入 watchdog 重启计数（影响自愈 vs 重启的比例）。
5. **监控时长**：用户要求 1 小时已超额完成（18:25-19:49）；但自愈闭环未最终确认 — 建议再观察 1-2 个断流周期（~30 分钟）后给出"解决/未解决"结论。

## 监控命令

```bash
# 容器与重启
docker ps --format '{{.Names}}\t{{.Status}}' --filter name=polysignal-lab$; docker inspect polysignal-lab --format '{{.RestartCount}}'
# 核心错误指标（注意 "1008" 会误匹配 ts_event 时间戳 — 用 code=1008 完整匹配）
docker logs polysignal-lab --since 6m 2>&1 | grep -cE "code=1008|code=1013|data_starvation"
# 交易与窗口
docker logs polysignal-lab --since 6m 2>&1 | grep -c "Submit.*LimitOrder"
docker logs polysignal-lab --since 6m 2>&1 | grep "Submit" | grep -oP 'market_slug=\K[a-z0-9-]+' | sort -u
# gate 健康
docker logs polysignal-lab --since 6m 2>&1 | grep -c "GATE_ACCEPT"; docker logs polysignal-lab --since 6m 2>&1 | grep -c "GATE_REJECT.*STALE"
# WS 事件
docker logs polysignal-lab --since 8m 2>&1 | grep -iE "dead connection|Reconnect succeeded|Restoring" | grep -v InvalidState
```

## 关键知识

- 时间戳：docker 日志 UTC（`2026-08-18T19:xx`），Python 日志本地 +7（`2026-08-19 02:xx`）
- 15m/5m 窗口边界：`:00/:15/:30/:45` UTC → 断流通常发生在连接建立后 3-7 分钟
- 之前的手动重启（18:46、19:09）是唯一可靠的即时恢复手段（重启后 load_ids 预填 → 32 订阅 → 恢复）
- memory 文件：`~/.claude/projects/-home-debian-polysignal-lab/memory/issue69-tungstenite-signal-stall-2026-08-18.md`（完整历史）
## 第 6 轮状态 / Next iteration — 2026-08-18

状态：**设计完成，尚未执行生产变更**。

### 下一轮唯一范围：I1 watchdog breaker history/latch re-arm

源码已确认 `_restart_requested` 不再在 `restart_circuit_breaker_open` 分支设置；但当前实现仍在
每次满足故障条件的 watchdog poll 中先追加 `runtime_restart_history.json` 再检查断路器。若断路器
打开后每 30 秒继续追加，1800 秒滚动窗口可能永远不冷却；该在线影响待运行验证。因此下一轮只
处理/验证此问题：保留 append-before-check 的首次计数，禁止 breaker-open episode 每次 poll 重复
追加，并证明同一 watchdog 实例 cooldown 后可以再次 restart。

允许修改范围仅为：

- `src/polysignal_lab/observability/liveness_watchdog.py`
- `tests/test_restart_circuit_breaker.py`

不处理市场发现、订阅、tungstenite heartbeat、DataEngine dedup、依赖升级或 `@refs`。

### I1 验收门槛

```bash
.venv/bin/python -m pytest \
  tests/test_restart_circuit_breaker.py \
  tests/test_liveness_watchdog.py -x
.venv/bin/basedpyright src/polysignal_lab/observability/liveness_watchdog.py
rtk git diff --check
```

运行时使用 `docs/agents/loop-repair-issue69-2026-08-18.md` 中的 baseline/采样命令，观察 **45 分钟**：
至少覆盖 1800 秒断路器窗口和一个 15 分钟市场边界。成功条件是：代码门槛全部通过；45 分钟
canary 无未恢复的 `data_starvation`、持续 `code=1008` 或未经解释的容器重启；heartbeat 的
`last_data_at` 继续推进。若自然出现 breaker-open，history 不得按 poll 周期无限增长；若未自然
出现，记录该运行路径为 `not exercised`，不得主动制造生产断流，I1 仍可凭确定性回归测试完成。

I1 完成后，下一轮才进入交接文档中待验证的 **stall 自愈 v2**：
`awaiting_first_book` 或 `stale_orderbook` → `_data_stall_refresh_due` → `request_instruments`
→ ≤5 分钟内 book/订单/`GATE_ACCEPT` 恢复，且无需手动重启。

## 第 7 轮状态 / Iteration I1 执行完成 — 2026-08-18 20:31 UTC

状态：**I1（watchdog breaker history/latch re-arm）已修复、部署、验证中**。

### 本轮改动（工作区，未 commit）

- `src/polysignal_lab/observability/liveness_watchdog.py`：breaker-open 前置短路 —
  已 open 时不再 `_append_restart_timestamp`（保留 closed 路径的 append-before-check）；
  日志 open 分支合并为单次判定。`build-info.json` 更新为
  `1.0.0-debug.127+1258ec35fdca`（勿 git checkout 还原）。
- `tests/test_restart_circuit_breaker.py`（+1 回归）：
  `test_breaker_open_episode_does_not_append_history_per_poll`。
- Code gates：pytest 19 passed、basedpyright 0 errors、git diff --check clean。

### 部署与生产证据（自然事件，无人工诱导）

- 部署 20:29:27Z（镜像 `polysignal-lab:debug-issue69-fix`，
  digest `sha256:6f3e53e3…069db`）；容器 20:29:38Z 启动，healthy，RestartCount=0。
- 缺陷现场完整采集：19:52:45 起每 30s 无间断追加（60 条 = 窗口容量上限）；
  breaker open 后 recent_count 37→38→60 持续增长；readiness_miss 自 20:10:00，
  `last_data_at` 停于 20:05:14（18.5 分钟），31 条件 bookless，stall 自愈 adapter
  replay 未确认 — **旧代码永远压制重启，断流无法自愈**。
- 部署后 43 秒 `last_data_at=20:30:21` 恢复流动；**history 停止增长**
  （最后一条 20:29:32 = 部署前）— 新代码 open 短路生效的运行时证据。

### 45 分钟 canary 观察窗口（至 20:29 + 45min ≈ 21:15 UTC）

- 观察：history 在 open 期间不增长；窗口自然冷却（20:53 起 19:53:45 首条过期，
  ~21:23 全部过期）；若冷却后断流再现，同实例应 fire restart（RestartCount+1 可解释）；
  无持续 1008 / 无未恢复 data_starvation / GATE_ACCEPT 恢复。
- 每 6 分钟采样（cron job `8f997ff4`）追加到
  `docs/agents/loop-repair-issue69-2026-08-18.md` I1 result 段。

### Next iteration（I1 canary 通过后）

- **stall 自愈 v2 runtime 验证**：`awaiting_first_book`/`stale_orderbook` →
  `_data_stall_refresh_due` → `request_instruments` → ≤5 分钟 book/订单/GATE_ACCEPT
  恢复且无需手动重启。若自然断流发生在 I1 canary 期间且由本次部署恢复，
  该事件已计入 I1（部署即恢复手段）；纯自愈（不重启）仍需自然事件验证。

## 第 8 轮状态 / Iteration I1 闭环验证完成 — 2026-08-18 21:33 UTC

状态：**I1 全部 acceptance gates 通过（含两次迭代：短路修复 debug.127 → 漩涡修复
debug.128）**，watchdog 自动重启闭环在自然事件中完整验证。

### I1 迭代历程（本轮生产事件链，全部自然触发）

1. **debug.127 部署**（20:29Z）：修复 open 期间每 poll 追加（历史 60 条/窗口容量满、
   recent_count 37→38 现场证据）；20:30 数据恢复、history 停止增长。
2. **冷却漩涡发现**（R7，21:02）：count 自然衰减至 2 → closed 路径 append 假尝试
   （未来时间戳）→ count 回 3 → 恒卡 max，fire 永不发生。末两条旧条目间隔 17s 使
   count 衰减到 2 而非 1，预判的 fire 未发生。生产取证：history 60→3 条、
   recent_count 恒 3 达 8 轮。
3. **debug.128 漩涡修复**（21:10Z）：仅在真实 fire restart 时 append；open 短路保留；
   测试 2/4 语义更新 + 计数断言；19 passed / basedpyright 0 errors / diff clean。
4. **闭环验证**（R11，21:32）：新断流 21:17:08 → 21:23:44 readiness_miss → open 短路
   **8 次 poll 零 append** → 21:28:45 残留过期 count=2 → append+fire(data_starvation)
   → 21:29:12 容器重启（RestartCount=1）→ 21:31:44 数据恢复 → GATE_ACCEPT 喷发。
   **全程无人干预**，同场景下 debug.127 会卡漩涡。

### 部署

| 项 | 值 |
| --- | --- |
| 镜像 | `polysignal-lab:debug-issue69-fix` digest `sha256:81b882dc…7e27` |
| build-info | `1.0.0-debug.128+1258ec35fdca` |
| 容器 | StartedAt=21:29:12Z RestartCount=1（watchdog 监督重启，可解释）healthy |
| 代码改动（未 commit） | `liveness_watchdog.py`（open 短路 + fire 才计数）、`tests/test_restart_circuit_breaker.py`（语义更新 + 2 个新断言） |

### I1 验收结论

- open 期间 history 零增长 ✓；冷却不续期 ✓；同实例 cooldown → re-arm → restart ✓
- 无持续 1008、无未恢复 data_starvation、无未经解释重启（1 次重启=watchdog fire）✓
- **I1 完成**。canary 剩余防回归采样持续至 21:55Z。

### Next iteration — I2：stall 自愈 v2 runtime 验证（R5 已有证据缺口）

R5 记录：12 个 bookless 新窗口条件 `subscribe_requested=False`、无 replay 计时、
`_data_stall_refresh_due` 未触发（awaiting 判定缺失）→ request_instruments 从未发出。
I2 需确认：轮换窗口条件的订阅意图建立路径为何缺失（发现新条件 → `_subscribe_market_conditions`
→ 新条件未进入 `_subscription_state.awaiting_book_sides_by_condition`？），修复后验证
`awaiting_first_book`/`stale_orderbook` → 自愈 → ≤5 分钟恢复且无需 watchdog 重启。

## 第 9 轮状态 / I1 正式完成 — 2026-08-18 22:03 UTC

状态：**I1（watchdog breaker history/latch re-arm）完成，canary 收官，全部 gates 通过**。

### I1 最终结论（详见 loop-repair 文档 Iteration I1 result）

- 恢复路径确认：WS 周期断流（8-12min，B 缺陷）→ readiness_miss/data_starvation
  → watchdog fire（窗口内真实 restart ≤3 + 冷却）→ 容器重启 → 数据恢复。
  **4 次 fire（21:28:45/21:38:56/21:51:12/21:58:55）全部自动闭环，无人干预**。
- history 语义最终形态：3 条 = 窗口内真实 restart 时间戳，open 零增长、出窗即 prune、
  fire 才计数。
- 代码门：19 passed / basedpyright 0 / diff clean。部署：debug.128（digest 81b882dc）。

### 观察项（记录给 I2）

1. `code=1013 slow consumer: send buffer full`（21:58:40）——B 缺陷新症状变体，
   WS 数据积压触发 venue 关闭；与 1008 同族。
2. stall 自愈 v2 仍未见触发日志（R5 证据缺口仍在：换轮条件 subscribe_intent 未建立）。
3. watchdog restart 兜底下生产可持续运行（每次 fire 后恢复），但断流周期未根除 —
   I2 目标是让 request_instruments 自愈在 watchdog 重启前恢复数据。

### Next iteration — I2：stall 自愈 v2（awaiting → request_instruments → ≤5min 恢复）

- 范围建议：`lifecycle.py:_data_stall_refresh_due` 触发链 + `subscriptions.py`
  订阅意图建立（换轮条件进入 awaiting 集合）+ 对应回归测试。
- 验收：自然断流时无需 watchdog 重启、≤5 分钟数据/订单恢复；watchdog fire 计数
  在自愈生效后应显著下降（当前每 ~10min 一次）。

## 第 10 轮状态 / Recovery 链修复执行 — 2026-08-21（未部署）

状态：**Readiness/Orderbook/Subscription 恢复链四项修复已实现并通过代码门禁**。

### 本轮代码改动（工作区，未 commit，不使用 codex review）

1. **abandoned condition 重入契约**（`lifecycle.py:_attach_discovered_conditions`）
   - discovery 对 `_no_book_abandoned_at_by_condition` 抑制窗口内的 condition 不再加入
     `_active_condition_ids`，只刷新 registry metadata；新增 `discovery_attach_suppressed` 日志。
   - 窗口过期后 `_subscribe_suppressed()` 清除 marker，同一 discovery 轮重新 attach 并建立订阅 intent。
   - 回归：`tests/test_issue69_market_discovery.py` 新增 4 个测试（suppressed 跳过、混合、窗口过期重 attach、heartbeat 路径）。

2. **单 generation recovery + 显式 timeout 可观测性**
   - `MarketSubscriptionState.book_recovery_attempt_count_by_condition`：每次 recovery batch dispatch 计数，
     generation begin/finish/retire 时清除。
   - readiness detail 新增 `adapter_replay_timeout`、`recovery_attempt_count`、`recovery_dispatched_at_by_side`、`missing_sides`。
   - `runtime_health._detail_counts_toward_readiness_miss`：replay grace 结束后带 timeout 证据的 never-READY
     计入 liveness clock（不再无限 warmup）。
   - monitor（`scripts/monitor_issue69_reconnect.py`）：timeout 状态判定为 unrecovered，而非 replay_unconfirmed。
   - 回归：`tests/test_issue69_blocker_regressions.py` +2、`tests/test_issue69_monitor.py` +1。

3. **instrument refresh 失败可观测性**
   - `_request_instrument_refresh` 成功/失败日志携带 `pending_instrument_count`，失败还带 `last_request_at`；
     失败不消耗节流（可立即重试的语义保留）。
   - 回归：`tests/test_issue69_market_discovery.py` +1。

4. **discovery 失败可见性与 readiness 语义**
   - `market_discovery_error`（WARN，原 debug）与 `market_discovery_empty`（INFO）。
   - startup grace 到期后 active-but-unsubscribed 条件计入 readiness miss。
   - 回归：`tests/test_issue69_market_discovery.py` +1、`tests/test_readiness_liveness_split.py` +1。

### Code gates（全部通过）

```bash
pytest 目标 15 文件                      # 259 passed（含 dashboard）
basedpyright lifecycle/subscriptions/readiness/runtime_health   # 0 errors, 54 warnings（既有基线）
git diff --check                        # clean
```

### 未完成 / 下一轮

- 未构建镜像、未部署 canary（`POLYSIGNAL_IMAGE_REF` 未固定新 digest）。
- 未做 45 分钟运行时观测（两个 15 分钟边界、自然 reconnect、自然 instrument refresh）。
- 1008/1000/1001 reconnect restore 净化仍属 Rust wheel/上游范围，保留为仓库外验收项。
- `InvalidStateTrigger`（订单状态告警）本轮明确未修改。

## 第 10 轮 canary（准备中 → 结果）— 2026-08-21 debug.129

### 部署

| 项 | 值 |
| --- | --- |
| 镜像 | `polysignal-lab:debug-129-sha-1258ec35fdca`（digest 84e9e2a638d2…） |
| build-info | `1.0.0-debug.129+1258ec35fdca`，source_ref `debug/orderbook-recovery` |
| 容器 | StartedAt=2026-08-21T00:46:30Z，RestartCount=0 |
| 部署方式 | `docker compose up -d --no-deps polysignal-lab`；`.env` 临时更新 POLYSIGNAL_IMAGE_REF（备份 /tmp/.env.before-129） |

### 45+ 分钟观测（00:46:30 → 01:39:21 UTC，超过 45 分钟）

- **恢复证据**：01:03 数据回流，heartbeat `last_data_at` 推进；01:39 最终 `readiness_ok`、detail=0、miss=0，容器 healthy。
- **交易**：45 分钟窗口内 `GATE_ACCEPT` 2537（新窗口正常交易）。
- **新观测字段生效**：8→4 个 waiting 条件的 detail 均含 `adapter_replay_timeout`、`recovery_attempt_count`、`missing_sides`、`recovery_dispatched_at_by_side`（本轮新增）。
- **suppressed 契约生效**：`discovery_attach_suppressed` 高发（约 1038 次/50m），但条件未被反复 attach→abandon（重建 active 的高频循环被打破；`book_recovery_batch_dispatched` 243，每个 generation 有界）。
- **旧问题回归**：`Event loop is closed`/`delta precision`/`SIGKILL`/`unsubscribe handler error` = 0。

### 仍需关注（未完全通过 canary）

- **abandon→suppress 仍频繁**：50m `condition_abandoned_no_book` 约 460 次（旧现场为 180/30m）；说明 1013 slow-consumer 断流下条件仍反复 abandon，只是不立刻重进 active。需后续验证这是“真 generation 超时”还是仍过多。
- **GATE_REJECT.*STALE_ORDERBOOK** 约 230/50m（多为市场切换期瞬时，恢复后 01:39 readiness_ok 时归零）。
- **InvalidStateTrigger** 4630（OrderSubmitted/OrderAccepted；按计划本轮不修改，仅记录）。
- 1008/1000/1001 restore 净化仍属 Rust wheel/上游范围；1013 slow-consumer 仍在（2 次/50m）。

### 结论

- 代码侧修复在运行时产生预期新字段，suppressed 契约阻止了“被抑制条件进入 active 后无订阅”的非法组合；数据与交易在 45 分钟窗口内恢复并维持 healthy。
- canary 未完全合格（高频 abandon 与 InvalidStateTrigger 仍未根除），继续观察；不宣告整体成功。

## 第 10 轮 canary 第二次部署 — 2026-08-21 debug.129b

- 为诊断高频 abandon，给 `condition_abandoned_no_book` 的 message 追加 `strategy=`、`condition_id=`、`stall_sec=`；extra 仍保留原始字段。
- 重建镜像 `polysignal-lab:debug-129b-sha-1258ec35fdca`，.env 指向该 tag（备份 /tmp/.env.before-129b），`docker compose up -d --no-deps polysignal-lab`。
- 部署时间 01:47:29Z，容器 RestartCount=0，健康启动中；新 canary 从 01:47 重新开始继续观察。

## 第 10 轮 canary 二次观测 — 2026-08-21 debug.129b

- 采样截至 2026-08-21T02:38:22Z，运行约 51min；RestartCount=0，Health=unhealthy。
- 最终 heartbeat：`phase=readiness_miss`，`detail=8`, `miss=5`，`last_data_at=02:30:56Z`。
- 8 个 detail 均为 `awaiting_first_book`、`adapter_replay_timeout=true`、`attempts=2..8`、`ever=True`；是 once-READY 条件又进入 replay/awaiting。
- `Runtime readiness miss started: condition_id=__global__` 在 09:38 开始记录，说明 readiness miss 进入 liveness。
- 6 分钟内仍有 `discovery_attach_suppressed` 高频，venue 断流后多策略重复抑制同条件（`condition_abandoned_no_book` 有 message 带 strategy/condition_id），但 heartbeat 仍 health=unhealthy。
- `condition_abandoned_no_book` 到新日志已可区分 condition，但尚未从运行数据消除高频。
- `InvalidStateTrigger` 仅记录，不修改。

结论：debug.129b canary **未通过**。恢复链在代码侧和观测可读性上有进展，但生产运行仍未稳定满足目标，下一步应停止盲目重复采样，优先写代码策略减少多策略重复 abandon/suppress，再部署。

### 02:39Z 复采

- Health=unhealthy；`last_data_at=02:31:12Z`；`detail=4`、`miss=5`（含 `__global__`）。
- 4 个 detail 均 once-READY awaiting_first_book、retry attempts 6~8；venue WS 仍无法在 refresh/restore 后及时恢复。
- 本地代码门：目标相关 pytest 全绿；basedpyright subscriptions 0 errors；diff check clean。
- 判定：canary 未通过，主因更接近外部 WS/live restore 路径，非本轮 Python 控制面。

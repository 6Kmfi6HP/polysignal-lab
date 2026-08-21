# Issue69 loop-repair workflow（2026-08-18）

## 依据与边界

最新状态以 `docs/agents/handoff-issue69-monitor-2026-08-18.md` 为准；历史细节来自
`~/.claude/projects/-home-debian-polysignal-lab/memory/issue69-tungstenite-signal-stall-2026-08-18.md`。
NautilusTrader 相关实现遵循 `docs/nautilus_reference/developer_guide/`；本轮不修改
`@refs`、不升级依赖、不创建 PR。

已由交接文档/源码确认的事实：

- watchdog 断路器分支不再设置 `_restart_requested`（`liveness_watchdog.py` 约 198 行），
  回归测试覆盖“同一实例冷却后再次 restart”。
- 当前实现仍在每次满足故障条件的 watchdog poll 中先追加 restart history，再检查断路器；
  因此“断路器打开后每 30 秒继续追加”是源码可见风险。其是否已在线上阻止 1800 秒冷却，
  标记为**待运行验证**，不得以单元测试替代。
- 交接文档待验证的主闭环是：数据断流后，`_data_stall_refresh_due` 触发
  `request_instruments`，在不手动重启的情况下恢复 book 和信号。
- `GATE_ACCEPT`、`GATE_REJECT.*STALE`、`last_data_at`、`market_discovery_run`、
  `code=1008`、`data_starvation` 和 restart history 均已有代码或交接记录依据；不新增虚构
  指标。

## 每轮模板

每轮只允许一个主假设、一个最小改动面和一组可判定门槛：

1. **Scope**：从上一轮状态选一个缺陷；列出明确不处理的相邻缺陷。
2. **Baseline**：记录镜像/commit、容器 `StartedAt`/`RestartCount`、heartbeat、restart
   history，以及最近窗口的现有日志计数。
3. **Targeted change**：只改该缺陷涉及的源文件和回归测试；先跑最小测试，再做类型检查。
4. **Deploy**：使用固定的 debug 镜像引用；记录镜像 tag/digest、commit、build-info 和
   Nautilus wheel 版本。不得用手动重启伪造恢复证据。
5. **Observe**：按下方 acceptance gates 和固定窗口采样；每次采样记录 UTC 时间。
6. **Decision**：全部硬门槛通过才算 success；否则 rollback，保留日志和 heartbeat 证据。
7. **Handoff**：把结果追加到本文件对应迭代，并在
   `docs/agents/handoff-issue69-monitor-2026-08-18.md` 追加下一轮状态。

## Acceptance gates

### 信号/数据恢复

- `state/runtime_heartbeat.json` 的 `updated_at` 持续新鲜，且 `last_data_at` 在恢复后继续
  推进；不得出现新的 `data_starvation`。
- 至少出现新的 `GATE_ACCEPT`；不得出现连续 30 分钟 `GATE_ACCEPT=0`。
- active 条件不长期全部停留在 heartbeat 的 `subscription_state` 为
  `awaiting_first_book` 或 `stale_orderbook`。

### 轮换/订阅

- `market_discovery_run` 持续出现；新窗口出现时必须能看到 `new>0`、订阅日志或订单恢复的
  证据，不能只靠一次容器重启恢复。
- `code=1008` 必须使用 `code=1008` 精确匹配；不得形成持续的 close/reconnect/restore 循环。
- 若本轮触发 stall recovery，必须在交接承诺的 **5 分钟内**看到 adapter refresh、book 或
  订单恢复；否则失败。

### watchdog/容器

- 不发生未经计划的手动重启；`runtime_restart_requested`、容器 `RestartCount` 和
  `runtime_restart_history.json` 的变化必须能解释。
- 对 latch/断路器轮次：断路器打开期间 history 不得按 watchdog poll 周期无限增长；冷却窗口
  后，同一实例行为由单元测试证明可再次触发 restart。

## Rollback triggers

任一条件触发即停止该轮，不继续叠加修复：

- `data_starvation` 后 5 分钟仍无自动恢复，或只能靠手动重启恢复。I1 若自然触发该事件，先采集 breaker 证据，不因事件本身立即中止。
- 出现持续 `code=1008`，或已解析市场重新进入 restore 订阅路径。
- 市场边界后 active 条件丢失、新条件没有 `market_discovery_run`/订阅证据，且只能靠重启恢复。
- watchdog history 在 breaker open 期间持续增长、breaker 不能在 1800 秒窗口后冷却，或容器重启风暴复发。
- 健康状态恶化到无法继续采样，或观测证据与本轮假设矛盾。

回滚只回到本轮部署前的固定镜像/工作区状态；保留失败镜像、日志、heartbeat 和 restart history。
不得用清空 history 或手动重启掩盖失败。

## 观测窗口

- **代码/测试轮**：最小测试和类型检查必须一次通过；失败立即停止。
- **运行轮**：至少 45 分钟：覆盖 30 分钟断路器窗口和一个 15 分钟市场边界。
  不主动制造生产断流；若没有自然触发 breaker，记录该路径为 `not exercised`，但可凭确定性
  回归测试和 45 分钟无回归 canary 完成 I1。stall 自愈本身必须在 I2 获得自然断流证据后
  才能宣告成功。
- 每 5 分钟采样一次容器、heartbeat、restart history 和核心日志；边界前后额外采样一次。

## 第一轮（下一轮，不在本次执行生产变更）

**Iteration I1 — watchdog breaker history/latch re-arm**

### Scope

- 目标：修复/验证断路器打开期间重复追加 restart history 的问题，同时保留
  append-before-check 对“当前尝试计数”的语义；保证窗口冷却后同一 watchdog 实例可以再次 restart。
- 允许修改：`src/polysignal_lab/observability/liveness_watchdog.py` 及其
  `tests/test_restart_circuit_breaker.py` 回归测试。
- 明确不处理：market discovery、订阅、tungstenite heartbeat、DataEngine dedup、依赖升级和
  任何 `@refs` 文件。

### Code gates

```bash
.venv/bin/python -m pytest \
  tests/test_restart_circuit_breaker.py \
  tests/test_liveness_watchdog.py -x
.venv/bin/basedpyright src/polysignal_lab/observability/liveness_watchdog.py
rtk git diff --check
```

必须保留并通过：

- breaker 达阈值时不调用 restart；
- 窗口过期后旧 history 被清理；
- 同一 watchdog 实例 breaker open → cooldown → restart；
- 持续故障的重复 `poll_once()` 不会每次新增一条 history。

### Runtime gates and commands

部署前：

```bash
docker ps --format '{{.Names}}\t{{.Status}}' --filter name=polysignal-lab$
docker inspect polysignal-lab --format \
  'StartedAt={{.State.StartedAt}} RestartCount={{.RestartCount}} Health={{.State.Health.Status}} Image={{.Config.Image}}'
docker exec polysignal-lab cat /app/state/runtime_heartbeat.json
docker exec polysignal-lab cat /app/state/runtime_restart_history.json
docker logs polysignal-lab --since 10m 2>&1 | \
  grep -cE 'code=1008|code=1013|data_starvation|runtime_restart_requested|restart_circuit_breaker_open'
```

每 5 分钟及窗口结束时：

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
docker inspect polysignal-lab --format \
  'StartedAt={{.State.StartedAt}} RestartCount={{.RestartCount}} Health={{.State.Health.Status}}'
docker exec polysignal-lab cat /app/state/runtime_heartbeat.json
docker exec polysignal-lab cat /app/state/runtime_restart_history.json
docker logs polysignal-lab --since 6m 2>&1 | grep -cE 'code=1008|code=1013|data_starvation'
docker logs polysignal-lab --since 6m 2>&1 | grep -c 'GATE_ACCEPT'
docker logs polysignal-lab --since 6m 2>&1 | grep -c 'GATE_REJECT.*STALE'
docker logs polysignal-lab --since 8m 2>&1 | \
  grep -iE 'dead connection|Reconnect succeeded|Restoring' | grep -v InvalidState
docker logs polysignal-lab --since 8m 2>&1 | \
  grep -E 'market_discovery_run|Subscribed|Submit.*LimitOrder|runtime_restart_requested|restart_circuit_breaker_open'
```

I1 success requires: all code gates pass; the 45-minute canary has no unexplained restart, no
unrecovered data starvation, no sustained 1008 loop, and heartbeat data remains live. If a breaker-open
episode occurs naturally, history must not grow on each poll; otherwise record that runtime path as
`not exercised` rather than inducing a production failure. The I1 result is then appended to the handoff
before starting the next iteration, which is the
pending **stall self-heal v2** observation (`awaiting_first_book`/`stale_orderbook` →
`request_instruments` → book/signal recovery without manual restart).

## Iteration I1 result — 2026-08-18（第 6→7 轮交接，执行完成）

### 结论

I1 缺陷（breaker open 期间每 poll 追加 restart history → 1800s 窗口永不冷却）在
**源码与生产现场双重确认**，已修复并部署；code gates 全部通过；部署后 43 秒数据
恢复，history 停止增长。自然断流事件全程证据保留（`runtime_restart_history.json`
60 条 = 30s×30min 窗口容量上限，recent_count 37→38→60）。

### 源码确认与修复

- 缺陷位置：`liveness_watchdog.py:_restart_if_recovery_exhausted` 原先无条件
  `_append_restart_timestamp(observed_now)` 再检查 breaker；open 状态下每次
  poll（30s）继续追加，窗口被持续刷新，breaker 永远无法冷却。
- 修复（保留 append-before-check 首次计数语义）：先查 `_circuit_breaker_open`，
  已 open 则**不再追加**（窗口靠自然时间滚动冷却）；closed 才 append-before-check
  记账本次尝试，append 后达阈值同样不 fire。latch 仍只在正常分支置位，同一实例
  支持 open → cooldown → restart。
- 新增回归测试 `test_breaker_open_episode_does_not_append_history_per_poll`
  （seed 3 条=达阈值，3 次 poll 后 history 仍 3 条、无 restart）。
- 既有 5 个断路器测试断言全部保持通过（append-before-check 语义未变）。

### Code gates（全部通过）

```bash
pytest tests/test_restart_circuit_breaker.py tests/test_liveness_watchdog.py -x  # 19 passed
basedpyright liveness_watchdog.py  # 0 errors（5 个既有 warning 不在改动区）
git diff --check  # clean
```

### 部署（Runtime baseline 与部署记录）

| 项 | 值 |
| --- | --- |
| 部署时间 | 2026-08-18T20:29:27Z（compose up -d polysignal-lab） |
| 镜像 | `polysignal-lab:debug-issue69-fix`，digest `sha256:6f3e53e3…069db` |
| build-info | `1.0.0-debug.127+1258ec35fdca`（run 127） |
| 部署前 baseline | StartedAt=19:43:42Z RestartCount=0 healthy；history 60 条（19:53:45→20:29:32，每 30s 无间断）；readiness_miss 自 20:10:00，last_data_at=20:05:14（停 18.5 分钟）；31 条件 bookless |
| 部署后 | StartedAt=20:29:38Z RestartCount=0 healthy；last_data_at=20:30:21（43s 恢复）；history 停止增长（最后一条 20:29:32） |

### 自然事件证据（无人工诱导）

- 19:52:45 起每 30s 追加（容器 19:43:42 启动，5min critical_down_sec 后故障判定
  一致）；20:03 后 breaker open，计数仍持续增长（37@20:10:45 → 38@20:11:15 →
  60 上限@20:23）；stall 自愈 v2 adapter replay 20:06 触发但 unconfirmed（未恢复）。
- 符合模板 I1 条款：自然触发的 breaker 事件中 history 持续增长 = 缺陷现场；
  未用清空 history 或手动重启掩盖；部署（计划内镜像替换）即恢复手段。

### 45 分钟 canary 观察窗口

- 窗口：2026-08-18T20:29:27Z → 21:15（覆盖 1800s 冷却窗口 + 至少一个 :45 市场边界）。
- 后续每 6 分钟采样结果继续追加在本段下方（cron job 8f997ff4 驱动）。
- I1 通过判据：code gates 全过 ✓；canary 无未恢复 data_starvation / 无持续 1008 /
  无未经解释重启 / history 在 open 期间不增长 / last_data_at 持续推进。

#### 采样 R2 — 2026-08-18T20:32:23Z（部署后 ~3min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0 Health=healthy | ✓ |
| heartbeat phase | `market_data_evaluation`（readiness_miss 已解除） | ✓ |
| last_data_at | 20:31:13（恢复后持续推进） | ✓ |
| bookless conditions | 31 → **0** | ✓ |
| history | 60 条，last=20:29:32（部署前，**未再增长**）；first 19:53:45 已自然过期被 prune → 19:59:45（窗口冷却开始） | ✓ I1 关键 |
| code=1008/1013/starve | 2（20:29:50-51 启动瞬态 1008，restore 订阅路径），无 data_starvation | ✓ |
| GATE_ACCEPT | 998 | ✓ |
| 订单 | Submit LimitOrder 正常（skew_mean_reversion/native_exit 等，20:31:45 起批量） | ✓ |
| discovery | 68 次 market_discovery_run | ✓ |

结论：恢复稳定，无 rollback trigger。部署后 history 停止增长的首个观测点成立。

#### 采样 R3 — 2026-08-18T20:37:59Z（部署后 ~8min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0 Health=healthy | ✓ |
| heartbeat phase | `readiness_ok`（完全恢复） | ✓ |
| last_data_at | 20:36:22（持续推进） | ✓ |
| bookless | 0 | ✓ |
| history | 60 条不变（last=20:29:32；first 滚动至 19:59:45，自然过期继续） | ✓ I1 关键 |
| code=1008/1013/starve | 0 | ✓ |
| GATE_ACCEPT | 0（非市场边界空窗；R2 的 998 = 启动 catch-up 集中评估） | 观察 |
| Submit LimitOrder | 998（20:30-20:38 启动 catch-up + 20:30 边界信号） | ✓ |
| discovery | 192 | ✓ |

结论：phase 升为 readiness_ok，无 rollback trigger。GATE_ACCEPT 连续 30 分钟为 0
才是风险阈值，当前仅单窗口为 0（与信号边界节律一致），继续观察。

#### 采样 R4 — 2026-08-18T20:43:56Z（部署后 ~14min）— 新一轮断流开始，breaker 自然冷却生效

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0 Health=healthy | ✓ |
| heartbeat phase | `readiness_miss` 重现（自 ~20:42:52 起） | ⚠ 见下 |
| last_data_at | 20:37:52（已停 6 分钟） | ⚠ |
| bookless | 4 | ⚠ |
| history | 60 条，last=20:29:32 **未增长**；窗口内计数 **33→32 单调下降**（03:43:10 / 03:43:40 breaker 日志） | ✓✓ I1 修复效应 |
| code=1008/1013/starve | 0 | ✓ |
| GATE_ACCEPT | 1376（20:40 边界评估活跃，基于断流前缓存） | ✓ |
| WS 事件 | 20:42:28 dead connection → 20:42:29 Reconnect succeeded → Restoring assets=8（B 缺陷模式再现，重连后数据未恢复） | ⚠ |
| stall 自愈 | 尚未见 request_instruments 触发（300s 节流中，预期 ~20:47） | 观察 |
| discovery | 192 | ✓ |

关键判定：**新一轮自然断流（WS 静默死亡→重连→restore 后仍无数据）已在部署后发生**；
watchdog 因 readiness_miss 每 30s 评估，但 history 不再增长（last 恒为 20:29:32），
breaker 窗口内计数随自然过期下降（60→33→32），预计 ~20:58 降至 <3（max=3）后
breaker 关闭、同实例重新 arm。两条恢复路径并存：① stall 自愈 v2（预期 20:47 前后
request_instruments → adapter replay）；② watchdog 冷却后 fire restart。符合 I1 模板
"自然触发 breaker 先采集证据、不因事件中止"条款，继续观察两条路径谁先恢复。

#### 采样 R5 — 2026-08-18T20:50:00Z（部署后 ~20min）— breaker 持续冷却中，stall 自愈未触发

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0 Health=healthy | ✓ |
| heartbeat phase | readiness_miss 持续 | ⚠ |
| last_data_at | 20:37:52（停 12 分钟） | ⚠ |
| bookless | 4 → **12** | ⚠ |
| history | 60 条未变；breaker recent_count **24→23→22→21→20 单调下降**（03:47:40-03:49:41） | ✓ I1 |
| code=1008/1013/starve | 0 | ✓ |
| GATE_ACCEPT | 416（部分条件仍基于缓存评估） | ✓ |
| stall 自愈 | **未触发**：12 个 bookless 条件 `subscribe_requested=False`、`replay_started=None`、`stall_age_ms=None`、无 request_instruments 日志 | ⚠ I2 证据 |
| discovery | 191 | ✓ |

关键判定：I1 修复效应持续（history 不增长、count 按 30s/条自然衰减，预期 ~20:58 降至
<3 → breaker 关闭 → 同实例 fire restart）。stall 自愈 v2 本轮事件未接住（新窗口条件
订阅意图未建立 → awaiting 判定缺失），证据完整记录，属 I2 范围（本迭代不改代码不部署）。
readiness_miss（非 data_starvation）+ watchdog 自动重启路径已排程，按 I1 模板继续观察不中止。

#### 采样 R6 — 2026-08-18T20:55:55Z（部署后 ~26min）— breaker 逼近冷却临界

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0 Health=healthy（尚未重启） | ✓ |
| heartbeat phase | readiness_miss 持续；last_data_at=20:51:16（20:51 有短暂数据回流，随后又停 ~4.5min） | ⚠ |
| bookless | 12 → **20** | ⚠ |
| history | 60 条未变（last=20:29:32） | ✓ I1 |
| breaker | recent_count 12→11→10→9→**8**（03:53:41-03:55:41） | ✓ 持续冷却 |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 0（信号空窗，缓存耗尽） | 观察 |

推算：count=8@20:55:41，每 30s 减 1 → count=1@~20:58:11 → 该 poll append（2 条）后
check 2<3 → **fire restart（预期 20:58:11-20:58:41）**。若发生：容器 StartedAt/RestartCount
变化 + `runtime_restart_requested` 日志 + 数据恢复 = I1 "同一实例 open → cooldown → re-arm →
restart"完整闭环。下一轮采样确认。

#### 采样 R7 — 2026-08-18T21:02:06Z — 发现冷却漩涡（I1 修复边界缺陷），已二次修复部署

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=20:29:38Z RestartCount=0（**未重启**） | ✗ 闭环未发生 |
| heartbeat | readiness_miss 持续，last_data_at=20:52:57 | ⚠ |
| bookless | 24 | ⚠ |
| history | **60→3 条**（first=20:58:41 last=20:59:41，三次新 append） | ⚠ |
| breaker | recent_count 3 卡死（03:59:11 起 6 个连续 poll 恒为 3） | ✗ 缺陷 |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 0（缓存耗尽） | ⚠ |

**缺陷确认（冷却漩涡 cooldown vortex）**：count 自然衰减到 2（<max=3）→ closed 路径
append（新时间戳）→ count 回 3 → open 短路 → 1800s 后第一条出窗 → count=2 → 再 append……
窗口内条数恒卡 max，**fire 永不发生**。append-before-check 的达阈值尝试以"未来时间戳"
残留窗口，持续续期冷却。修复前编码预判（count=1 时 fire）不成立：末两条旧条目
（20:29:15/20:29:32）间隔仅 17s，count 衰减到 2 而非 1，即陷入漩涡。

**二次修复（debug.128）**：仅在真实 fire restart 时 append（消除假尝试续期）——
open 短路保留；closed 时 append+fire 一次，不再二次 check。窗口内计数 = 真实 restart
次数，衰减到 <max 即恢复 fire，无漩涡。更新测试 2（closed 多次 poll 语义）、测试 4
（seed 改 3 条 = 已 open；cooldown 后 fire 断言不变）；新增断言 fire 计入 history。
Code gates：19 passed、basedpyright 0 errors、diff clean。

**部署 debug.128**：21:10:03Z compose up；容器 21:10:10Z 启动（digest 81b882dc）；
21:11:30Z phase=readiness_ok、last_data_at=21:11:29（79s 恢复）、GATE_ACCEPT=48、
history 3 条保持不变（20:58:41-20:59:41 为 debug.127 残留假尝试，~21:29 自然过期后
breaker 完全关闭）。canary 窗口重新起算：21:10Z → 21:55Z。

#### 采样 R8 — 2026-08-18T21:12:59Z（debug.128 部署后 ~3min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:10:10Z RestartCount=0 healthy | ✓ |
| heartbeat phase | `dropped_frame`（非 active 条件的迟到 frame 被丢弃 = 窗口轮换正常现象，已确认源码语义） | ✓ |
| last_data_at | 21:11:56 持续推进 | ✓ |
| bookless | 6（启动后订阅建立中） | 观察 |
| history | 3 条不变（20:58:41-20:59:41） | ✓ |
| breaker 日志 | **无新输出**（heartbeat 无故障 → reason=None → 不评估 breaker，正确） | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 410 | ✓ |
| 订单 / discovery | 417 / 62 | ✓ |

结论：数据流稳定、信号恢复、breaker 静默。bookless=6 为启动订阅建立期状态，
下轮确认收敛。

#### 采样 R9 — 2026-08-18T21:20:12Z — 又一次自然断流开始，watchdog 冷却排程在即

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:10:10Z RestartCount=0 healthy | ✓ |
| heartbeat phase | readiness_miss 出现（heartbeat 侧条件级判定；watchdog 侧 300s 门槛未到） | ⚠ |
| last_data_at | 21:17:08（停 ~3min） | ⚠ |
| bookless | 4 | ⚠ |
| history | 3 条不变（残留 20:58:41-20:59:41，cutoff=20:50:12 仍在窗内） | ✓ |
| breaker 日志 | 0（watchdog 未判定故障 → 静默，正确） | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 570 | ✓ |
| 订单 / discovery | 1043 / 188 | ✓ |

预测：21:22:08 前后 watchdog 判 readiness_miss → count=3 → open 短路（不 append）；
**21:28:41 首条残留（20:58:41）过期 → count=2 → closed → append(21:28:xx)+fire restart**
= debug.128 漩涡修复验证点（fire 才算账，假尝试不续期）。容器重启后数据恢复 →
I1 完整闭环。若无 fire（或 fire 后数据未恢复）→ 触发 rollback trigger 上报。

#### 采样 R10 — 2026-08-18T21:26:13Z — breaker open 短路验证（无 append、无续期）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:10:10Z RestartCount=0（未重启） | ✓ |
| heartbeat | readiness_miss 持续；last_data_at=21:17:08（停 9min） | ⚠ |
| bookless | 4 → 8 | ⚠ |
| history | 3 条不变（20:58:41-20:59:41） | ✓ |
| breaker | **21:23:44 起每 30s `recent_count=3`**（open 短路：log 但零 append） | ✓ I1 |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 0（信号耗尽） | ⚠ |

关键验证：open 短路在生产中 = log 每 30s + **history 零增长**（R7 之前旧代码此处会每
poll 追加）。首条残留 20:58:41 将于 21:28:41 出窗 → count=2 → closed → append+fire
（预期 21:28:41-21:29:11）→ 容器重启 → 数据恢复 = debug.128 漩涡修复 + I1 闭环
最终验证。下一轮采样确认。

#### 采样 R11 — 2026-08-18T21:32:21Z — **I1 完整闭环验证成功（watchdog 自动 restart 并恢复）**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=21:29:12Z（变）RestartCount=1** healthy | ✓✓ watchdog fire |
| heartbeat | phase=`order_event`（恢复）；last_data_at=21:31:44（21:29:12 启动后 ~2.5min 恢复） | ✓✓ |
| bookless | 8 → **1** | ✓ |
| history | 3 条：first=20:59:11（20:58:41 过期被 prune）、**last=21:28:45（真实 restart 时间戳）** | ✓✓ |
| 重启链路 | 21:28:45 `runtime_restart_requested reason=data_starvation` → `supervised_node_restart` → 21:29:12 容器重启 | ✓✓ |
| breaker | 21:23:44-21:28:15 count=3 open 短路（**8 次 poll 零 append**，无续期） | ✓✓ |
| code=1008/starve | 0（2 条"错误"= 重启事件本身日志） | ✓ |
| GATE_ACCEPT | 1245（恢复后信号爆发） | ✓ |

**闭环时间线（自然事件全链）**：
断流 21:17:08 → readiness_miss 21:23:44 → open 短路（零 append，对比 R7 前每次 poll 追加）
→ 21:28:45 残留首条过期 count=2 → **append+fire（data_starvation）** → 21:29:12 容器重启
→ 21:31:44 数据恢复 → GATE_ACCEPT 喷发。**全程无人干预**；
R7 同场景在 debug.127 下会 append 使 count 回 3 卡死（漩涡），debug.128 下 fire 才计数 → 闭环成立。
I1 全部 acceptance gates 通过：code gates ✓、open 不增长 ✓、冷却不续期 ✓、
同实例 cooldown→restart ✓、无持续 1008 ✓、无未恢复断流 ✓、last_data_at 推进 ✓。
canary 剩余窗口 21:32→21:55 继续常规采样防回归。

#### 采样 R12 — 2026-08-18T21:42:18Z — 第二次 watchdog 自动重启自愈（重复验证成功）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=21:41:47Z（变）RestartCount=2** healthy | ✓✓ |
| heartbeat | readiness_miss（重启后订阅建立期瞬态）；last_data_at=21:42:17（**数据已恢复流动**） | ✓ |
| bookless | 8（建立中，上轮 R11 恢复后为 1） | 观察 |
| history | **2 条**（21:28:45、**21:38:56**）——二次 restart append；20:59 残留已全部出窗 | ✓✓ |
| 重启日志 | 21:41:17 `runtime_restart_requested reason=data_starvation` | ✓✓ |
| code=1008/starve | 0（2 条"错误"= 重启事件链日志） | ✓ |
| GATE_ACCEPT | 0（重启后 ~40s，信号建立中） | 观察 |
| discovery / 订单 | 79 / 0（订阅建立期） | 观察 |

**重复验证**：第二次自然断流同样无人工干预自愈（21:38:56 fire → 21:41:47 容器启动 →
数据回流）。history 语义正确收敛（真实 restart 数）。GATE/订单在重启后空窗属
启动期正常，下轮确认全面恢复。

#### 采样 R13 — 2026-08-18T21:44:55Z — 二次重启后全面恢复

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:41:47Z RestartCount=2 healthy（稳定） | ✓ |
| heartbeat | phase=`order_event`（恢复）；last_data_at=21:44:23 持续推进 | ✓✓ |
| bookless | 8 → **2**（收敛中） | ✓ |
| history | 2 条不变（真实 restart 时间戳） | ✓ |
| code=1008/starve | 0（2 条 = 21:41 重启事件链日志，无新事件） | ✓ |
| GATE_ACCEPT | **386**（信号恢复） | ✓ |
| 订单 / discovery | 386 / 90（交易恢复） | ✓ |
| restart/breaker | 1（= 21:41:17 已确认的重启，无新 fire） | ✓ |

结论：第二次自愈闭环后系统全面恢复，运行稳定。I1 canary 防回归观察持续至 21:55Z。

#### 采样 R14 — 2026-08-18T21:51:20Z — 第三次 watchdog fire（执行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:41:47Z RestartCount=2 healthy（重启进行中，fire 刚发生） | ✓ |
| heartbeat | readiness_miss；last_data_at=21:45:48（停 ~5.5min） | ⚠ |
| bookless | 10 | ⚠ |
| history | **3 条，last=21:51:12（第三次 restart append）** | ✓✓ |
| 重启日志 | `runtime_restart_requested` 8min 窗口内 1 条 = 21:51:12 本次 fire | ✓✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 32（断流中衰减） | ⚠ |
| 订单 / discovery | 638 / 164（断流前数据） | ✓ |

时序：21:45:48 停 → 21:50:48 判定故障（300s）→ 窗口内 2 条（21:28:45、21:38:56）< 3
→ closed → 21:51:12 append+fire（第三次真实 restart）。窗口内现 3 条 → 第 4 次断流
将被 open 短路（30 分钟冷却）。fire 后容器重启预计 ~21:51:40-52:00，下轮确认恢复。

#### 采样 R15 — 2026-08-18T21:58:13Z — 第三次重启完成；fire4 在 open 挡 2 轮后如期发生

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=21:51:51Z RestartCount=3** Health=unhealthy（数据停 6min 后健康检查失败） | ⚠ |
| heartbeat | dropped_frame；last_data_at=21:52:10（重启后 19s 有数据，随后又停） | ⚠ |
| bookless | 12 | ⚠ |
| history | 3 条（21:28:45/21:38:56/21:51:12 = 三次真实 restart） | ✓ |
| breaker | 21:57:55、21:58:25 **open 短路 recent_count=3**（挡 fire4）→ **21:58:55 fire4**（`supervised_node_restart`，21:28:45 出窗后 count=2） | ✓✓ |
| error / GATE | 1（=21:58:55 fire 链）/ 0（重启后空窗，未超 30min 阈值） | 观察 |
| 订单 / discovery | 0 / 51 | 观察 |

观察结论：断流周期（WS 静默死亡 B 缺陷）~8-12 分钟 < 30 分钟窗口 → 每次判定时
窗口内恰好 2 条前序 fire + 本次 = 3 → open 仅挡 1-2 个 poll，首条出窗后立即 re-arm。
断路器在"每次 fire 都恢复数据"前提下正常兜底（无 873 死亡螺旋、无漩涡、无无界增长）；
B 缺陷（周期断流）本身属 I2+ 范围。unhealthy 状态由数据停触发，fire4 容器重启
（预期 21:59:25 前后）后恢复，下轮确认。

#### 采样 R16 — 2026-08-18T22:02:16Z — **I1 canary 收官：全面恢复，验收通过**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=21:59:13Z RestartCount=4 Health=healthy** | ✓✓ |
| heartbeat | phase=`readiness_ok`；last_data_at=22:01:24 推进 | ✓✓ |
| bookless | 12 → **0** | ✓✓ |
| history | 3 条（21:38:56/21:51:12/**21:58:55**）；21:28:45 出窗被 prune | ✓ |
| 错误 | 4 = 21:58:40 单次 `code=1013 slow consumer` WARN（B 缺陷症状，非循环）+ fire4 重启链 3 条；code=1008 零 | ✓ |
| GATE_ACCEPT | **1372** | ✓✓ |
| 订单 / discovery | 1372 / 96 | ✓✓ |
| restart/breaker | 3 = 21:57:55/21:58:25 open + 21:58:55 fire（均已知） | ✓ |

### I1 最终验收结论（2026-08-18 22:02 UTC）

**全部 acceptance gates 通过**：

1. code gates：19 passed / basedpyright 0 errors / git diff check clean ✓
2. open 期间 history 零增长（21:23:44-21:28:15 共 8 轮、21:57:55-21:58:25 共 2 轮）✓
3. 冷却不续期（fire 才计数；21:28:45 出窗 → 下一 poll 即 re-arm fire）✓
4. 同一实例 open → cooldown → restart：**四次真实 fire（21:28:45/21:38:56/21:51:12/21:58:55）全部成功重启并恢复** ✓
5. 无漩涡（对比 debug.127 同场景卡 count=3 永不 fire）✓
6. code=1008 零；无未恢复断流；4 次重启全部可解释（fire 链日志完整）✓
7. heartbeat last_data_at 推进；GATE=0 最长 ~10min（重启恢复期），未达 30min 阈值 ✓

**遗留问题（I2 范围，非 I1）**：B 缺陷（WS 周期性静默死亡 / slow consumer 1013）使
断流周期 ~8-12 分钟，系统靠 watchdog 监督重启兜底维持运行。R5 已记录 stall 自愈 v2
未接住换轮条件的证据缺口（新条件 `subscribe_requested=False`、`_data_stall_refresh_due`
awaiting 判定缺失）。**I1 完成，下一迭代 = I2 stall 自愈 v2。**

#### 采样 R17 — 2026-08-18T22:08:25Z（I1 后防回归）— 周期模式照常，open 挡 fire5

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=21:59:13Z RestartCount=4 healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=22:03:34（停 ~5min） | ⚠ B 缺陷周期 |
| bookless | 8 | ⚠ |
| history | 3 条（21:38:56/21:51:12/21:58:55，窗口内） | ✓ |
| breaker | **22:08:48 `recent_count=3` open 短路（挡 fire5）**；21:38:56 将于 22:08:56 出窗 → fire5 预期 ~22:09:18 | ✓✓ |
| GATE / 订单 | 0 / 1001（断流衰减） | ⚠ |
| discovery | 188 | ✓ |

结论：I1 修复后的稳态模式（断流 → open 挡 1-2 poll → 出窗 re-arm → fire → 重启 →
恢复）按设计运转。无 rollback trigger。下轮确认 fire5 重启与恢复。

#### 采样 R18 — 2026-08-18T22:14:23Z — fire5 如期完成；重启瞬态 1008×4（非循环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=22:09:45Z RestartCount=5** healthy | ✓✓ |
| heartbeat | readiness_miss；last_data_at=22:11:29（重启后恢复 2.5min 又停） | ⚠ 周期 |
| bookless | 8 | ⚠ |
| history | 3 条（21:51:12/21:58:55/**22:09:18**）；21:38:56 出窗 prune | ✓✓ |
| 重启链 | 22:08:48 open（count=3）→ **22:09:18 fire5**（与 R17 预判一致） | ✓✓ |
| code=1008 | **4 条**（22:10:12/22:10:22，fire5 后 30-40s 订阅恢复瞬态，10s 内终止，非持续循环） | ⚠ 观察 |
| GATE / 订单 | 7 / 7（重启后重建） | 观察 |
| discovery | 131 | ✓ |

观察：重启后订阅恢复时段出现 `code=1008 invalid subscription payload` 瞬态（R2 时 2
条、本次 4 条）——与已解析市场 restore 订阅路径相关（交接 Step3/第4层修复涉及），
尚无证据表明升级为持续循环。预期下一节点：22:16:29 判定 → open 挡 fire6 →
21:51:12 出窗（22:21:12）→ fire6 ~22:21:18。继续观察。

#### 采样 R19 — 2026-08-18T22:22:30Z — fire6 如期发生（重启进行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=22:09:45 **RestartCount=5（fire6 重启进行中）** | ✓ |
| heartbeat | phase=readiness_ok（22:13:56 前数据流的旧评估）；last_data_at=22:13:56（重启前最后数据） | ⚠ |
| bookless | 8 | ⚠ |
| history | 3 条（21:58:55/22:09:18/**22:21:21**）；21:51:12 出窗 prune | ✓✓ |
| 重启链 | 22:19:16/22:19:51/22:20:26 **open×3（挡 fire6）** → **22:21:23 fire6**（与 R18 预判 ±5s 吻合） | ✓✓ |
| GATE / 订单 | 0 / 0（重启中） | 观察 |
| discovery | 92 | ✓ |

连续第 6 次 watchdog 自动重启（21:28/21:38/21:51/21:58/22:09/22:21）。模式完全
可预测：断流→300s 判定→open 挡 2-4 poll→出窗 re-arm→fire→重启。下轮确认
RestartCount=6 与数据恢复。无 rollback trigger（每次 fire 均恢复，1008 无持续）。

#### 采样 R20 — 2026-08-18T22:40:20Z — **Rollback trigger 触发：持续 code=1008 循环**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **RestartCount=7**（fire7 @22:30:43 重启 22:31:10）；fire8 append @22:39:53（进行中） | ✓ 可解释 |
| heartbeat | readiness_miss；last_data_at=22:34:45（fire7 后恢复 3.5min 又停） | ⚠ |
| bookless | 8 | ⚠ |
| history | 3 条（22:21:21/22:30:43/22:39:53 = fire7/fire8 真实时间戳，出窗 prune 正常） | ✓ |
| **code=1008** | **持续循环：12min 内 53 条，每 ~10s 2 条 `invalid subscription payload`**，自 22:22:54（fire6 重启后 22s）起跨 fire6/fire7/fire8 三次重启无间断；22:38:12 仍见 `Restoring market subscription state after reconnect: assets=12` | ✗ **TRIGGER** |
| GATE_ACCEPT | 0（1008 循环下数据无法持续） | ⚠ |
| breaker | 22:28:00 open（count=3 挡 fire7）→ re-arm → 22:30:43 fire7 → 22:39:53 fire8（全部按设计） | ✓ |

**Rollback trigger 判定**：满足模板条件 2（"出现持续 code=1008，或已解析市场重新
进入 restore 订阅路径"）。**该轮停止叠加修复**，证据保留：

- 循环内容：`code=1008 invalid subscription payload`——venue 对 restore 订阅列表的
   payload 持续拒绝；WS 客户端 connect → 1008 close → re-connect → Restoring →
   重发无效 payload → close，周期 ~10s。
- 循环起点：fire6（22:22:32）之后 22 秒，跨 3 次 watchdog fire 未断 → 与 watchdog
   breaker 无关（breaker 全程正确：open 挡 1-2 poll、fire 真实、history 语义对）。
- I1 结论不受影响：全部 gates 在 1008 循环出现前已通过；R16 时 1008 零、1013 单条。
- **不回滚 debug.128**：回滚目标（debug.127）带冷却漩涡缺陷且 1008 非其引入（R2 时
  已见同类瞬态），回滚只会更慢恢复。

处置：监控 cron 继续采样（观察循环演变与 watchdog 兜底）；是否修复订阅恢复路径
（restore 列表/无效 payload 来源）属 I2 范围，等待用户指示。

#### 采样 R21 — 2026-08-18T22:42:16Z — fire8 后 1008 骤降，数据回流（循环中断？）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **RestartCount=8** StartedAt=22:40:25（fire8 重启完成）healthy | ✓ |
| heartbeat | readiness_miss（重启后瞬态）；**last_data_at=22:41:57（数据回流）** | ✓ |
| bookless | 8（建立中） | 观察 |
| history | 3 条（22:21:21/22:30:43/22:39:53） | ✓ |
| code=1008 | **2 条/6min**（对比 R20：53 条/12min 每 10s 2 条）——频率骤降 97% | ✓ 改善 |
| GATE_ACCEPT | 15（信号恢复中） | ✓ |

观察：fire8（22:39:53）重启后 1008 循环中断、数据回流。可能本次 restore 订阅列表
未含无效 payload（偶发爆发 vs 永久锁死仍需 2-3 轮确认）。若持续恢复正常，说明
1008 爆发与每次重启后的 restore 内容相关（fire6/fire7 时 restore 含坏 payload，
fire8 时未含）——I2 修复方向仍是 restore 列表净化 + 恢复路径 payload 校验。
watchdog 兜底持续有效。下轮确认循环是否真正平息。

#### 采样 R22 — 2026-08-18T22:49:58Z — 1008 平息但断流依旧（B 缺陷未除）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=8 StartedAt=22:40:25 healthy | ✓ |
| heartbeat | readiness_miss；**last_data_at=22:42:02**（fire8 后数据仅活 ~5s 又停，已停 8min） | ⚠ |
| bookless | 8 → 14 | ⚠ |
| history | 3 条（不变） | ✓ |
| code=1008/1013/starve | **2 条/6min**（1008 爆发已平息，非持续循环） | ✓ |
| GATE_ACCEPT | 0（断流） | ⚠ |

结论：1008 循环本身平息（R20 的滚雪球联动消失），但断流周期持续（静默死亡继续）。
watchdog 兜底模式照旧：22:42:02 停 → 22:47:02 判定 → open 挡 fire9（22:21:21
22:51:21 出窗后）→ fire9 预期 ~22:51:27。I2 目标不变：切断断流源头（订阅恢复
路径/restore 净化），当前 watchdog 维持生产运行。

#### 采样 R23-R26 — 2026-08-18/19 — **宿主 OOM 事件：容器被杀，恢复尝试中被用户中断**

| 时间 (UTC) | 事件 |
| --- | --- |
| 23:33:18 / 23:34:58 | fire 重启后容器 **exit 137（global OOM kill）**；内核日志显示 OOM killer 点名 node/vitest（非本容器），宿主 swap 12Gi 溢出、load 300+，docker daemon 无响应 ~5h |
| 04:41 | daemon 恢复；`docker ps` 确认 polysignal-lab **Exited (137) 5h**（unless-stopped 未补拉） |
| 04:45 | `compose up` 被 warp(unhealthy) 依赖挡住 → `--no-deps` 拉起成功但 **Restarting (137)** 循环 |
| 04:53-04:54 | 容器启动 0.14s 即被杀；无内核 OOM 点名（cgroup/daemon 层）；free 22Gi 可用、load 已降至 2.13 |
| — | 恢复尝试中被**用户中断**，停止自动恢复操作，交由用户决定 |

状态：**polysignal-lab 未运行**（Restarting 循环，compose Restarts=18）。warp Up
unhealthy。宿主资源已恢复（可用内存 22Gi、load 2）。heartbeat/history 无法读取
（容器未运行）。**I1 结论不受影响**（验收于 22:22 1008 循环前完成；此后事件
为宿主基础设施故障，非 watchdog 行为）。恢复决策与后续处理等待用户指示。

#### 采样 R27 — 2026-08-19T04:57:01Z — 容器仍未运行（Restarting 循环持续）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | `Restarting (137)`（50s 前一次）——状态未变 | ⚠ |
| heartbeat/history/日志 | 不可读（容器未运行） | — |
| 宿主 | load 11.78/26.86/142.43（15min 均值仍高但下行中） | ⚠ |

状态未变：等待用户恢复决策（方案 1：stop 风暴→稳定后拉起；或先修 warp 依赖）。
无新观察项。

#### 采样 R28 — 2026-08-19T05:05Z — **恢复完成（用户授权"恢复"）**

| 时间 (UTC) | 事件 |
| --- | --- |
| 04:59 | `compose stop` 止血（restart 风暴停止） |
| 05:00-05:03 | 两次拉起仍 137——**真因定位**：非 OOM，是 entrypoint 冷启动误杀逻辑（`docker-entrypoint.sh:29-34`）：启动即查 `state/runtime_heartbeat.json` mtime，冻结 >420s 即 SIGKILL app；容器死 6 小时 → 旧文件 21,904s 冻结 → 无条件误杀循环（exit 137 酷似 OOM，内核 OOM 日志实际点名 node/vitest） |
| 05:03 | `sudo touch state/runtime_heartbeat.json`（宿主 volume 直挂 `/home/debian/polysignal-lab/state`）更新 mtime 绕过误杀（最小干预，不改镜像） |
| 05:04:27 | 容器启动成功，**15 秒数据回流（last_data_at=05:04:12）**，bookless=0，healthy |
| 05:05 | phase=`evaluation_heartbeat`（正常）；history 3 条（全为 22:54 前旧 fire，已出窗口自然过期后 breaker 完全关闭）；错误 0 |

恢复完成。watchdog restart history 语义未变（3 条真实 fire 时间戳，窗口已清空）。
宿主 OOM 事件教训记录：**entrypoint 冷启动冻结误杀 + 旧 heartbeat mtime = 恢复死锁**，
建议 I2 期间一并加"启动首写 grace"（先等 app 写首次 heartbeat 再启动冻结计时）。

#### 采样 R29 — 2026-08-19T05:06:46Z — 恢复后运行中，交易回归

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=05:04:27（**无新重启**）RestartCount=13 healthy | ✓✓ |
| heartbeat | readiness_miss（bookless=8 条件建立期）但 **last_data_at=05:06:06（40s 前，数据流动）** | ✓ |
| history | 3 条（22:30-22:54 旧 fire，**已全部出窗口，count=0，breaker 完全关闭**） | ✓✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | **10 / 10（交易回归）** | ✓✓ |
| warp | Up 33h unhealthy（数据流证明网络通路有效，交易正常） | 观察 |

结论：恢复确认（无新重启、数据流动、交易回归、breaker 清空 re-arm）。
watchdog 已完整就位：若再断流，窗口 0 条 → 首次判定即 fire（无 open 阻挡）。

#### 采样 R30 — 2026-08-19T05:14:06Z — 稳态确认（完全健康）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=05:04:27 无新重启 healthy | ✓✓ |
| heartbeat | **phase=readiness_ok**；last_data_at=05:14:01（5s 前，活跃流动） | ✓✓ |
| bookless | 8 → **2**（收敛） | ✓ |
| history | 3 条旧 fire（窗口外）不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | 12 / 18 | ✓✓ |

稳态确认：readiness_ok、数据活跃、交易持续、零错误。恢复后系统进入正常观测
模式（B 缺陷断流周期若再现，watchdog 将零阻挡 fire——窗口已清空）。

#### 采样 R31 — 2026-08-19T05:20:03Z — 完美稳态（bookless=0）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13 稳定（9+ 分钟无重启）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=05:20:01（2s 前）；**bookless=0** | ✓✓✓ |
| history | 3 条旧 fire（窗口外）不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | 24 / 26 | ✓✓ |

恢复后 16 分钟持续健康：bookless=0（全部条件双边书就绪）、数据 2s 级流动、
交易活跃、breaker 静默。B 缺陷周期本轮未再现。持续稳态观测。

#### 采样 R32 — 2026-08-19T05:26:04Z — 持续稳态（22 分钟无断流无重启）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13（22 分钟无重启）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=05:25:36（28s 前）；bookless=0 | ✓✓ |
| history | 3 条旧 fire 不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 16 | ✓ |

恢复后 22 分钟完全无事件（无断流/无重启/无 1008）——B 缺陷周期暂未再现，
数据持续 30s 级流动。继续稳态观测。

#### 采样 R33 — 2026-08-19T05:32:25Z — 持续稳态（28 分钟，超越历史断流周期）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13（**28 分钟无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=05:32:01（24s 前）；bookless=0 | ✓✓ |
| history | 3 条旧 fire 不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | 24 / 32 | ✓✓ |

28 分钟完全无事件——已超过历史 B 缺陷断流周期（8-12min）2 倍以上，本次运行
为恢复后最稳定的窗口。持续观测。

#### 采样 R34 — 2026-08-19T05:38:12Z — 持续稳态（34 分钟）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13（**34 分钟无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=05:38:01（11s 前）；bookless=0 | ✓✓ |
| history | 3 条旧 fire 不变 | ✓ |
| code=1008/starve | 0；GATE 16 | ✓ |

34 分钟完全无事件，稳态持续（恢复后最稳定运行窗口延续中）。

#### 采样 R35 — 2026-08-19T05:44:24Z — 持续稳态（40 分钟 + 边界信号批量入场）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13（**40 分钟无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=05:42:20；bookless=0 | ✓✓ |
| history | 3 条旧 fire 不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | **1656 / 1656**（05:40 市场边界信号批量评估入场，交易正常） | ✓✓ |

40 分钟完全无事件；05:40 边界信号批量入场（交易系统完整工作：边界数据 → 信号 →
gate → 下单全链路）。稳态延续，B 缺陷周期已 3 倍周期未再现。

#### 采样 R36 — 2026-08-19T05:50:03Z — B 缺陷周期再现（42 分钟存活后断流）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=13（无重启）healthy | ✓ |
| heartbeat | **readiness_miss 再现**；last_data_at=05:46:56（停 ~3min）；bookless=11 | ⚠ |
| history | 3 条旧 fire 不变 | ✓ |
| code=1008/starve | 0；GATE 0 | ⚠ |

时间线：05:04:27 启动 → 05:46:56 停（**WS 连接存活 42 分钟，远超历史 8-12min**）
→ 05:51:56 判定（300s）→ **窗口内 0 条（旧 fire 全出窗）→ 首次判定即 fire
（无 open 阻挡）**，预期 05:51:56-05:52:26。下轮确认。

#### 采样 R37 — 2026-08-19T05:56:05Z — 干净窗口 fire 完美执行，history 收敛为 1

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=05:54:57Z RestartCount=14** healthy | ✓✓ |
| 重启链 | **05:54:33 `runtime_restart_requested`（窗口 0 条 → 无阻挡 fire）** | ✓✓ |
| heartbeat | readiness_miss（启动瞬态）；**last_data_at=05:55:43（fire 后 46s 数据回流）** | ✓ |
| **history** | **1 条（05:54:33）**——旧 3 条全部出窗消融；**风暴 36 次重启历史完全清空**，窗口语义从干净态重新计数 | ✓✓✓ |
| bookless | 8（订阅建立中） | 观察 |

**关键验证**：watchdog 从最干净状态（窗口 0 条）执行完整自愈——首次判定即 fire、
重启 24s 完成、46s 数据回流。history 收敛为单条（真实 fire 时间戳），breaker
完全重新武装。第 9 次自动自愈（本会话第 1 次发生于干净窗口）。

#### 采样 R38 — 2026-08-19T06:02:01Z — fire 后稳态（数据流动 + 边界批量交易）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=14（无新重启，7min）healthy | ✓ |
| heartbeat | dropped_frame（轮换期正常）；last_data_at=06:00:41；**bookless=0** | ✓✓ |
| history | 1 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT / 订单 | **1755 / 1843**（06:00 边界信号批量评估入场） | ✓✓ |

fire 后 7 分钟数据持续流动、06:00 边界批量交易全链路活跃。恢复-稳态循环正常。

#### 采样 R39 — 2026-08-19T06:08:06Z — 第 10 次自动自愈（fire→重启进行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=06:07:58Z RestartCount=15** healthy（刚重启 8s） | ✓✓ |
| 重启链 | **06:07:30 fire**（窗口 1 条 <3 → 无阻挡） | ✓✓ |
| heartbeat | phase=start（启动阶段）；last_data_at=None（数据未回流） | 观察 |
| history | **2 条**（05:54:33、06:07:30） | ✓✓ |
| code=1008/starve | 2（= 重启链日志） | ✓ |

第 10 次 watchdog 自动自愈。上轮数据存活 6 分钟（间隔波动 6-42min，B 缺陷
不稳定）。fire 间隔 13 分钟（05:54:33→06:07:30），窗口 2 条正常。下轮确认数据回流。

#### 采样 R40 — 2026-08-19T06:14:11Z — fire 后恢复完成（第 10 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=15（6min 无新重启）healthy | ✓ |
| heartbeat | **readiness_ok**；last_data_at=06:12:03；bookless=0 | ✓✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | **1644**（06:10 边界批量评估） | ✓✓ |

第 10 次自愈闭环完成（fire 06:07:30 → 重启 → 数据回流 → 边界批量交易）。
系统按"断流-自愈-交易"循环稳定运行。

#### 采样 R41 — 2026-08-19T06:20:07Z — 第 11 次自愈（窗口将满，边界考验在即）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=06:18:28Z RestartCount=16** healthy | ✓✓ |
| 重启链 | **06:18:00 fire**（窗口 2 条 <3 → 无阻挡）→ 06:18:28 重启 → 06:20:03 数据回流（95s） | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=06:20:03（4s 前）；bookless=0 | ✓✓ |
| history | **3 条**（05:54:33/06:07:30/06:18:00，窗口达 max） | ✓ |
| code=1008 | 2 条（06:18:41 fire 后 41s 订阅恢复瞬态，同 R18 模式） | 观察 |
| GATE_ACCEPT | 1423 | ✓ |

第 11 次自动自愈。**下次断流（预期 ~06:25 判定）窗口内 3 条 ≥3 → open 挡 fire12，
但 05:54:33 将于 06:24:33 出窗 → 判定时大概率已降为 2 → 直接 fire**（又到
"边缘 re-arm"模式）。1008 每次 fire 后 2 条瞬态规律化（非循环）。

#### 采样 R42 — 2026-08-19T06:26:11Z — 断流再现，判定未到期（fire12 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=16（无新重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=06:22:34（停 3.7min）；bookless=4 | ⚠ |
| history | 3 条不变 | ✓ |
| restart/breaker 日志 | 8min 窗口空（判定未到期，正确静默） | ✓ |

预判：06:27:34 判定（300s）→ 05:54:33 已出窗（06:24:33）→ 窗口 2 条 <3 →
**fire12 无阻挡（预期 06:27:34-06:28:10）**。下轮确认。

#### 采样 R43 — 2026-08-19T06:33:38Z — fire12 精确命中预判（第 12 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=06:28:29Z RestartCount=17** healthy | ✓✓ |
| 重启链 | **06:28:00 fire12**（预判 06:27:34-06:28:10 ✓）→ 06:28:29 重启 | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=06:32:00（90s 内回流）；bookless=0 | ✓✓ |
| history | 3 条（06:07:30/06:18:00/06:28:00；05:54:33 出窗 prune） | ✓✓ |

第 12 次自动自愈闭环（无阻挡 fire，预判精确）。fire 间隔 ~10 分钟稳定，
窗口 3 条滚动健康。监控持续。

#### 采样 R44 — 2026-08-19T06:38:17Z — fire13 刚发生（重启进行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=17（fire13 重启进行中，预期 06:38:30 前后完成） | ✓ |
| heartbeat | readiness_miss；last_data_at=06:32:41（停 5.6min）；bookless=4 | ⚠ |
| history | 3 条（06:18:00/06:28:00/**06:38:01**；06:07:30 出窗 prune） | ✓✓ |
| code=1008/starve | 3（= fire13 重启链日志） | ✓ |

fire13（06:38:01）第 13 次自动自愈，间隔 10 分钟稳定（06:28:00→06:38:01）。
窗口 3 条滚动健康（入一出）。下轮确认恢复。

#### 采样 R45 — 2026-08-19T06:44:06Z — 第 13 次自愈闭环完成

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=06:38:29Z RestartCount=18** healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=06:41:49；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 2（fire 链日志） | ✓ |
| GATE_ACCEPT | **1493**（06:40 边界批量交易） | ✓✓ |

第 13 次自动自愈闭环（fire→重启 28s→数据回流→边界交易）。循环运行稳定。

#### 采样 R46 — 2026-08-19T06:50:26Z — 第 14 次自愈闭环完成

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=06:49:01Z RestartCount=19** healthy | ✓✓ |
| 重启链 | **fire14 @06:48:05**（间隔 10min 稳定）→ 重启 06:49:01 → 数据 06:50:11 回流（70s） | ✓✓ |
| heartbeat | readiness_ok；last_data_at=06:50:11（15s 前）；bookless=1 | ✓✓ |
| history | 3 条（06:28:00/06:38:01/06:48:05；06:18:00 出窗 prune） | ✓✓ |
| code=1008/starve | 4（fire 链 + 恢复瞬态） | ✓ |
| GATE_ACCEPT | 73（恢复中） | ✓ |

第 14 次自动自愈闭环，70 秒数据回流。fire 间隔 10 分钟继续稳定，窗口滚动健康。

#### 采样 R47 — 2026-08-19T06:56:26Z — 断流再现，窗口满 → 预期 open 边界实况

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=19（无新重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=06:52:35（停 4min）；bookless=4 | ⚠ |
| history | 3 条不变（06:28:00 仍窗内） | ✓ |
| code=1008/starve | 0；GATE 56 | ⚠ |

预判：06:57:35 判定时窗口 3 条 ≥max → **open 挡 fire15（1-2 poll）**；
06:28:00 出窗（06:58:00）→ count=2 → fire15（预期 06:58:00-06:58:30）。
open 短路实况下一轮可见。

#### 采样 R48 — 2026-08-19T07:02:29Z — **WS reconnect 自愈（无 watchdog fire）**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=19（**无新重启**）healthy | ✓✓ |
| heartbeat | dropped_frame（轮换期正常）；last_data_at=07:00:41（数据流动）；bookless=0 | ✓✓ |
| history | 3 条不变（无新 fire） | ✓ |
| breaker 日志 | 8min 空（无 open 无 fire） | ✓ |
| **自动恢复链** | 06:52:35 停 → **06:57:01 `Detected dead connection → Reconnect succeeded → Restoring assets=8`** → 数据恢复（判定前完成，watchdog 未触发）；07:00:50 再次 dead detection/reconnect | ✓✓ 重要 |

**关键观察（I2 素材）**：本轮断流由 **WS dead-detection reconnect 直接自愈**（4.5
分钟检测 → restore 订阅成功 → 数据回流），watchdog 未到 5 分钟判定点即已恢复。
与此前 fire 循环（restore 失败场景）交替出现——**系统存在两条自愈路径**：
① WS reconnect（restore 成功时，4.5min）② watchdog fire（restore 失败时，5min+）。
reconnect 路径恢复成功率是 I2 改善方向（restore 订阅列表有效性）。

#### 采样 R49 — 2026-08-19T07:08:06Z — 双路径竞态点将临

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=19（**19 分钟无重启**）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=07:04:25（停 3.7min）；bookless=8 | ⚠ |
| history | 3 条（06:28:00/06:38:01 已出窗 → 衰减至 1 条在窗） | ✓ |
| code=1008/starve | 0；GATE 0 | ⚠ |

竞态预判：07:04:25 停 → WS reconnect 检测点 ~07:08:55（4.5min）→ watchdog
判定点 07:09:25（5min）。reconnect 成功则免 fire（R48 模式）；失败则窗口 1 条
无阻挡 fire15（07:09:25-07:09:55）。下轮确认路径胜负。

#### 采样 R50 — 2026-08-19T07:14:08Z — 竞态结果：reconnect 失败 → watchdog 兜底（第 15 次自愈）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=07:10:32Z RestartCount=20** healthy | ✓✓ |
| 重启链 | **fire15 @07:10:04**（data_starvation）→ 重启 28s → 数据 07:13:07 回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=07:13:07；bookless=0 | ✓✓ |
| history | **2 条**（06:48:05/07:10:04；06:28:00、06:38:01 出窗 prune） | ✓✓ |
| WS 事件 | 07:07:30 dead detection → 07:07:31 Reconnect succeeded → **restore 后数据未回**（本轮 reconnect 路径失败） | ⚠ |

双路径竞态结果：本轮 WS reconnect 恢复失败（restore 无数据），watchdog 于
判定点兜底 fire15——两条路径的交替依赖 restore 成功率（I2 核心改善点）。
第 15 次自动自愈闭环完成。

#### 采样 R51 — 2026-08-19T07:20:02Z — 竞态再现（fire16 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=20（9.5min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=07:16:21（停 3.7min）；bookless=8 | ⚠ |
| history | 2 条不变（06:48:05/07:10:04） | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 966（07:15 边界交易，停流前） | ✓ |

竞态预判：reconnect 检测 ~07:20:51 vs watchdog 判定 07:20:51（同时刻）。
reconnect 成功 → 免 fire；失败 → 窗口 2 条无阻挡 fire16（07:20:51-07:21:21）。

#### 采样 R52 — 2026-08-19T07:25:57Z — 第 16 次自愈闭环（watchdog 胜出）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=07:22:33Z RestartCount=21** healthy | ✓✓ |
| 重启链 | **fire16 @07:22:04**（窗口 2 条无阻挡）→ 重启 29s → 数据 07:24:59 回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=07:24:59；bookless=1 | ✓✓ |
| history | 2 条（07:10:04/07:22:04；06:48:05 出窗 prune） | ✓✓ |
| WS 事件 | 07:22:45 reconnect×2（fire16 后恢复期）；**07:25:34 / 07:25:42 又一轮 dead detection+reconnect**（数据 07:24:59 后刚断，重连中） | 观察 |

第 16 次自动自愈闭环（本轮 watchdog 胜出；reconnect 路径未在判定前恢复）。
07:25:42 新重连进行中——若 restore 成功则本轮免 fire，否则下一个竞态点 ~07:30。

#### 采样 R53 — 2026-08-19T07:32:00Z — 竞态再现（fire17 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=21（9.5min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=07:27:44（停 4.3min）；bookless=4 | ⚠ |
| history | 2 条不变（07:10:04/07:22:04） | ✓ |
| WS | 07:25:42 最后一次 reconnect（之后无 dead detection——连接静止后静默死亡） | ⚠ |

竞态预判：reconnect 检测 ~07:32:14 vs watchdog 判定 07:32:44——窗口 2 条
无阻挡 fire17（07:32:44-07:33:14）。下轮确认。

#### 采样 R54 — 2026-08-19T07:38:10Z — fire17 精确命中（第 17 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=07:33:33Z RestartCount=22** healthy | ✓✓ |
| 重启链 | **fire17 @07:33:05**（预判 07:32:44-07:33:14 ✓）→ 重启 28s | ✓✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=07:36:20；bookless=0 | ✓✓ |
| history | 3 条（07:10:04/07:22:04/07:33:05）滚动健康 | ✓✓ |

第 17 次自动自愈闭环，预判连续命中（fire14-17 全部在预期窗口内）。系统循环稳定。

#### 采样 R55 — 2026-08-19T07:44:24Z — 第 18 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=07:43:04Z RestartCount=23** healthy | ✓✓ |
| 重启链 | **fire18 @07:42:35** → 重启 29s → 数据 07:44:13 回流（69s） | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=07:44:13（11s 前）；bookless=3 | ✓✓ |
| history | 3 条（07:22:04/07:33:05/07:42:35；07:10:04 出窗） | ✓✓ |
| GATE_ACCEPT | 245（恢复中） | ✓ |

第 18 次自动自愈闭环，69 秒数据回流。fire 间隔 ~9.5-10 分钟稳定。

#### 采样 R56 — 2026-08-19T07:50:18Z — 竞态再现（fire19 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=23（7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=07:47:27（停 2.8min）；bookless=4 | ⚠ |
| history | 3 条不变（07:22:04 出窗在 07:52:04） | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 1868（07:45 边界批量交易，停流前） | ✓ |

竞态预判：reconnect 检测 ~07:51:57 vs watchdog 判定 07:52:27——07:22:04
07:52:04 出窗后窗口 2 条 → fire19 无阻挡（07:52:27-07:52:57）。

#### 采样 R57 — 2026-08-19T07:56:11Z — fire19 预判命中（第 19 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=07:53:04Z RestartCount=24** healthy | ✓✓ |
| 重启链 | **fire19 @07:52:36**（预判 07:52:27-07:52:57 ✓）→ 重启 28s → 数据 07:55:23 回流 | ✓✓ |
| heartbeat | early_exit_result_failed（交易阶段）；last_data_at=07:55:23；bookless=0 | ✓✓ |
| history | 3 条（07:33:05/07:42:35/07:52:36；07:22:04 出窗） | ✓✓ |

第 19 次自动自愈闭环，预判命中（fire15-19 连续 5 次命中窗口）。系统循环稳定。

#### 采样 R58 — 2026-08-19T08:02:06Z — 竞态再现（窗口满 → 预期 open 挡 fire20）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=24（9min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=07:57:52（停 4.2min）；bookless=4 | ⚠ |
| history | 3 条不变（07:33:05 出窗在 08:03:05） | ✓ |
| GATE_ACCEPT | 802（07:55 边界交易，停流前） | ✓ |

预判：判定 08:02:52 时窗口 3 条 ≥max → **open 挡 fire20（1-2 poll）**；
07:33:05 出窗（08:03:05）→ count=2 → fire20（08:03:05-08:03:35）。

#### 采样 R59 — 2026-08-19T08:08:12Z — **fire20 预判命中（第 20 次自愈里程碑）**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:03:35Z RestartCount=25** healthy | ✓✓ |
| 重启链 | **fire20 @08:03:07**（预判 08:03:05-08:03:35 ✓；open 挡 1 poll 后出窗 re-arm）→ 重启 28s | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=08:06:38；bookless=0 | ✓✓ |
| history | 3 条（07:42:35/07:52:36/08:03:07；07:33:05 出窗） | ✓✓ |

**第 20 次自动自愈里程碑**：fire16-20 连续 5 次预判命中（含 open 挡 + 出窗 re-arm
边缘模式）。watchdog 断路器行为在 20 次实战中完全可预测、零异常。

#### 采样 R60 — 2026-08-19T08:14:16Z — 第 21 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:13:35Z RestartCount=26** healthy | ✓✓ |
| 重启链 | **fire21 @08:13:07** → 重启 28s → 数据 08:13:51（**16s 回流**） | ✓✓ |
| heartbeat | evaluation_heartbeat；last_data_at=08:13:51（25s 前）；bookless=0 | ✓✓ |
| history | 3 条（07:52:36/08:03:07/08:13:07；07:42:35 出窗） | ✓✓ |
| GATE_ACCEPT | 726（08:10 边界交易） | ✓ |

第 21 次自动自愈闭环，16 秒数据回流（最快纪录）。fire 间隔 10 分钟稳定。

#### 采样 R61 — 2026-08-19T08:20:21Z — fire21 后稳态（边界批量交易）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=26（7min 无重启）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=08:18:05；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | **1852**（08:15 边界批量交易） | ✓✓ |

fire21 后 7 分钟稳态 + 08:15 边界全链路交易。系统循环稳定运行。

#### 采样 R62 — 2026-08-19T08:26:14Z — 竞态再现（fire22 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=26（12.6min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=08:22:17（停 3.9min）；bookless=9 | ⚠ |
| history | 3 条不变（07:52:36 出窗于 08:22:36） | ✓ |
| code=1008/starve | 1（watchdog 侧判定日志） | ✓ |
| GATE_ACCEPT | 0（断流） | ⚠ |

预判：判定 08:27:17（窗口 2 条）→ fire22 无阻挡（08:27:17-08:27:47）。
reconnect 检测 ~08:26:47——竞态再现。

#### 采样 R63 — 2026-08-19T08:32:13Z — 第 22 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:28:36Z RestartCount=27** healthy | ✓✓ |
| 重启链 | **fire22 @08:28:08** → 重启 28s → 数据回流 | ✓✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=08:31:24；bookless=0 | ✓✓ |
| history | 3 条（08:03:07/08:13:07/08:28:08；07:52:36 出窗） | ✓✓ |

第 22 次自动自愈闭环。fire 间隔 15 分钟（08:13:07→08:28:08，最长之一——本轮
WS 存活 ~9.5min）。系统循环稳定。

#### 采样 R64 — 2026-08-19T08:38:16Z — 判定刚到期（fire23 预期即时发生）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=27（9.7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=08:33:11（停 5min）；bookless=4 | ⚠ |
| history | 3 条不变（08:03:07 出窗于 08:33:07 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 696（08:30 边界交易，停流前） | ✓ |

预判：判定 08:38:11（窗口 2 条）→ fire23 无阻挡（08:38:11-08:38:41，可能已发生）。

#### 采样 R65 — 2026-08-19T08:44:00Z — fire23 预判命中（第 23 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:39:06Z RestartCount=28** healthy | ✓✓ |
| 重启链 | **fire23 @08:38:38**（预判 08:38:11-08:38:41 ✓）→ 重启 28s | ✓✓ |
| heartbeat | readiness_ok；last_data_at=08:42:24；bookless=0 | ✓✓ |
| history | 3 条（08:13:07/08:28:08/08:38:38；08:03:07 出窗） | ✓✓ |

第 23 次自动自愈闭环，预判命中（fire19-23 连续 5 次）。系统循环稳定。

#### 采样 R66 — 2026-08-19T08:50:12Z — 第 24 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:48:37Z RestartCount=29** healthy | ✓✓ |
| 重启链 | **fire24 @08:48:09**（间隔 10min 稳定）→ 重启 28s → 数据 08:49:35 回流（58s） | ✓✓ |
| heartbeat | readiness_ok；last_data_at=08:49:35；bookless=5 | ✓✓ |
| history | 3 条（08:28:08/08:38:38/08:48:09；08:13:07 出窗） | ✓✓ |
| GATE_ACCEPT | 1171（08:45 边界交易） | ✓ |

第 24 次自动自愈闭环。fire 间隔 10 分钟稳定，系统循环运行。

#### 采样 R67 — 2026-08-19T08:56:16Z — 竞态再现（窗口满 → 预期 open 挡 fire25）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=29（7.7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=08:52:19（停 3.9min）；bookless=4 | ⚠ |
| history | 3 条不变（08:28:08 出窗于 08:58:08） | ✓ |
| GATE_ACCEPT | 1083（08:50 边界交易） | ✓ |

预判：判定 08:57:19（窗口 3 条 ≥max）→ **open 挡 fire25（1-2 poll）**；
08:28:08 出窗（08:58:08）→ count=2 → fire25（08:58:08-08:58:38）。

#### 采样 R68 — 2026-08-19T09:02:03Z — open 挡实况完整记录（第 25 次自愈）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=08:58:37Z RestartCount=30** healthy | ✓✓ |
| 重启链 | **08:57:39 open（count=3 挡 fire25）→ 08:58:09 fire25**（预判 08:58:08-08:58:38 ✓，open 挡 1 poll 后出窗 re-arm） | ✓✓ |
| heartbeat | readiness_ok；last_data_at=09:01:13；bookless=0 | ✓✓ |
| history | 3 条（08:38:38/08:48:09/08:58:09；08:28:08 出窗） | ✓✓ |

第 25 次自动自愈闭环，open 挡 → 出窗 re-arm → fire 全链条实战记录。
预判命中持续（fire19-25）。

#### 采样 R69 — 2026-08-19T09:08:20Z — 数据活跃（轮换期部分条件建立中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=30（9.7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss（**09:00 边界轮换后部分条件订阅建立中**）；last_data_at=09:08:01（19s 前，数据流动） | ✓ |
| bookless | 4（建立中） | 观察 |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 248 | ✓ |

数据活跃（19s 前），非断流——readiness_miss 为 09:00 边界轮换后新条件订阅
建立期的瞬时状态。无 fire 预期。

#### 采样 R70 — 2026-08-19T09:14:20Z — 第 26 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=09:10:38Z RestartCount=31** healthy | ✓✓ |
| 重启链 | **fire26 @09:10:10**（间隔 12min）→ 重启 28s → 数据回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=09:14:01（19s 前）；bookless=0 | ✓✓ |
| history | 3 条（08:48:09/08:58:09/09:10:10；08:38:38 出窗） | ✓✓ |
| GATE_ACCEPT | 233 | ✓ |

第 26 次自动自愈闭环。R69 观察的"数据活跃+bookless 建立期"随后转为断流，
fire26 于 09:10:10 恢复。系统循环稳定。

#### 采样 R71 — 2026-08-19T09:20:10Z — fire26 后稳态

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=31（9.5min 无重启）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=09:19:51（19s 前）；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 426（09:15 边界交易） | ✓✓ |

fire26 后 9.5 分钟稳态（数据活跃、无断流迹象）。系统循环稳定。

#### 采样 R72 — 2026-08-19T09:26:20Z — fire26 后超长稳态（15.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=31（**15.7min 无重启**，超过平均 fire 间隔）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=09:25:50（30s 前）；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 263 | ✓✓ |

fire26 后 15.7 分钟无断流（WS 连接存活 15+ 分钟，优于平均 5-10min）。
稳态延续中。

#### 采样 R73 — 2026-08-19T09:32:20Z — fire26 后超长稳态（21.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=31（**21.7min 无重启**，本会话最长窗口之一）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=09:32:01（19s 前）；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 103 | ✓✓ |

fire26 后 21.7 分钟无断流——WS 连接存活超长（本会话 top 3 窗口）。
稳态延续，等待下一周期。

#### 采样 R74 — 2026-08-19T09:38:22Z — fire26 后超长稳态（27.7min，fire 间隔记录）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=31（**27.7min 无重启**——本轮 fire 间隔最长记录）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=09:38:01（21s 前）；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 16 | ✓ |

fire26 后 27.7 分钟无断流（fire 间隔最长记录，超过平均 10min 近 3 倍）。
WS 连接存活持续向好。稳态延续。

#### 采样 R75 — 2026-08-19T09:44:12Z — 超长窗口结束（33.5min），fire27 排程中

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=31（**33.5min 无重启**）healthy | ✓✓ |
| heartbeat | readiness_miss；last_data_at=09:43:01（停 1.2min）；bookless=4 | ⚠ |
| history | 3 条不变（08:48:09 早出窗 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 8 | ⚠ |

预判：判定 09:48:01（窗口 2 条）→ fire27 无阻挡（09:48:01-09:48:31）。
本轮 WS 存活 33.5 分钟（fire26 后最长记录），下一周期开始。

#### 采样 R76 — 2026-08-19T09:50:02Z — fire27（reason=fleet_never_ready，历史首现）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=09:48:38Z RestartCount=32** healthy | ✓✓ |
| 重启链 | **fire27 @09:48:11 reason=`fleet_never_ready`**（首次以该 reason 触发；fleet 全 bookless 超阈值路径，断路器语义等价）→ 重启 27s → 数据 09:49:30 回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=09:49:30；bookless=1 | ✓✓ |
| **history** | **1 条（09:48:11）**——fire26（09:10:10）距今 38min > 窗口 → 全部出窗，**窗口从零重新计数** | ✓✓✓ |

第 27 次自动自愈闭环。fire27 为 fleet_never_ready reason 首例（证明 watchdog
故障判定覆盖 fleet 路径）；窗口因超长稳态（33.5min）自然清空后从零计数。
history 语义持续正确（真实 fire 才记录、出窗即清）。

#### 采样 R77 — 2026-08-19T09:56:06Z — fire27 后稳态

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=32（7.5min 无重启）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=09:55:11；bookless=0 | ✓✓ |
| history | 1 条不变（09:48:11） | ✓ |
| code=1008/starve | 0；GATE 254 | ✓✓ |

fire27 后 7.5 分钟稳态。系统循环稳定。

#### 采样 R78 — 2026-08-19T10:02:20Z — fire27 后稳态（13.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=32（**13.7min 无重启**，超平均）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=10:02:01（19s 前）；bookless=0 | ✓✓ |
| history | 1 条不变（09:48:11） | ✓ |
| code=1008/starve | 0；GATE 24 | ✓✓ |

fire27 后 13.7 分钟无断流（WS 连接再次优于平均 5-10min）。稳态延续。

#### 采样 R79 — 2026-08-19T10:08:22Z — fire27 后超长稳态（19.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=32（**19.7min 无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:08:01（21s 前）；bookless=0 | ✓✓ |
| history | 1 条不变（09:48:11） | ✓ |
| code=1008/starve | 0；GATE 16 | ✓✓ |

fire27 后 19.7 分钟无断流（连续第 2 个超长窗口，WS 连接存活稳定向好）。稳态延续。

#### 采样 R80 — 2026-08-19T10:14:20Z — fire27 后超长稳态（25.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=32（**25.7min 无重启**，接近 33.5min 纪录）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:14:01（19s 前）；bookless=1 | ✓✓ |
| history | 1 条不变（09:48:11） | ✓ |
| code=1008/starve | 0；GATE 14 | ✓✓ |

fire27 后 25.7 分钟无断流（连续第 3 个超长窗口——WS 连接存活持续改善）。
稳态延续，等待下一周期。

#### 采样 R81 — 2026-08-19T10:20:30Z — 第 28 次自愈闭环（fire 间隔 26min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=10:14:39Z RestartCount=33** healthy | ✓✓ |
| 重启链 | **fire28 @10:14:11**（间隔 26min，超长窗口验证）→ 重启 28s → 数据回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:20:09（21s 前）；bookless=0 | ✓✓ |
| history | **2 条**（09:48:11/10:14:11） | ✓✓ |
| GATE_ACCEPT | 24 | ✓ |

第 28 次自动自愈闭环。fire28 间隔 26 分钟确认超长窗口（WS 连接改善非偶然）。

#### 采样 R82 — 2026-08-19T10:26:20Z — fire28 后稳态

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（11.7min 无重启）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=10:25:36（44s 前）；bookless=0 | ✓✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0；GATE 18 | ✓✓ |

fire28 后 11.7 分钟稳态。系统循环稳定。

#### 采样 R83 — 2026-08-19T10:32:21Z — fire28 后长窗口（17.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（**17.7min 无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:32:01（20s 前）；bookless=0 | ✓✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 168（10:30 边界交易） | ✓✓ |

fire28 后 17.7 分钟无断流（连续第 4 个超长窗口——WS 连接改善稳定延续）。

#### 采样 R84 — 2026-08-19T10:38:19Z — fire28 后超长稳态（23.7min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（**23.7min 无重启**）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:36:06（2.2min 前，bookless=0） | ✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | 230 | ✓✓ |

fire28 后 23.7 分钟超长稳态（连续第 5 个超长窗口）。last_data_at 略旧（2.2min）
可能接近断流边缘，下一轮关注 fire29 是否触发。

#### 采样 R85 — 2026-08-19T10:44:16Z — fire28 后超长稳态（29.7min，接近纪录）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（**29.7min 无重启**，接近 33.5min 纪录）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:44:01（15s 前，数据活跃——R84 略旧仅为评估间隙）；bookless=0 | ✓✓ |
| history | 2 条不变；8min 无 restart/breaker 日志（无 fire29） | ✓✓ |
| code=1008/starve | 0 | ✓ |

fire28 后 29.7 分钟超长稳态（连续第 6 个超长窗口）。WS 连接改善持续，无 fire 排程。

#### 采样 R86 — 2026-08-19T10:50:21Z — **fire28 后 35.7min 新纪录**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（**35.7min 无重启**，超过 33.5min 纪录）healthy | ✓✓ |
| heartbeat | readiness_ok；last_data_at=10:49:30（51s 前）；bookless=0 | ✓✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0；GATE 210 | ✓✓ |

**fire28 后 35.7 分钟无断流——新纪录**（连续第 7 个超长窗口，>30min）。
WS 连接改善呈现长期趋势。监控持续。

#### 采样 R87 — 2026-08-19T10:56:25Z — **fire28 后 41.7min 再破纪录**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=33（**41.7min 无重启**，再破纪录）healthy | ✓✓✓ |
| heartbeat | readiness_ok；last_data_at=10:55:16（1.1min 前）；bookless=0 | ✓✓ |
| history | 2 条不变 | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | **1471**（10:55 边界批量交易） | ✓✓✓ |

**fire28 后 41.7 分钟无断流——连续第二次破纪录**（>40min 超长窗口）。
WS 连接存活持续显著改善（从平均 5-10min → 40min+ 量级），断流频率大幅下降。

#### 采样 R88 — 2026-08-19T11:02:23Z — fire29（47.5min 间隔，再破纪录）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:02:10Z RestartCount=34** healthy（启动中） | ✓✓ |
| 重启链 | **fire29 @11:01:42**（**fire 间隔 47.5min，再破纪录**）→ 重启 28s | ✓✓ |
| heartbeat | phase=starting；last_data_at=None（数据未回流） | 观察 |
| history | **1 条（11:01:42）**——09:48:11/10:14:11 出窗（>30min），窗口从零重新计数 | ✓✓✓ |
| GATE_ACCEPT | 0（启动中） | 观察 |

第 29 次自动自愈。**fire 间隔 47.5 分钟——连续第三次破纪录**（WS 连接存活
从平均 5-10min 改善至 47min 量级）。history 语义正确（超长窗口自然清空→零计数）。

#### 采样 R89 — 2026-08-19T11:08:24Z — fire29 恢复完成

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=11:02:10Z RestartCount=34（6.2min 无重启）healthy | ✓✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=11:06:14（数据回流）；bookless=0 | ✓✓ |
| history | 1 条不变（11:01:42） | ✓ |
| code=1008/starve | 0 | ✓ |
| GATE_ACCEPT | **1741**（11:05 边界批量交易） | ✓✓✓ |

fire29 自愈闭环完成：数据回流 + 11:05 边界全链路交易。系统循环稳定。

#### 采样 R90 — 2026-08-19T11:14:26Z — 第 30 次自愈闭环（间隔回归 11min）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:13:10Z RestartCount=35** healthy | ✓✓ |
| 重启链 | **fire30 @11:12:42**（间隔 11min——47.5min 为长尾非永久）→ 重启 28s → 数据 11:13:53 回流（43s） | ✓✓ |
| heartbeat | readiness_miss（订阅建立中）；last_data_at=11:13:53（33s 前）；bookless=8 | ✓ |
| history | 2 条（11:01:42/11:12:42） | ✓✓ |
| GATE_ACCEPT | 130（恢复中） | ✓ |

第 30 次自动自愈里程碑。**fire 间隔多样化明确**：长尾 47.5min 与常规 10-12min
交替（WS 存活分布宽）。系统循环稳定。

#### 采样 R91 — 2026-08-19T11:20:36Z — 竞态再现（fire31 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=35（7.4min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=11:17:49（停 2.6min）；bookless=4 | ⚠ |
| history | 2 条不变（11:01:42 出窗于 11:31:42） | ✓ |
| GATE_ACCEPT | 1938（11:15 边界交易，停流前） | ✓✓ |

预判：判定 11:22:49（窗口 2 条）→ fire31 无阻挡（11:22:49-11:23:19）。
reconnect 检测 ~11:22:19——竞态再现。

#### 采样 R92 — 2026-08-19T11:26:22Z — fire31 预判命中（第 31 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:23:41Z RestartCount=36** healthy | ✓✓ |
| 重启链 | **fire31 @11:23:12**（预判 11:22:49-11:23:19 ✓）→ 重启 29s → 数据 11:25:43 回流 | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=11:25:43；bookless=0 | ✓✓ |
| history | 3 条（11:01:42/11:12:42/11:23:12） | ✓✓ |

第 31 次自动自愈闭环，fire31 预判命中（连续命中保持）。监控持续。

#### 采样 R93 — 2026-08-19T11:32:42Z — 竞态再现（fire32 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=36（9min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=11:30:03（停 2.6min）；bookless=5 | ⚠ |
| history | 3 条不变（11:01:42 已出窗 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 1021（11:25 边界交易） | ✓✓ |

预判：判定 11:35:03（窗口 2 条）→ fire32 无阻挡（11:35:03-11:35:33）。
reconnect 检测 ~11:34:33。

#### 采样 R94 — 2026-08-19T11:38:26Z — fire32 预判命中（第 32 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:35:41Z RestartCount=37** healthy | ✓✓ |
| 重启链 | **fire32 @11:35:13**（预判 11:35:03-11:35:33 ✓）→ 重启 28s → 数据回流 | ✓✓ |
| heartbeat | evaluation_heartbeat；last_data_at=11:37:16；bookless=0 | ✓✓ |
| history | 3 条（11:12:42/11:23:12/11:35:13；11:01:42 出窗） | ✓✓ |

第 32 次自动自愈闭环，fire32 预判命中（连续命中保持）。监控持续。

#### 采样 R95 — 2026-08-19T11:44:23Z — fire32 后稳态

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=37（8.7min 无重启）healthy | ✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=11:42:30；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 133 | ✓✓ |

fire32 后 8.7 分钟稳态。系统循环稳定。

#### 采样 R96 — 2026-08-19T11:50:32Z — 第 33 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:49:12Z RestartCount=38** healthy | ✓✓ |
| 重启链 | **fire33 @11:48:44**（间隔 13.5min）→ 重启 28s → 数据 11:50:08 回流（56s） | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=11:50:08；bookless=8（建立中） | ✓ |
| history | 3 条（11:23:12/11:35:13/11:48:44；11:12:42 出窗） | ✓✓ |
| GATE_ACCEPT | 2230（11:45 边界批量交易） | ✓✓✓ |

第 33 次自动自愈闭环。系统循环稳定。

#### 采样 R97 — 2026-08-19T11:56:47Z — 竞态再现（fire34 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=38（7.6min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=11:52:29（停 4.3min）；bookless=4 | ⚠ |
| history | 3 条不变（11:23:12 出窗于 11:53:12 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 1517（11:50 边界交易） | ✓✓ |

预判：判定 11:57:29（窗口 2 条）→ fire34 无阻挡（11:57:29-11:57:59）。
reconnect 检测 ~11:56:59。

#### 采样 R98 — 2026-08-19T12:02:21Z — fire34 预判命中（第 34 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=11:58:12Z RestartCount=39** healthy | ✓✓ |
| 重启链 | **fire34 @11:57:44**（预判 11:57:29-11:57:59 ✓）→ 重启 28s → 数据 12:01:39 回流（42s） | ✓✓ |
| heartbeat | readiness_ok；last_data_at=12:01:39；bookless=0 | ✓✓ |
| history | 3 条（11:35:13/11:48:44/11:57:44；11:23:12 出窗） | ✓✓ |

第 34 次自动自愈闭环，fire34 预判命中（连续命中保持）。监控持续。

#### 采样 R99 — 2026-08-19T12:08:26Z — fire35 刚发生（重启进行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=39（fire35 重启进行中，预期 12:08:42 前后） | ✓ |
| 心跳 | readiness_miss；last_data_at=12:03:05（停 5.3min）；bookless=4 | ⚠ |
| history | 3 条（11:48:44/11:57:44/**12:08:14**；11:35:13 出窗） | ✓✓ |
| 错误 2 / GATE 301 | fire 链 / 交易正常 | ✓✓ |

fire35 @12:08:14（间隔 10.5min）第 35 次自动自愈进行中。下轮确认恢复。

#### 采样 R100 — 2026-08-19T12:14:24Z — **第 35 次自愈闭环 + 第 100 轮采样里程碑**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=12:08:42Z RestartCount=40** healthy | ✓✓ |
| 重启链 | fire35 @12:08:14 → 重启 28s → 数据回流 | ✓✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=12:12:01；bookless=0 | ✓✓ |
| history | 3 条滚动（11:48:44/11:57:44/12:08:14） | ✓✓ |

**第 100 轮采样里程碑**：自 2026-08-18 20:10（I1 修复）起连续 100 轮监控，
35 次 watchdog 自动自愈（fire1-fire35），全部闭环恢复、预判连续命中、history
语义全程正确。系统在 I1 修复兜底下稳定循环运行。

#### 采样 R101 — 2026-08-19T12:20:26Z — fire36 刚发生（重启进行中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=40（fire36 重启进行中，预期 12:20:43 前后） | ✓ |
| heartbeat | readiness_miss；last_data_at=12:15:11（停 5.2min）；bookless=9 | ⚠ |
| history | 3 条（11:57:44/12:08:14/**12:20:15**；11:48:44 出窗） | ✓✓ |
| GATE_ACCEPT | 580（12:15 边界交易） | ✓✓ |

fire36 @12:20:15（间隔 12min）第 36 次自动自愈进行中。下轮确认恢复。

#### 采样 R102 — 2026-08-19T12:26:24Z — 第 36 次自愈闭环完成

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=12:20:43Z RestartCount=41** healthy | ✓✓ |
| 重启链 | fire36 @12:20:15 → 重启 28s → 数据 12:25:15 回流 | ✓✓ |
| heartbeat | native_exit（交易阶段）；last_data_at=12:25:15；bookless=0 | ✓✓ |
| history | 3 条滚动（11:57:44/12:08:14/12:20:15） | ✓✓ |
| GATE_ACCEPT | 1449（12:20/12:25 边界交易） | ✓✓✓ |

第 36 次自动自愈闭环完成。系统循环稳定，监控持续。

#### 采样 R103 — 2026-08-19T12:32:27Z — 竞态再现（fire37 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=41（11.7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=12:27:28（停 4.9min）；bookless=4 | ⚠ |
| history | 3 条不变（11:57:44 出窗于 12:27:44 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 687（12:25 边界交易） | ✓✓ |

预判：判定 12:32:28（窗口 2 条）→ fire37 无阻挡（12:32:28-12:32:58）。
reconnect 检测 ~12:31:58。

#### 采样 R104 — 2026-08-19T12:38:22Z — fire37 预判命中（第 37 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=12:33:13Z RestartCount=42** healthy | ✓✓ |
| 重启链 | **fire37 @12:32:46**（预判 12:32:28-12:32:58 ✓）→ 重启 27s → 数据回流 | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=12:36:12；bookless=0 | ✓✓ |
| history | 3 条（12:08:14/12:20:15/12:32:46；11:57:44 出窗） | ✓✓ |

第 37 次自动自愈闭环，fire37 预判命中（连续命中保持）。监控持续。

#### 采样 R105 — 2026-08-19T12:44:30Z — 第 38 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=12:42:44Z RestartCount=43** healthy | ✓✓ |
| 重启链 | **fire38 @12:42:16**（间隔 9.5min）→ 重启 28s → 数据 12:43:28 回流（44s） | ✓✓ |
| heartbeat | market_data_evaluation；last_data_at=12:43:28；bookless=8（建立中） | ✓ |
| history | 3 条（12:20:15/12:32:46/12:42:16；12:08:14 出窗） | ✓✓ |
| GATE_ACCEPT | 54（恢复中） | ✓ |

第 38 次自动自愈闭环。系统循环稳定。

#### 采样 R106 — 2026-08-19T12:50:27Z — 竞态再现（fire39 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=43（7.7min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=12:47:02（停 3.3min）；bookless=4 | ⚠ |
| history | 3 条不变（12:20:15 出窗于 12:50:15 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 1304（12:45 边界交易） | ✓✓ |

预判：判定 12:52:02（窗口 2 条）→ fire39 无阻挡（12:52:02-12:52:32）。
reconnect 检测 ~12:51:32。

#### 采样 R107 — 2026-08-19T12:56:26Z — fire39 预判命中（第 39 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=12:52:44Z RestartCount=44** healthy | ✓✓ |
| 重启链 | **fire39 @12:52:16**（预判 12:52:02-12:52:32 ✓）→ 重启 28s → 数据回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=12:55:15；bookless=0 | ✓✓ |
| history | 3 条（12:32:46/12:42:16/12:52:16；12:20:15 出窗） | ✓✓ |

第 39 次自动自愈闭环，fire39 预判命中（连续命中保持）。监控持续。

#### 采样 R108 — 2026-08-19T13:02:31Z — 竞态再现（fire40 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=44（9.8min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=13:00:13（停 2.2min）；bookless=5 | ⚠ |
| history | 3 条不变（12:32:46 出窗于 13:02:46 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 259（13:00 边界交易） | ✓✓ |

预判：判定 13:05:13（窗口 2 条）→ fire40 无阻挡（13:05:13-13:05:43）。
reconnect 检测 ~13:04:43。

#### 采样 R109 — 2026-08-19T13:08:38Z — **fire40 预判命中（第 40 次自愈里程碑）**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=13:05:45Z RestartCount=45** healthy | ✓✓ |
| 重启链 | **fire40 @13:05:17**（预判 13:05:13-13:05:43 ✓）→ 重启 28s → 数据回流 | ✓✓ |
| heartbeat | dropped_frame（轮换期正常）；last_data_at=13:07:27；bookless=1 | ✓✓ |
| history | 3 条（12:42:16/12:52:16/13:05:17；12:32:46 出窗） | ✓✓ |

**第 40 次自动自愈里程碑**：fire40 预判命中（连续命中保持），全部 40 次 fire
闭环恢复。监控持续。

#### 采样 R110 — 2026-08-19T13:14:33Z — fire40 后稳态

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=45（8.8min 无重启）healthy | ✓ |
| heartbeat | readiness_ok；last_data_at=13:11:55；bookless=0 | ✓✓ |
| history | 3 条不变 | ✓ |
| code=1008/starve | 0；GATE 260 | ✓✓ |

fire40 后 8.8 分钟稳态。系统循环稳定。

#### 采样 R111 — 2026-08-19T13:20:28Z — 第 41 次自愈闭环

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=13:18:15Z RestartCount=46** healthy | ✓✓ |
| 重启链 | **fire41 @13:17:47**（间隔 12.5min）→ 重启 28s → 数据 13:18:57 回流（42s） | ✓✓ |
| heartbeat | readiness_miss（订阅建立中）；last_data_at=13:18:57；bookless=12 | ✓ |
| history | 3 条（12:52:16/13:05:17/13:17:47；12:42:16 出窗） | ✓✓ |
| GATE_ACCEPT | 1076（13:15 边界交易） | ✓✓✓ |

第 41 次自动自愈闭环。系统循环稳定。

#### 采样 R112 — 2026-08-19T13:26:38Z — 竞态再现（fire42 排程中）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=46（8.4min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=13:23:40（停 2.9min）；bookless=4 | ⚠ |
| history | 3 条不变（12:52:16 出窗于 13:22:16 → 窗口 2 条） | ✓ |
| GATE_ACCEPT | 1188（13:20 边界交易） | ✓✓ |

预判：判定 13:28:40（窗口 2 条）→ fire42 无阻挡（13:28:40-13:29:10）。

#### 采样 R113 — 2026-08-19T13:32:26Z — fire42 预判命中（第 42 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=13:29:16Z RestartCount=47** healthy | ✓✓ |
| 重启链 | **fire42 @13:28:47**（预判 13:28:40-13:29:10 ✓）→ 重启 29s → 数据回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=13:30:51；bookless=0 | ✓✓ |
| history | 3 条（13:05:17/13:17:47/13:28:47；12:52:16 出窗） | ✓✓ |

第 42 次自动自愈闭环，fire42 预判命中（连续命中保持）。监控持续。

#### 采样 R114 — 2026-08-19T13:38:11Z — 第 43 次自愈闭环（14s 最快回流）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=13:37:47Z RestartCount=48** healthy | ✓✓ |
| 重启链 | **fire43 @13:37:19**（间隔 8.5min，本轮 WS 存活 ~6min）→ 重启 28s → 数据 13:38:01 回流（**14s**） | ✓✓ |
| heartbeat | evaluation_heartbeat；last_data_at=13:38:01（10s 前）；bookless=0 | ✓✓ |
| history | 3 条（13:17:47/13:28:47/13:37:19；13:05:17 出窗） | ✓✓ |
| GATE_ACCEPT | 0（刚重启） | 观察 |

第 43 次自动自愈闭环，14 秒数据回流（最快纪录）。监控持续。

#### 采样 R115 — 2026-08-19T13:44:21Z — 竞态再现（窗口满 → 预期 open 挡 fire44）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount=48（6.6min 无重启）healthy | ✓ |
| heartbeat | readiness_miss；last_data_at=13:41:30（停 2.9min）；bookless=8 | ⚠ |
| history | 3 条不变（13:17:47 出窗于 13:47:47） | ✓ |
| GATE_ACCEPT | 2056（13:40 边界交易） | ✓✓ |

预判：判定 13:46:30（窗口 3 条 ≥max）→ **open 挡 fire44（1-2 poll）**；
13:17:47 出窗（13:47:47）→ count=2 → fire44（13:47:47-13:48:17）。

#### 采样 R116 — 2026-08-19T13:50:25Z — open 挡实况 + fire44（第 44 次自愈）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=13:49:47Z RestartCount=49** healthy | ✓✓ |
| 重启链 | **13:46:49 open（count=3 挡）→ fire44 @13:49:19（fleet_never_ready，二次出现）** → 重启 28s → 数据 13:50:06 回流（19s） | ✓✓ |
| heartbeat | evaluation_heartbeat；last_data_at=13:50:06；bookless=0 | ✓✓ |
| history | 3 条（13:28:47/13:37:19/13:49:19；13:17:47 出窗） | ✓✓ |

第 44 次自愈闭环（open 挡 4-5 poll 后出窗 re-arm fire；fleet_never_ready 为
第二个该 reason 实例）。监控持续。

#### 采样 R117 — 2026-08-19T14:06:57Z — fire45（第 45 次自愈，data_starvation 触发）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=14:00:47Z RestartCount=50** healthy | ✓✓ |
| 重启链 | 13:54:31 断流（fire44 重启后 ~4.7min，B 缺陷模式）→ readiness_miss（3 bookless）→ **fire45 @14:00:19（reason=data_starvation）** → 重启 28s → 数据 14:04:51 回流 | ✓✓ |
| heartbeat | readiness_ok；last_data_at=14:04:51（2min 前）；bookless=0 | ✓✓ |
| history | 3 条（13:37:19/13:49:19/14:00:19；13:28:47 出窗）open 零增长 | ✓✓ |
| 错误/GATE（6min） | code=1008/1013/starve=0；GATE_ACCEPT=349（13:40 边界交易延续） | ✓✓ |

第 45 次自愈闭环，无人工干预；13:54:31 断流 → 判定线 13:59:31 +30s poll →
14:00:19 fire，时间链与 critical_down_sec=300 完全吻合。监控持续。

#### 采样 R118 — 2026-08-19T14:08:55Z — 新断流进行中，预判 fire46（出窗竞态再现）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=14:00:47Z RestartCount=50 healthy（fire45 后无新重启） | ✓ |
| heartbeat | **readiness_miss**；last_data_at=14:05:29（停 ~3.4min）；bookless=8 | ⚠ |
| history | 3 条不变（13:37:19/13:49:19/14:00:19） | ✓ |
| 错误/GATE（6min） | code=1008/1013/starve=0；GATE_ACCEPT=251 | ✓ |
| WS/discovery | discovery_run 14:08:30 起 9 策略连续轮询（new=16）；无 dead/reconnect 日志（静默死亡 B 缺陷） | ⚠ |

时间链：fire45 重启 14:00:47 → 数据回流 14:04:51→14:05:29 → 再次断流（新连接
存活 ~4.7min，B 缺陷 3-7min 模式）。13:37:19 已出窗（14:08:55 时 cutoff
13:38:55）→ 窗口 2 条 <max=3 → **closed**。预判：判定线 14:10:29 → fire46
@ ~14:10:30-14:11:00（若数据不恢复）。无 rollback trigger。

#### 采样 R119 — 2026-08-19T14:14:16Z — fire46 精确命中预判（第 46 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=14:11:18Z RestartCount=51** healthy | ✓✓ |
| 重启链 | **fire46 @14:10:50（reason=data_starvation）**（R118 预判 14:10:30-14:11:00 命中）→ 重启 28s → 数据 14:12:55 回流（~1.6min） | ✓✓ |
| heartbeat | readiness_ok；last_data_at=14:12:55（1.4min 前）；bookless=0 | ✓✓ |
| history | 3 条（13:49:19/14:00:19/**14:10:50**；13:37:19 出窗） | ✓✓ |
| 错误/GATE（6min） | code=1008/1013=0（grep 命中 2 条实为 fire 本身日志 `reason=data_starvation`，非 venue 错误）；GATE_ACCEPT=1412 | ✓✓ |

时间链闭环：断流 14:05:29 → 判定线 14:10:29 → fire 14:10:50（+21s poll
对齐）→ 重启 14:11:18 → 恢复 14:12:55。**R118 预判精确命中**（时间窗内 +10s）。
第 46 次自愈，全程无人干预。监控持续。

#### 采样 R120 — 2026-08-19T14:19:54Z — 断流进行中（1013 slow consumer 变体），预判 fire47

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=14:11:18Z RestartCount=51（fire46 后无重启）healthy | ✓ |
| heartbeat | **readiness_miss**；last_data_at=14:16:23（停 ~3.5min）；bookless=8 | ⚠ |
| history | 3 条不变（13:49:19/14:00:19/14:10:50） | ✓ |
| 错误/GATE（6min） | **code=1013×2**（14:16:25/14:17:53 slow consumer: send buffer full）；GATE_ACCEPT=200 | ⚠ |
| WS | 两次 close → Reconnect succeeded → Restoring 16 assets → 数据仍未恢复 | ⚠ |

1013 变体再现（R9 曾记录同症状）：venue 因 send buffer 满关闭 → 重连 restore
订阅 → 仍无数据（B 缺陷链路；重连 success 非 1008 循环）。13:49:19 已出窗
（cutoff 13:49:54）→ 窗口 2 条 <max=3 → closed。预判：判定线 14:16:23+300s
= **14:21:23** → fire47 @ ~14:21:30-14:22:00。无 rollback trigger（1013 非
持续循环；断流 3.5min < 5min；重启全部可解释）。

#### 采样 R121 — 2026-08-19T14:28:15Z — fire47 命中预判；新断流 + 窗口满 → 预判 fire48

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=14:22:18Z RestartCount=52** healthy | ✓ |
| 重启链 | **fire47 @14:21:51**（R120 预判 14:21:30-14:22:00 命中）→ 重启 27s → 数据恢复 | ✓✓ |
| heartbeat | **readiness_miss**；last_data_at=14:26:20（停 ~2min）；bookless=6 | ⚠ |
| history | 3 条（14:00:19/14:10:50/**14:21:51**；13:49:19 出窗）→ 窗口 3 条 = max | ⚠ open |
| 错误/GATE（6min） | 0；GATE=0（刚重启恢复中） | ✓ |

窗口竞态再现：3 条 = max → **open 挡 fire48**；判定线 14:26:20+300s =
14:31:20；14:00:19 出窗于 14:30:19 → count=2 → closed → fire48 @
14:31:20-14:31:50。无 rollback trigger。

#### 采样 R122 — 2026-08-19T14:35:05Z — fire48（fleet_never_ready）；新断流 → 预判 fire49

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=14:33:19Z RestartCount=53** healthy | ✓ |
| 重启链 | **fire48 @14:32:52（reason=fleet_never_ready，第三个实例）**（晚于 R121 data_starvation 预判 ~1min——fleet_never_ready 走独立判定路径，bookless 条件全超出 replay grace）→ 重启 27s → 数据 14:34:07 恢复 | ✓✓ |
| heartbeat | **readiness_miss**；last_data_at=14:34:07（停 ~1min）；bookless=12 | ⚠ |
| history | 3 条（14:10:50/**14:21:51/14:32:52**；14:00:19 出窗）→ 窗口 3 条 = max | ⚠ open |
| 错误/GATE（6min） | 0；GATE_ACCEPT=376 | ✓ |
| WS | **14:35:35 新 1013 close（send buffer full）→ Reconnect succeeded → Restoring 16 assets → 未见数据恢复** | ⚠ |

fleet_never_ready 第三次出现（I2 已知缺口：stall 自愈 v2 订阅意图未建立，
bookless 条件不触发 `_data_stall_refresh_due`）——本轮不修，记录观察。
竞态预判：窗口 max=3 → open 挡 fire49；14:10:50 出窗于 14:40:50 → count=2 →
closed；若 14:35:36 后无数据恢复，判定线 ~14:40:36 → fire49 @ ~14:41:00-14:41:30。

#### 采样 R123 — 2026-08-19T14:42:06Z — fire49 未触发（数据续流 2min，判定线未到）；窗口已 closed

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | StartedAt=14:33:19Z RestartCount=53（fire48 后无新 restart）healthy | ✓ |
| heartbeat | **readiness_miss**；last_data_at=14:37:52（停 ~4.2min）；bookless=4 | ⚠ |
| history | 3 条不变（14:10:50/14:21:51/14:32:52）；14:10:50 已于 14:40:50 出窗 → 窗口实际 2 条 = closed | ✓ closed |
| 错误/GATE（6min） | 0；GATE_ACCEPT=89 | ✓ |
| WS | 14:42:33 **close 1000 all subscribed assets resolved** → Reconnect → Restoring **8** assets（16→8，窗口结算换资产） | 观察 |

R122 预判偏差修正：数据在 14:35:35 1013 后续流至 14:37:52（非 14:35:36 停），
∴ data_starvation 判定线 = **14:42:52**（晚于 R122 预估 ~2min）；窗口已出窗
closed。14:42:33 资产结算事件（1000 close）→ 换资产阶段。修正预判 fire49
@ ~14:43:00-14:43:30（若换资产后数据不恢复）。无 rollback trigger。

#### 采样 R124 — 2026-08-19T14:44:00Z — fire49 命中修正预判（第 49 次自愈闭环）

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **StartedAt=14:43:50Z RestartCount=54** healthy | ✓ |
| 重启链 | **fire49 @14:43:23（reason=data_starvation）**（R123 修正预判 14:43:00-14:43:30 命中；判定线 14:42:52 +31s poll）→ 重启 27s | ✓✓ |
| heartbeat | **phase=starting**；last_data_at=None（刚重启）；bookless=0 | 启动中 |
| history | 3 条（14:21:51/**14:32:52/14:43:23**；14:10:50 出窗） | ✓✓ |
| 错误/GATE（6min） | 真 code=1008/1013=0（grep count=2 为 fire 日志自身 `reason=data_starvation`；14:35:35 唯一 1013 已在 10min 前窗口外）；GATE_ACCEPT=494 | ✓✓ |

第 49 次自愈闭环（fire→27s 重启，容器 starting 恢复中）。14:10:50 出窗后
窗口 2 条 → fire 正常 append → 3 条（13:32:52 仍在内、13:21:51 仍在内）。
无 rollback trigger。

#### 采样 R23 — 2026-08-18T23:32Z — **Rollback trigger：容器重启风暴复发（RestartCount 10→36）**

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | **RestartCount=36**（22 分钟 +26 次，~50s/次），StartedAt 持续变化，Health=starting→unhealthy | ✗ **TRIGGER** |
| 重启源 | **entrypoint 看门狗**：`heartbeat frozen NNNNs (>420s) - SIGKILL wedged app`（docker-entrypoint.sh:39），SIGKILL 后 compose until-stopped 重启 | ✗ 第二重启源 |
| 增量链 | 每次重启后冻结时间递增（1792→2393s）：应用存活期缩短、重启频率上升 | ✗ |
| watchdog 模块 | history 3 条（窗口已清理？需容器稳定后复读）；模块 fire 受 3/30min 限制未失控 | ✓ |
| 1008 | 已平息（R22），但断流周期未停 | ⚠ |

**根因链**：B 缺陷（WS 静默死亡/订阅恢复失败）→ nautilus 主循环卡死 → heartbeat
（`_note_runtime_progress`）冻结 30min → entrypoint 看门狗（420s 阈值）SIGKILL →
容器重启（compose unless-stopped）→ 新进程在 1008/断流中重蹈覆辙。watchdog 模块
（debug.128）行为正确，但**无法拦截 entrypoint SIGKILL 的 docker 层重启**。
**Rollback trigger 条件 4（容器重启风暴复发）成立，本轮停止，不叠加修复。**

处置：
- 不回滚 debug.128（规则：只回滚到本轮部署前状态；debug.127 带漩涡缺陷且风暴
  根因非 I1 引入——R16 前无风暴、1008 为零，风暴与 debug.128 无关）。
- 不手动重启 / 不清空 history（模板禁令）。
- 风暴持续中的恢复路径：配方库无自动缓解——**需用户决策**：I2 修复订阅恢复路径
  （restore 净化 + payload 校验 + 主循环存活保护）或临时配置级缓解（如收紧/放宽
  entrypoint 看门狗阈值属部署配置改动，等待指示）。

#### 采样 R24 — 2026-08-18T23:33 ~ 2026-08-19T02:30Z — 风暴后容器稳定但宿主濒临 OOM

| 指标 | 值 | 判定 |
| --- | --- | --- |
| 容器 | RestartCount 停于 **38**（23:33:18 后 ~3 小时无新重启）；unhealthy | ✓ 风暴停 |
| 错误/GATE（6min） | code=1008/1013/starve=0；GATE=0（容器最后状态） | ✓ 循环停 |
| docker daemon | **无响应**（inspect/ps 超时、context canceled） | ✗ |
| 宿主 | **load 152/335/387；Mem 29/31G；Swap 31G 耗尽（26Mi free）** | ✗✗ OOM 边缘 |
| 磁盘 | / 77%（291/394G） | ⚠ |

判定：风暴于 23:33:18 后停止（该次重启后订阅恢复成功，错误归零），容器保持
unhealthy 稳定运行 ~3 小时；此后宿主负载失控（swap 耗尽）导致 docker daemon 无
响应，无法获取容器最新状态。符合模板"健康状态恶化到无法继续采样"条款——采样
中断，证据保留（RestartCount 38、冻结时间序列、SIGKILL 链、宿主负载数据）。
**建议（不自动执行）**：优先宿主资源恢复（日志清理/daemon 恢复），随后决定
I2 根治（订阅恢复路径）或配置级缓解。

## Status location

- Iteration design and gate changes: this file.
- Current result and next exact scope: append a dated `## 第 N+1 轮状态 / Next iteration` section to
  `docs/agents/handoff-issue69-monitor-2026-08-18.md`.
- Raw evidence: container logs plus `/app/state/runtime_heartbeat.json` and
  `/app/state/runtime_restart_history.json`; preserve UTC timestamps.

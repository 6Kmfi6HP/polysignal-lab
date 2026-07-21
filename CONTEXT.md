# PolySignal Lab

PolySignal Lab 用统一语言描述短周期二元预测市场中的市场观察、交易判断与模拟验证。这里区分“决定交易什么”“交易系统实际发生了什么”以及“向人展示什么”，避免把信号、订单、成交和报表混为同一事实。

## 市场与合约

**Market（市场）**：
一个有明确问题、开放区间和结算结果的二元预测合约；每个市场关联一个资产、时间周期以及 UP、DOWN 两个结果。
_Avoid_: 交易对、盘口、token

**Side（Outcome Side，结果方向）**：
市场可能结算到的二元结果，即 UP 或 DOWN。它表达预测结果，不表达订单的买卖方向。
_Avoid_: OrderSide、BUY、SELL

**Outcome Token（结果 Token）**：
代表某一市场中特定结果方向的可交易权益；同一市场的 UP 与 DOWN 分别对应不同的 Outcome Token。
_Avoid_: Side、Market、Instrument

**Market View（市场视图）**：
某一时点用于形成交易判断的不可变市场观察，包含两个结果方向的价格与深度、现货参照、时间信息、数据新鲜度以及已有交易活动。
_Avoid_: Market Snapshot、实时账本、盘口真相

**Price to Beat（目标价）**：
市场用来判定标的资产最终属于 UP 还是 DOWN 的参照价格。
_Avoid_: 入场价、限价、现货价

## 判断与资格

**Alpha Decision（Alpha 决策）**：
策略基于 Market View 形成的不可变交易意图，说明目标 Outcome Side、价格边界、置信度、理由以及期望的执行方式。它是“系统想交易什么”的唯一事实，不表示订单已经提交或成交。
_Avoid_: Signal Candidate、Order、Fill

**Order Intent（订单意图）**：
Alpha Decision 对期望执行语义的描述，例如被动挂单、立即部分成交或全部成交；它不是执行引擎最终接受的订单状态。
_Avoid_: Time in Force、Order Status、Fill Policy

**Hedge Leg（对冲腿）**：
为对冲同一市场中已有未对冲持仓而买入相反 Outcome Side 的 Alpha Decision；同一二元对的两条腿通过 pair_id 关联。它是新的交易意图，不是退出或取消已有订单。
_Avoid_: Exit、平仓、反向订单

**Signal Candidate（信号候选）**：
Alpha Decision 面向资格检查、发布、审计和展示形成的不可变投影。它关联原始交易意图，但不是订单路由或交易状态的事实来源。
_Avoid_: Alpha Decision、Order、Trade

**Signal Gate（信号门）**：
Signal Candidate 在发布和提交前必须通过的业务资格边界，检查市场、时间、数据新鲜度、价格、价差、到期参数和置信度。它不判断账户余额、敞口、仓位上限或最终可执行性。
_Avoid_: Risk Engine、风控引擎、撮合规则

**Rejected Signal（拒绝信号）**：
在提交前被拒绝的 Signal Candidate，以及首个失败规则、原因码和判定细节；拒绝可以发生在 Signal Gate，也可以发生在通过 Gate 之后的决策管道（如在途重复、订单映射失败）。策略本身未产生 Alpha Decision 不属于 Rejected Signal。
_Avoid_: Rejected Order、无信号

**Accepted Signal（接受信号）**：
通过 Signal Gate、可被发布并继续提交的 Signal Candidate。它不保证订单会被接受，更不代表已经成交。
_Avoid_: Filled Signal、Trade、成交

## 执行与持仓

**Order（订单）**：
交易运行时接收并跟踪的执行请求；其生命周期可经历提交、接受、部分成交、成交、取消、到期或拒绝。Order 是执行事实，不等同于发起它的 Alpha Decision 或 Signal Candidate。
_Avoid_: Signal、Trade、Position

**Fill（成交）**：
Order 中实际执行的数量与价格事实；一个 Order 可以没有 Fill，也可以产生一个或多个 Fill。
_Avoid_: Order、Signal、Settlement

**Position（持仓）**：
由已发生的 Fill 建立并由交易运行时持续管理的市场权益。报表中的持仓行只是它的只读投影。
_Avoid_: Signal、Report Position、Wallet Balance

**Exit（退出）**：
通过真实 Order 与 Fill 减少或关闭既有 Position 的交易意图与执行过程；退出原因可以是止盈、止损或达到最长持有时间。市场结算产生的 Report Result 本身不证明 Exit 已经发生。
_Avoid_: Resolution Evidence、Report Result、取消订单

## 结算与报告

**Resolution Evidence（结算证据）**：
外部来源对 Market 最终 Outcome Side 的观察。它可以支持计算验证结果，但本身不是 Fill，也不证明交易运行时中的 Position 已关闭。
_Avoid_: Settlement Fill、Position Closed、Payout

**Report Result（报告结果）**：
基于 Position、退出事实或 Resolution Evidence 得出的只读验证结果，记录 WIN、LOSS 或 VOID，以及结算价值、损益和收益率；UNKNOWN 表示尚不能确定结果，SPLIT 仅用于兼容历史数据。它不得改变 Order、Position、Portfolio 或 Account。
_Avoid_: Native Settlement、Fill、Position

**Daily Report（日报）**：
按报告日期汇总信号、订单、成交、持仓、结果和权益的可修订快照；迟到的结算事实可以产生新的 revision，而不是改写既有历史。
_Avoid_: Trading Ledger、Account、实时状态

**Reporting Projection（报告投影）**：
从交易生命周期和结算结果派生、供 Dashboard、Telegram 和审计使用的持久化只读事实。删除投影可能丢失展示历史，但不得改变任何交易状态。
_Avoid_: Trading State、Execution Ledger、恢复来源

## 研究与晋级

**Recorded Market Data（录制行情）**：
运行期间持久化的市场观察流（盘口报价、现货参照、Price to Beat、市场元数据），作为回测回放的输入。它是市场事实的只读副本，不包含订单、成交或持仓。
_Avoid_: Reporting Projection、合成数据、样本赔率

**Promotion Gate（晋级门）**：
判定一个策略参数组合能否从 lab 配置进入生产配置的研究资格边界，基于对 Recorded Market Data 的 IS/OOS 回放，检查样本量下限、OOS 正期望、参数邻域稳定性与点差敏感性。它评审策略与参数，不评审单条信号；晋级动作本身由人修改配置完成，不由工具自动执行。
_Avoid_: Signal Gate、风控、自动调参

**Promotion Report（晋级报告）**：
Promotion Gate 对一个（策略、资产、周期、参数）组合的判定产物，结论为 PASS、FAIL 或 INSUFFICIENT_DATA，并附带证据。它是研究文档与只读投影，不改变任何配置或交易状态。
_Avoid_: Daily Report、冠军参数、配置补丁

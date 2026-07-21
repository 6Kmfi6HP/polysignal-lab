# 外部发布不得拥有交易状态

Dashboard 只消费 Reporting Projection；Telegram 可以消费 Accepted Signal、Reporting Projection 或持久化投递意图，但任何发布结果都不得提交、回滚、结算或推进交易生命周期，且 Accepted Signal 不表示 Order 已被 RiskEngine 接受或已产生成交。对于需要恢复的外部发送，系统先持久化本地事实和最小 outbox intent，再以确定性幂等键发送或重试；这增加了少量交付状态，但避免不可撤回的外部消息先于本地事实，并使交付重试不会重复创建结算或报告结果。

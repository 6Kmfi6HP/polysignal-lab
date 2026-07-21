# 将持久化状态限定为报告投影

SQLite 中由原生生命周期派生的 `report_*` 数据只构成 Reporting Projection，不构成交易账本，也不得用于恢复或驱动 Order、Position、Portfolio、Account、敞口或预留资金；JSONL 和 `system_events` 是审计或 best-effort telemetry，既不保证完整，也不是恢复来源。项目选择小型 SQLite current-state projection，并将其与不可变事件历史分开，以获得可查询、可修订且幂等的报告能力；代价是维护明确的投影边界，但避免为实验室系统引入第二套执行状态或 Kafka、Redis Streams、分布式事务和通用 event-sourcing framework。

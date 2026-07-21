# Sandbox 与 live 结算只生成报告结果

在 sandbox 和 live 模式中，外部 Resolution Evidence 只生成 Report Result，不合成 Fill、`PositionClosed`、Portfolio、Account 或 Cache mutation，因为当前 Polymarket adapter 提供结果观察能力，却没有公开的 payout、redeem 或 settle authority。项目接受报告结果与 native Position 生命周期可能持续不一致，以避免伪造交易事实；backtest 仅可重放 NautilusTrader 原生 `InstrumentClose` 路径，由引擎自身完成到期撮合和状态更新。

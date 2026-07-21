# 晋级判定只来自录制行情在真实引擎中的回放

Promotion Gate 的判定只基于 Recorded Market Data 在 NautilusTrader BacktestEngine 中的回放，复用与 sandbox 完全相同的 Strategy、DecisionPipeline 与 SignalGate 代码路径，不建立第二套轻量模拟器，也不用合成数据（现货序列加赔率曲面近似）出具方向性结论，因为双实现必然漂移、合成成交模型系统性偏乐观——这正是参考实现 claw-poly 自己承认的回测失真根源。项目为此接受两个代价：参数搜索受真实引擎速度约束，只能用粗网格与少量参数；判定必须等待录制数据积累到样本量下限（时间序 70/30 切分，每个策略、资产、周期组合至少 IS 1000 / OOS 300 个已结算回合），未达标一律 INSUFFICIENT_DATA，不出方向性结论。晋级动作本身——修改生产配置——始终由人手动完成，工具链只产出 Promotion Report。

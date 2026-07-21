# 以 NautilusTrader 独占交易运行时真相

PolySignal Lab 将市场数据、Order/Fill 生命周期、Position、Portfolio、Account 与风险状态交给 NautilusTrader 独占；NautilusTrader 还拥有 sandbox/backtest matching，而 live venue 的撮合结果通过官方 adapter 进入同一运行时生命周期。PolySignal 只拥有市场业务映射、Alpha Decision、业务资格和原生订单映射；Side（UP/DOWN）与 Nautilus OrderSide（BUY/SELL）不可互换。曾经存在的本地盘口、paper matching、wallet、account 与 exposure ledger 会形成可冲突的第二套交易真相，因此不得作为备用后端进入 live、sandbox 或决策路径；项目选择单一路径和 fail-fast 边界，而不是用兼容开关保留双执行体系。

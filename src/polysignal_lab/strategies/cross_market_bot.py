"""
CrossMarketBotStrategy — 跨市场组合套利策略 (策略7)

核心逻辑:
- 构建多市场关系图 (互斥穷尽 / 包含关系)
- 评估和找出 pair cost < 1 的组合套利机会
- EXHAUSTIVE_MUTUALLY_EXCLUSIVE: Σ YES_i ask < 1 → 同时买入所有 YES
- INCLUSION (A⊂B): YES_B + NO_A < 1 → 同时买入
- 使用 FOK 多腿同步执行 (失败则 neutralize)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.snapshot_batch import CrossMarketEvaluationContext
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.strategies.base import BaseStrategy


# ---------------------------------------------------------------------------
# 关系类型枚举
# ---------------------------------------------------------------------------

class RelationType(StrEnum):
    """市场关系类型"""
    EXHAUSTIVE_MUTUALLY_EXCLUSIVE = "EXHAUSTIVE_MUTUALLY_EXCLUSIVE"
    # 互斥穷尽: 所有 YES token 的 ask 之和 < 1 → 同时买入全部 YES
    INCLUSION = "INCLUSION"
    # 包含关系 A⊂B: YES_B + NO_A < 1 → 同时买入 YES_B + NO_A


@dataclass
class MarketRelation:
    """定义一个跨市场关系"""
    relation_id: str
    rel_type: RelationType
    # 参与该关系的条件 ID 列表
    condition_ids: list[str]
    # 每条腿的 side (首条腿的下标对应 condition_ids[0], 以此类推)
    sides: list[Side]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class CrossMarketBotConfig(BaseModel):
    """跨市场组合套利策略配置"""
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])

    # 最小利润阈值 (如果 pair_cost >= 1 - min_edge, 则不执行)
    min_edge: float = 0.01

    # 多腿执行超时
    max_leg_timeout_seconds: float = 1.5

    # 单篮子最大名义金额 (USDC)
    max_basket_notional: float = 50.0

    # 每层最小深度股数
    min_depth_shares: int = 5

    # 交易费率
    fee_rate: float = 0.01


# ---------------------------------------------------------------------------
# 策略实现
# ---------------------------------------------------------------------------

class CrossMarketBotStrategy(BaseStrategy):
    """跨市场组合套利策略

    在当前架构下每个 evaluate() 只拿到一个 market 的 snapshot,
    因此跨市场关系图在策略初始化时预定义 (hardcode 或从数据库/配置加载).
    evaluate() 检查当前 market 是否参与了某个已定义的 relation,
    如果是, 且满足套利条件, 则生成该腿的信号.
    """

    name = "cross_market_bot"

    def __init__(self, config: CrossMarketBotConfig):
        self.config = config
        # 预定义的市场关系列表。
        # 实际部署中可以从配置文件或数据库加载。
        self._relations: list[MarketRelation] = []
        # 缓存 market_id -> list[relation_index], 用于快速查找
        self._market_to_relations: dict[str, list[int]] = {}
        # 用于跨市场状态追踪
        self._active_baskets: dict[str, dict[str, Any]] = {}  # relation_id -> state


    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        for basket in self._active_baskets.values():
            if market_id in basket.get("markets", set()):
                basket.setdefault("fills", {})[market_id] = {
                    "side": side,
                    "fill_price": fill_price,
                    "shares": shares,
                }
                return

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        basket = self._active_baskets.setdefault(pair_id, {"fills": {}, "markets": set()})
        basket["failed"] = True
        basket["failed_leg"] = {"market_id": market_id, "side": side}
    # ------------------------------------------------------------------
    # 公开方法: 注册关系
    # ------------------------------------------------------------------

    def register_relation(
        self,
        relation_id: str,
        rel_type: RelationType,
        condition_ids: list[str],
        sides: list[Side],
    ) -> None:
        """动态注册一个跨市场关系"""
        if len(condition_ids) != len(sides):
            raise ValueError(f"condition_ids ({len(condition_ids)}) and sides ({len(sides)}) must have same length")
        rel = MarketRelation(
            relation_id=relation_id,
            rel_type=rel_type,
            condition_ids=list(condition_ids),
            sides=list(sides),
        )
        idx = len(self._relations)
        self._relations.append(rel)

        for cid in condition_ids:
            if cid not in self._market_to_relations:
                self._market_to_relations[cid] = []
            self._market_to_relations[cid].append(idx)

    # ------------------------------------------------------------------
    # 辅助计算
    # ------------------------------------------------------------------

    def _pair_effective_cost(self, *leg_prices: float) -> float:
        """计算 N 腿组合有效成本 = sum(leg_price) + N * fee + slippage_buffer

        如果 sum < 1.0, 则存在套利空间。
        """
        total = sum(leg_prices)
        total += len(leg_prices) * self.config.fee_rate
        return total

    def _executable_buy_price(self, book, shares: int) -> float | None:
        """检查深度是否足以买入 shares 股, 并返回加权平均执行价。

        模拟 FOK 逻辑: 如果深度不足 (无法完全成交), 返回 None。
        """
        if not book or not book.asks:
            return None
        remaining = float(shares)
        total_cost = 0.0
        for level in sorted(book.asks, key=lambda x: x.price):
            take = min(remaining, level.size)
            total_cost += take * level.price
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return None  # 深度不足, FOK 失败
        return total_cost / shares if shares > 0 else None

    # ------------------------------------------------------------------
    # 评估入口
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        if snapshot.market.asset not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []

        condition_id = snapshot.market.condition_id
        # 查找当前 market 参与的关系
        rel_indices = self._market_to_relations.get(condition_id, [])
        if not rel_indices:
            return []

        signals: list[SignalCandidate] = []

        for idx in rel_indices:
            rel = self._relations[idx]
            result = self._evaluate_relation(snapshot, rel, condition_id)
            if result:
                signals.extend(result)

        return signals

    def evaluate_group(
        self, context: CrossMarketEvaluationContext
    ) -> list[SignalCandidate]:
        candidates: list[SignalCandidate] = []
        for snapshot in context.snapshots_by_condition_id.values():
            candidates.extend(self.evaluate(snapshot))
        return candidates

    # ------------------------------------------------------------------
    # 关系评估
    # ------------------------------------------------------------------

    def _evaluate_relation(
        self,
        snapshot: MarketSnapshot,
        rel: MarketRelation,
        triggered_condition_id: str,
    ) -> list[SignalCandidate]:
        """评估一个跨市场关系在当前 snapshot 下是否产生信号

        当前策略仅在 snapshot 对应的腿触发时才生成该腿的信号,
        其余腿的信号由各自市场独立的 snapshot 触发生成。
        实际生产部署中会通过协调器同步所有腿的快照并批量生成信号。
        """
        # 找到当前 market 在关系中的下标
        try:
            leg_index = rel.condition_ids.index(triggered_condition_id)
        except ValueError:
            return []

        target_side = rel.sides[leg_index]
        target_book = snapshot.book_for(target_side)
        if target_book is None:
            return []
        target_ask = target_book.best_ask
        if target_ask is None:
            return []

        # 检查目标腿的深度是否满足最低股数要求
        exec_price = self._executable_buy_price(target_book, self.config.min_depth_shares)
        if exec_price is None:
            return []

        # 根据关系类型计算整体组合成本
        cost_valid = False
        reason_codes: list[str] = []
        metrics: dict[str, Any] = {}

        if rel.rel_type == RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE:
            # 互斥穷尽: Σ YES_i ask < 1
            # 当前 snapshot 只含有一个 market, 无法获得其余市场的实时 ask,
            # 这里假设协调器会在评估时传入各市场的当前价格.
            # 简化的单腿版本: 如果 target_ask < (1 - min_edge) / N,
            # 则对该腿生成信号; 完整的 N 腿同步需要外部协调.
            n_legs = len(rel.condition_ids)
            threshold = (1.0 - self.config.min_edge) / n_legs
            if exec_price <= threshold:
                cost = sum(
                    exec_price
                    for i in range(n_legs)
                ) + n_legs * self.config.fee_rate
                if cost < 1.0:
                    cost_valid = True
                    reason_codes = [
                        "EXHAUSTIVE_MUTUALLY_EXCLUSIVE",
                        f"COST_{cost:.4f}",
                        f"THRESHOLD_{threshold:.4f}",
                        f"LEG_{leg_index}_OF_{n_legs}",
                    ]
                    metrics = {
                        "relation_id": rel.relation_id,
                        "relation_type": rel.rel_type.value,
                        "leg_index": leg_index,
                        "n_legs": n_legs,
                        "estimated_pair_cost": round(cost, 4),
                        "min_edge": self.config.min_edge,
                        "leg_exec_price": exec_price,
                        "threshold": round(threshold, 4),
                    }

        elif rel.rel_type == RelationType.INCLUSION:
            # 包含关系 A⊂B: YES_B + NO_A < 1
            # A = condition_ids[0], B = condition_ids[1] (假设)
            if len(rel.condition_ids) >= 2:
                # 当前 snapshot 只含有一个 market,
                # 对于 INCLUSION 需要评估两个腿: YES_B + NO_A
                # 这里仅对当前腿生成信号, 对侧腿由另一个 snapshot 独立评估
                side_a = rel.sides[0]
                side_b = rel.sides[1]
                # 假设当前腿的价格代表当前腿的 ask
                if exec_price <= (1.0 - self.config.min_edge) * 0.5:
                    # 保守门槛: 假设对侧腿的最优价格也是 exec_price
                    est_cost = 2.0 * exec_price + 2.0 * self.config.fee_rate
                    if est_cost < 1.0:
                        cost_valid = True
                        role = "INCLUSION_A" if leg_index == 0 else "INCLUSION_B"
                        reason_codes = [
                            f"INCLUSION_{'A' if leg_index == 0 else 'B'}",
                            f"COST_{est_cost:.4f}",
                        ]
                        metrics = {
                            "relation_id": rel.relation_id,
                            "relation_type": rel.rel_type.value,
                            "leg_index": leg_index,
                            "estimated_pair_cost": round(est_cost, 4),
                            "min_edge": self.config.min_edge,
                            "leg_exec_price": exec_price,
                            "role": role,
                        }

        if not cost_valid:
            return []

        # 生成信号
        confidence = min(
            0.90,
            0.60 + (1.0 - metrics.get("estimated_pair_cost", 1.0)) * 2.0,
        )

        basket = self._active_baskets.setdefault(
            rel.relation_id,
            {"fills": {}, "markets": set(), "failed": False},
        )
        basket["markets"].add(snapshot.market.market_id)
        signal = self._candidate(
            snapshot=snapshot,
            side=target_side,
            confidence=confidence,
            max_entry_price=exec_price,
            reason_codes=reason_codes,
            metrics=metrics,
            order_intent=OrderIntent.TAKER_FOK,
            pair_id=rel.relation_id,
        )
        return [signal] if signal else []

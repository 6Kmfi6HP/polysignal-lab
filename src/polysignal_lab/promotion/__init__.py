"""
Input: polysignal_lab.promotion.report, polysignal_lab.promotion.runner
Output: ADR 0005 promotion gate (recorded-data replay → Promotion Report)
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from polysignal_lab.promotion.report import (
    ComboStats,
    PromotionReport,
    SegmentedStats,
    Verdict,
    evaluate_verdict,
    render_promotion_markdown,
)
from polysignal_lab.promotion.runner import (
    ADR_IS_FLOOR,
    ADR_OOS_FLOOR,
    PromotionRequest,
    collect_segment_stats,
    run_promotion,
)

__all__ = [
    "ADR_IS_FLOOR",
    "ADR_OOS_FLOOR",
    "ComboStats",
    "PromotionReport",
    "PromotionRequest",
    "SegmentedStats",
    "Verdict",
    "collect_segment_stats",
    "evaluate_verdict",
    "render_promotion_markdown",
    "run_promotion",
]

"""
Input: __future__, __future__.annotations, pydantic, pydantic.BaseModel
Output: Trade
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from pydantic import BaseModel


class Trade(BaseModel):
    """A single trade event from the CLOB trade stream.

    Mirrors PolyBullLabs' Trade dataclass used in VWAP/Momentum calculations.
    """

    price: float
    size: float
    timestamp: float  # Unix timestamp in seconds

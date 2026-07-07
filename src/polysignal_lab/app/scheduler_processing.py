"""
Input: __future__, __future__.annotations, typing, typing.TYPE_CHECKING, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate
Output: evaluate_once
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from typing import TYPE_CHECKING

from polysignal_lab.domain.signal import SignalCandidate

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


async def evaluate_once(scheduler: PolySignalScheduler) -> list[SignalCandidate]:
    raise RuntimeError("Legacy scheduler evaluation disabled in Nautilus mode")

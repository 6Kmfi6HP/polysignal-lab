"""
Input: __future__, __future__.annotations, logging, polysignal_lab.utils, polysignal_lab.utils.redact_text
Output: configure_logging, RedactingFormatter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import logging

from polysignal_lab.utils import redact_text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

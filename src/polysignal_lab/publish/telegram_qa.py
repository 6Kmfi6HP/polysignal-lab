from __future__ import annotations

import argparse
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TypedDict

import anyio
import httpx

from polysignal_lab.config import TelegramConfig
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.utils import mask_secret, redact_text, utc_iso


DEFAULT_MESSAGE = (
    "[PolySignal Lab]\n"
    "Paper-only Telegram QA send. No real order was placed. "
    "No profit guarantee. Not financial advice."
)


class TelegramQaEvidence(TypedDict):
    command: str
    mode: str
    evidence_path: str
    dry_run: bool
    status: str
    message_type: str
    max_chars: int
    retry_attempts: int
    telegram_message_id: str | None
    error: str | None
    bot_token_env: str
    channel_id_env: str
    bot_token_redacted: str
    channel_id_redacted: str
    sent_at: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class TelegramQaOptions:
    live: bool
    evidence_path: Path
    message: str
    message_type: str
    max_chars: int
    retry_attempts: int


def parse_args(argv: Sequence[str] | None = None) -> TelegramQaOptions:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--evidence",
        default=".omo/evidence/telegram-real-send-redacted.json",
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--message-type", default="telegram_qa")
    parser.add_argument("--max-chars", type=int, default=4096)
    parser.add_argument("--retry-attempts", type=int, default=1)
    parsed = parser.parse_args(argv)
    return TelegramQaOptions(
        live=bool(parsed.live),
        evidence_path=Path(str(parsed.evidence)),
        message=str(parsed.message),
        message_type=str(parsed.message_type),
        max_chars=int(parsed.max_chars),
        retry_attempts=int(parsed.retry_attempts),
    )


def build_config(options: TelegramQaOptions) -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        dry_run=not options.live,
        send_signals=True,
        send_consensus_signals=False,
        send_paper_results=False,
        send_daily_report=False,
        max_message_chars=options.max_chars,
        retry_attempts=options.retry_attempts,
    )


def build_evidence(
    options: TelegramQaOptions, config: TelegramConfig, result_status: str
) -> TelegramQaEvidence:
    bot_token = os.environ.get(config.bot_token_env)
    channel_id = os.environ.get(config.channel_id_env)
    command_parts = [
        ".venv/bin/python",
        "-m",
        "polysignal_lab.publish.telegram_qa",
    ]
    if options.live:
        command_parts.append("--live")
    command_parts.extend(["--evidence", str(options.evidence_path)])
    return {
        "command": shlex.join(command_parts),
        "mode": "live" if options.live else "dry_run",
        "evidence_path": str(options.evidence_path),
        "dry_run": not options.live,
        "status": result_status,
        "message_type": options.message_type,
        "max_chars": options.max_chars,
        "retry_attempts": options.retry_attempts,
        "telegram_message_id": None,
        "error": None,
        "bot_token_env": config.bot_token_env,
        "channel_id_env": config.channel_id_env,
        "bot_token_redacted": mask_secret(bot_token),
        "channel_id_redacted": mask_secret(channel_id),
        "sent_at": None,
        "recorded_at": utc_iso(),
    }


async def run(options: TelegramQaOptions) -> int:
    config = build_config(options)
    async with httpx.AsyncClient(timeout=10.0) as client:
        publisher = TelegramPublisher(config, client=client)
        result = await publisher.send(options.message, options.message_type)
    evidence = build_evidence(options, config, result.status)
    evidence["telegram_message_id"] = result.telegram_message_id
    evidence["error"] = redact_text(result.error) if result.error else None
    evidence["sent_at"] = result.sent_at
    options.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    options.evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if result.status == "FAILED":
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return anyio.run(run, parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

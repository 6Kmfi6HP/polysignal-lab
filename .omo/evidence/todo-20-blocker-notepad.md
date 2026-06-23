# Todo 20 Blocker

Status: BLOCKED, not complete.

The mandatory real Telegram channel send cannot run until both credentials are exported into the process environment:
- TELEGRAM_BOT_TOKEN: missing
- TELEGRAM_CHANNEL_ID: missing

Verified no-credential path:
- Command: `env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/todo-20-live-unset-redacted.json`
- Exit code: 2
- Artifact: `.omo/evidence/todo-20-live-unset-redacted.json`
- Observable: `status=FAILED`, `error_code=TELEGRAM_NOT_CONFIGURED`, `message_id=missing`
- Leak check: no obvious Telegram bot-token or channel-id shaped values found in the generated evidence.

After exporting valid credentials, the operator must run exactly:

```sh
.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json
```

`.env`/`.env*` files were not read, printed, copied, modified, deleted, or inspected by this preflight executor.

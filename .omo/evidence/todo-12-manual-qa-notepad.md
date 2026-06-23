**Todo 12 Manual QA Notepad**

Real-send command for an operator with exported credentials:

```bash
export TELEGRAM_BOT_TOKEN='<bot token>'
export TELEGRAM_CHANNEL_ID='<channel id>'
.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json
```

No `.env` file is needed or read. The command writes redacted evidence with:
- publish status
- Telegram message id when sent
- redacted token/channel fields
- error when failed
- timestamp

Executed locally without credentials:

```bash
env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/todo-12-telegram-real-send-redacted.json
```

Observed result:
- Exit code: 2
- Evidence path: `.omo/evidence/todo-12-telegram-real-send-redacted.json`
- Status: `FAILED`
- Error: `TELEGRAM_NOT_CONFIGURED`
- Token/channel values: absent or redacted

Executed dry-run:

```bash
.venv/bin/python -m polysignal_lab.publish.telegram_qa --evidence .omo/evidence/todo-12-telegram-dry-run-redacted.json
```

Observed result:
- Exit code: 0
- Evidence path: `.omo/evidence/todo-12-telegram-dry-run-redacted.json`
- Status: `DRY_RUN`
- Error: null
- Token/channel values: absent or redacted

Repair verification for actual command/path traceability:

```bash
env TELEGRAM_BOT_TOKEN='123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi' TELEGRAM_CHANNEL_ID='-1001234567890' .venv/bin/python -m polysignal_lab.publish.telegram_qa --evidence .omo/evidence/todo-12-repair-temp-dry-run-redacted.json
```

Observed result:
- Exit code: 0
- Evidence path: `.omo/evidence/todo-12-repair-temp-dry-run-redacted.json`
- Recorded command: `.venv/bin/python -m polysignal_lab.publish.telegram_qa --evidence .omo/evidence/todo-12-repair-temp-dry-run-redacted.json`
- Recorded mode: `dry_run`
- Recorded `dry_run`: true
- Status: `DRY_RUN`
- Fake token/channel grep over the artifact: no matches

```bash
env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/todo-12-repair-temp-live-unset-redacted.json
```

Observed result:
- Exit code: 2
- Evidence path: `.omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
- Recorded command: `.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/todo-12-repair-temp-live-unset-redacted.json`
- Recorded mode: `live`
- Recorded `dry_run`: false
- Status: `FAILED`
- Error: `TELEGRAM_NOT_CONFIGURED`
- Fake token/channel grep over the artifact: no matches

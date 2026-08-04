# Data retention maintenance

Install the unit files on the Docker host:

```bash
sudo install -m 0644 deploy/polysignal-lab-retention.service /etc/systemd/system/
sudo install -m 0644 deploy/polysignal-lab-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polysignal-lab-retention.timer
```

The timer runs maintenance daily at 04:00. The service uses `flock` so a second
run exits instead of overlapping an existing run. Inspect recent output with:

```bash
systemctl status polysignal-lab-retention.timer
journalctl -u polysignal-lab-retention.service
```

Preview the maintenance actions without deleting or archiving files:

```bash
docker compose run --rm --no-deps -T polysignal-lab maintenance --dry-run
```

SQLite exports are stored under `archive/sqlite`, rotated JSONL under
`archive`, and runtime log archives under `archive/runtime_logs`.

Stop the main runtime before running `VACUUM` manually. The scheduled command
does not run `VACUUM` and never removes SQLite WAL or SHM files.

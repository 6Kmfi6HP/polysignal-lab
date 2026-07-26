"""Re-key .basedpyright/baseline.json after module renames.

Pure key rename: entries move with their file, nothing new is suppressed.
Idempotent — re-running after the keys are already moved is a no-op.
"""

from __future__ import annotations

import json
import pathlib

RENAMES = {
    "./src/polysignal_lab/signal_layer/gate.py": "./src/polysignal_lab/pretrade/gate.py",
    "./src/polysignal_lab/signal_layer/formatter.py": "./src/polysignal_lab/publish/message_formatter.py",
    "./tests/test_signal_layer.py": "./tests/test_pretrade_gate.py",
    "./src/polysignal_lab/app/reporting.py": "./src/polysignal_lab/app/daily_report/__init__.py",
    "./src/polysignal_lab/app/reporting_build.py": "./src/polysignal_lab/app/daily_report/build.py",
    "./src/polysignal_lab/app/reporting_equity.py": "./src/polysignal_lab/app/daily_report/equity.py",
    "./src/polysignal_lab/app/reporting_projection.py": "./src/polysignal_lab/app/daily_report/projection.py",
    "./src/polysignal_lab/app/reporting_sources.py": "./src/polysignal_lab/app/daily_report/sources.py",
    "./src/polysignal_lab/app/reporting_storage.py": "./src/polysignal_lab/app/daily_report/storage.py",
    "./src/polysignal_lab/app/reporting_types.py": "./src/polysignal_lab/app/daily_report/types.py",
    "./src/polysignal_lab/dashboard/reporting_read.py": "./src/polysignal_lab/dashboard/ports.py",
    "./src/polysignal_lab/nautilus_runtime/state.py": "./src/polysignal_lab/nautilus_runtime/strategy_state.py",
    "./src/polysignal_lab/nautilus_runtime/node_signals.py": "./src/polysignal_lab/nautilus_runtime/os_signals.py",
    "./src/polysignal_lab/nautilus_runtime/node_shared.py": "./src/polysignal_lab/nautilus_runtime/os_signals.py",
    "./src/polysignal_lab/nautilus_runtime/node_builder_components.py": "./src/polysignal_lab/nautilus_runtime/configured_markets.py",
    "./src/polysignal_lab/alpha/state.py": "./src/polysignal_lab/alpha/state_json.py",
    "./src/polysignal_lab/data/state.py": "./src/polysignal_lab/data/registries.py",
    "./src/polysignal_lab/alpha/helpers.py": "./src/polysignal_lab/alpha/decisions.py",
}

# strategy/helpers.py was split across five modules; its entries cannot be mapped.
DROP = ("./src/polysignal_lab/nautilus_runtime/strategy/helpers.py",)


def main() -> None:
    path = pathlib.Path(".basedpyright/baseline.json")
    baseline = json.loads(path.read_text())
    files = baseline["files"]

    moved = 0
    for old, new in RENAMES.items():
        if old not in files:
            continue
        files.setdefault(new, []).extend(files.pop(old))
        moved += 1
    for key in DROP:
        _ = files.pop(key, None)

    baseline["files"] = dict(sorted(files.items()))
    path.write_text(json.dumps(baseline, indent=4) + "\n")
    print(f"re-keyed {moved} file entries")


if __name__ == "__main__":
    main()

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


def test_default_package_import_does_not_require_nautilus() -> None:
    module = importlib.import_module("polysignal_lab")

    assert module is not None


def test_nautilus_is_optional_polymarket_extra_not_default_dependency() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    default_deps = data["project"]["dependencies"]
    optional_deps = data["project"]["optional-dependencies"]

    assert all("nautilus_trader" not in dep for dep in default_deps)
    assert optional_deps["nautilus"] == [
        "nautilus_trader[polymarket]==1.229.0; python_version >= '3.12'"
    ]

def test_nautilus_node_does_not_import_scheduler_compat_shadow_wallet() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/node.py").read_text()

    assert "scheduler_compat" not in source
    assert "init_scheduler_paper_components" not in source
    assert "mirror_nautilus_fill_into_scheduler" not in source
    assert "paper_fill_mirror=lambda" not in source

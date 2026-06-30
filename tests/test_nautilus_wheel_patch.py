from __future__ import annotations

import pytest

from polysignal_lab.nautilus_runtime.patch_nautilus_polymarket_autoload import NEW_BLOCK, OLD_BLOCK, patch_source


def test_patch_source_retries_batch_exception_instead_of_failing_pending_futures() -> None:
    source = f"before\n{OLD_BLOCK}\nafter\n"

    patched = patch_source(source)

    assert OLD_BLOCK not in patched
    assert NEW_BLOCK in patched
    assert "if attempt >= max_retries:" in patched


def test_patch_source_rejects_unexpected_adapter_source() -> None:
    with pytest.raises(RuntimeError, match="expected auto-load exception block"):
        _ = patch_source("old block missing")

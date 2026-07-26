from pathlib import Path


def test_custom_nautilus_exit_policy_module_is_removed() -> None:
    assert not Path("src/polysignal_lab/nautilus_runtime/exit_policy.py").exists()


def test_custom_nautilus_native_exit_module_is_removed() -> None:
    assert not Path("src/polysignal_lab/nautilus_runtime/native_exit.py").exists()

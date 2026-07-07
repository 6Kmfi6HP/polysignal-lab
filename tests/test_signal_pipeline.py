import pytest

from polysignal_lab.app.services.signal_pipeline import SignalPipeline


class _Strategy:
    name = "fake"

    def evaluate(self, snapshot):
        raise AssertionError("legacy pipeline must not evaluate strategies")


class _Gate:
    pass


class _Consensus:
    pass


def test_signal_pipeline_evaluate_snapshot_is_removed() -> None:
    pipeline = SignalPipeline([_Strategy()], _Gate(), _Consensus(), persistence=None)

    with pytest.raises(RuntimeError, match="Nautilus strategy callbacks"):
        pipeline.evaluate_snapshot(snapshot=object())

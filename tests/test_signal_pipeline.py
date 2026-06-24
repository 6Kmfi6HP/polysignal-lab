from polysignal_lab.app.services.signal_pipeline import SignalPipeline


class _Strategy:
    name = "fake"

    def evaluate(self, snapshot):
        return []


class _Gate:
    pass


class _Consensus:
    pass


def test_signal_pipeline_returns_no_candidates_for_empty_strategy_result() -> None:
    pipeline = SignalPipeline([_Strategy()], _Gate(), _Consensus(), persistence=None)

    accepted = pipeline.evaluate_snapshot(snapshot=object())

    assert accepted == []

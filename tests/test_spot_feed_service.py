"""
Input: polysignal_lab.app.services.spot_feed_service, polysignal_lab.app.services.spot_feed_service.SpotFeedService
Output: test_spot_feed_stop_delegates_to_adapter, _Feed
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from polysignal_lab.app.services.spot_feed_service import SpotFeedService


class _Feed:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def run(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


async def test_spot_feed_stop_delegates_to_adapter(settings) -> None:
    feed = _Feed()
    service = SpotFeedService(feed)

    await service.stop()

    assert feed.stopped is True

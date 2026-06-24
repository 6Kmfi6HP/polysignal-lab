from polysignal_lab.app.services.book_feed_service import BookFeedService


class _MarketData:
    async def get_books(self, token_ids):
        return []


class _Books:
    def mark_stale(self, token_id, reason):
        self.last = (token_id, reason)


async def test_book_feed_reseed_marks_missing_books_stale(settings) -> None:
    books = _Books()
    service = BookFeedService(settings.data.polymarket, _MarketData(), books)

    await service.reseed(["token-1"])

    assert books.last == ("token-1", "RECONNECT_RESEED_FAILED")

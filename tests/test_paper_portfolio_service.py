from polysignal_lab.app.services.paper_portfolio_service import PaperPortfolioService


class _Settings:
    pass


class _Wallet:
    starting_balance = 1000.0
    equity = 1000.0
    open_position_count = 0


class _Paper:
    pass


class _Persistence:
    pass


def test_paper_portfolio_service_health_reports_open_positions() -> None:
    service = PaperPortfolioService(
        settings=_Settings(),
        wallet=_Wallet(),
        paper=_Paper(),
        exits=None,
        settlement=None,
        markets=None,
        books=None,
        persistence=_Persistence(),
    )

    health = service.health()

    assert health["name"] == "paper_portfolio"
    assert health["metrics"]["open_positions"] == 0

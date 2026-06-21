from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from polysignal_lab.storage.sqlite_store import SQLiteStore


def create_dashboard_app(store: SQLiteStore) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "OK", "counts": store.counts()}

    @app.get("/api/overview")
    def overview() -> dict:
        counts = store.counts()
        latest_report = store.query_json("daily_reports", limit=1)
        return {"counts": counts, "latest_report": latest_report[0] if latest_report else None}

    @app.get("/api/signals")
    def signals(limit: int = 100) -> list[dict]:
        return store.query_json("signals", limit=min(limit, 500))

    @app.get("/api/rejected-signals")
    def rejected_signals(limit: int = 100) -> list[dict]:
        return store.query_json("rejected_signals", limit=min(limit, 500))

    @app.get("/api/positions")
    def positions(status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            return store.query_json("paper_positions", where="WHERE status=?", params=(status.upper(),), limit=min(limit, 500))
        return store.query_json("paper_positions", limit=min(limit, 500))

    @app.get("/api/trades")
    def trades(limit: int = 100) -> list[dict]:
        return store.query_json("paper_trade_results", limit=min(limit, 500))

    @app.get("/api/leaderboard")
    def leaderboard(limit: int = 100) -> dict:
        reports = store.query_json("daily_reports", limit=min(limit, 500))
        merged: dict[str, dict] = {}
        for report in reports:
            for strategy, row in report.get("strategy_breakdown", {}).items():
                entry = merged.setdefault(strategy, {"strategy": strategy, "closed_positions": 0, "win_count": 0, "loss_count": 0, "total_pnl_usdc": 0.0})
                entry["closed_positions"] += row.get("closed_positions", 0)
                entry["win_count"] += row.get("win_count", 0)
                entry["loss_count"] += row.get("loss_count", 0)
                entry["total_pnl_usdc"] += row.get("total_pnl_usdc", 0.0)
        for entry in merged.values():
            denom = entry["win_count"] + entry["loss_count"]
            entry["win_rate"] = entry["win_count"] / denom if denom else 0.0
        return {"leaderboard": sorted(merged.values(), key=lambda x: x["total_pnl_usdc"], reverse=True)}

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        counts = store.counts()
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in counts.items())
        return f"""
        <html><head><title>PolySignal Lab</title></head>
        <body>
          <h1>PolySignal Lab Dashboard</h1>
          <p>Read-only dashboard. No market execution endpoints exist.</p>
          <table border='1' cellpadding='6'><tr><th>Table</th><th>Rows</th></tr>{rows}</table>
          <ul>
            <li><a href='/api/overview'>Overview JSON</a></li>
            <li><a href='/api/signals'>Signals JSON</a></li>
            <li><a href='/api/positions'>Positions JSON</a></li>
            <li><a href='/api/trades'>Trades JSON</a></li>
            <li><a href='/api/leaderboard'>Strategy Leaderboard JSON</a></li>
          </ul>
        </body></html>
        """

    return app

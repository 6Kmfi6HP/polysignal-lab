from __future__ import annotations

from html import escape
from typing import TypeAlias

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from polysignal_lab.storage.sqlite_store import SQLiteStore

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def _text(value: JsonValue) -> str:
    return escape(str(value))


def _fmt_money(value: JsonValue) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "0.00 USDC"
    return f"{amount:,.2f} USDC"


def _fmt_rate(value: JsonValue) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    return f"{rate * 100:.1f}%"


def create_dashboard_app(store: SQLiteStore) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    @app.get("/health", response_model=None)
    def health() -> dict[str, JsonValue]:
        return {"status": "OK", "counts": store.counts()}

    @app.get("/api/overview", response_model=None)
    def overview() -> dict[str, JsonValue]:
        counts = store.counts()
        latest_report = store.restore_daily_reports(limit=1)
        return {"counts": counts, "latest_report": latest_report[0] if latest_report else None}

    @app.get("/api/signals", response_model=None)
    def signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("signals", limit=_bounded_limit(limit))

    @app.get("/api/rejected-signals", response_model=None)
    def rejected_signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("rejected_signals", limit=_bounded_limit(limit))

    @app.get("/api/positions", response_model=None)
    def positions(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "paper_positions",
                where="WHERE status=?",
                params=(status.upper(),),
                limit=_bounded_limit(limit),
            )
        return store.query_json("paper_positions", limit=_bounded_limit(limit))

    @app.get("/api/trades", response_model=None)
    def trades(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("paper_trade_results", limit=_bounded_limit(limit))

    @app.get("/api/leaderboard", response_model=None)
    def leaderboard(limit: int = 100) -> dict[str, JsonValue]:
        return {"leaderboard": store.restore_strategy_leaderboard(limit=_bounded_limit(limit))}

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        counts = store.counts()
        latest_report = store.restore_daily_reports(limit=1)
        signals = store.query_json("signals", limit=5)
        trades = store.query_json("paper_trade_results", limit=5)
        leaderboard_rows = store.restore_strategy_leaderboard(limit=5)
        report = latest_report[0] if latest_report else None
        rows = "".join(
            f"<tr><th scope='row'>{_text(table)}</th><td>{count}</td></tr>"
            for table, count in counts.items()
        )
        signal_rows = "".join(
            "<tr>"
            f"<td><code>{_text(row.get('signal_id', ''))}</code></td>"
            f"<td>{_text(row.get('strategy', ''))}</td>"
            f"<td>{_text(row.get('asset', ''))} {_text(row.get('timeframe', ''))}</td>"
            f"<td>{_text(row.get('side', ''))}</td>"
            f"<td>{_fmt_rate(row.get('confidence', 0.0))}</td>"
            "</tr>"
            for row in signals
        ) or "<tr><td colspan='5' class='muted'>No stored signals yet.</td></tr>"
        trade_rows = "".join(
            "<tr>"
            f"<td><code>{_text(row.get('paper_trade_id', ''))}</code></td>"
            f"<td>{_text(row.get('strategy', ''))}</td>"
            f"<td>{_text(row.get('result', ''))}</td>"
            f"<td>{_fmt_money(row.get('pnl_usdc', 0.0))}</td>"
            f"<td>{_fmt_rate(row.get('roi', 0.0))}</td>"
            "</tr>"
            for row in trades
        ) or "<tr><td colspan='5' class='muted'>No closed paper trades yet.</td></tr>"
        leaderboard_preview = "".join(
            "<tr>"
            f"<td><code>{_text(row.get('strategy', ''))}</code></td>"
            f"<td>{_text(row.get('closed_positions', 0))}</td>"
            f"<td>{_fmt_rate(row.get('win_rate', 0.0))}</td>"
            f"<td>{_fmt_money(row.get('total_pnl_usdc', 0.0))}</td>"
            "</tr>"
            for row in leaderboard_rows
        ) or "<tr><td colspan='4' class='muted'>No stored report rows yet.</td></tr>"
        report_summary = (
            f"<dl class='summary'><div><dt>Report date</dt><dd>{_text(report.get('report_date', ''))}</dd></div>"
            f"<div><dt>Total signals</dt><dd>{_text(report.get('total_signals', 0))}</dd></div>"
            f"<div><dt>Closed positions</dt><dd>{_text(report.get('closed_positions', 0))}</dd></div>"
            f"<div><dt>Paper PnL</dt><dd>{_fmt_money(report.get('total_pnl_usdc', 0.0))}</dd></div></dl>"
            if report
            else "<p class='muted'>No daily report has been stored yet.</p>"
        )
        return f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <meta name="description" content="Read-only PolySignal Lab operations dashboard backed by stored SQLite rows.">
          <title>PolySignal Lab Dashboard</title>
          <style>
            :root {{
              --surface-primary: #f7f4ed;
              --surface-secondary: #efebe1;
              --surface-elevated: #fffdf8;
              --text-primary: #1f1c18;
              --text-secondary: #625b50;
              --text-tertiary: #8a8172;
              --border-default: #d9d0c0;
              --border-subtle: #e9e1d4;
              --accent-primary: #8f5b12;
              --accent-hover: #6e430b;
              --status-success: #277747;
              --status-warning: #9a650d;
              --space-1: 4px;
              --space-2: 8px;
              --space-3: 12px;
              --space-4: 16px;
              --space-5: 20px;
              --space-6: 24px;
              --space-8: 32px;
              --radius-sm: 4px;
              --radius-md: 8px;
            }}
            * {{ box-sizing: border-box; }}
            body {{
              margin: 0;
              background: var(--surface-primary);
              color: var(--text-primary);
              font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              font-variant-numeric: tabular-nums;
            }}
            a {{ color: var(--accent-primary); text-decoration-thickness: 1px; text-underline-offset: var(--space-1); transition: color 120ms ease-out; }}
            a:hover {{ color: var(--accent-hover); }}
            a:focus-visible {{ outline: 2px solid var(--accent-primary); outline-offset: var(--space-1); border-radius: var(--radius-sm); }}
            .skip {{ position: absolute; left: var(--space-4); top: var(--space-2); transform: translateY(-200%); background: var(--surface-elevated); padding: var(--space-2); }}
            .skip:focus {{ transform: translateY(0); }}
            header, main, footer {{ max-width: 1180px; margin: 0 auto; padding: var(--space-5); }}
            header {{ display: grid; gap: var(--space-4); border-bottom: 1px solid var(--border-default); }}
            h1 {{ margin: 0; font-size: 1.75rem; line-height: 1.2; font-weight: 650; letter-spacing: 0; }}
            h2 {{ margin: 0 0 var(--space-3); font-size: 1.125rem; line-height: 1.3; font-weight: 650; letter-spacing: 0; }}
            p {{ margin: 0; color: var(--text-secondary); max-width: 72ch; }}
            nav ul {{ display: flex; flex-wrap: wrap; gap: var(--space-2); list-style: none; margin: 0; padding: 0; }}
            nav a {{ display: inline-block; padding: var(--space-1) var(--space-2); }}
            main {{ display: grid; gap: var(--space-6); }}
            .status {{ display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; color: var(--text-secondary); }}
            .badge {{ border: 1px solid var(--border-default); border-radius: var(--radius-sm); color: var(--status-warning); padding: var(--space-1) var(--space-2); background: var(--surface-elevated); }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-3); }}
            article, section.panel {{ background: var(--surface-elevated); border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: var(--space-4); }}
            article h2 {{ color: var(--text-secondary); font-size: 0.75rem; line-height: 1.35; margin: 0 0 var(--space-2); }}
            article strong {{ display: block; font-size: 1.125rem; line-height: 1.3; }}
            .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-3); margin: 0; }}
            dt {{ color: var(--text-secondary); font-size: 0.75rem; }}
            dd {{ margin: 0; font-weight: 650; }}
            .table-wrap {{ overflow-x: auto; border: 1px solid var(--border-default); border-radius: var(--radius-sm); background: var(--surface-elevated); }}
            table {{ width: 100%; border-collapse: collapse; min-width: 560px; }}
            caption {{ padding: var(--space-2) var(--space-3); text-align: left; color: var(--text-secondary); font-weight: 650; }}
            th, td {{ padding: var(--space-2) var(--space-3); border-top: 1px solid var(--border-subtle); text-align: left; vertical-align: top; font-size: 0.8125rem; }}
            thead th {{ background: var(--surface-secondary); color: var(--text-secondary); }}
            tbody tr:hover {{ background: var(--surface-secondary); }}
            code {{ font: 500 0.8125rem/1.45 "SFMono-Regular", Consolas, "Liberation Mono", monospace; }}
            .muted {{ color: var(--text-tertiary); }}
            footer {{ color: var(--text-tertiary); border-top: 1px solid var(--border-subtle); }}
            @media (max-width: 720px) {{
              header, main, footer {{ padding: var(--space-4); }}
              table {{ min-width: 480px; }}
            }}
          </style>
        </head>
        <body>
          <a class="skip" href="#content">Skip to dashboard content</a>
          <header>
            <div>
              <h1>PolySignal Lab Dashboard</h1>
              <p>Paper-only read model backed by persisted SQLite rows. No execution, admin, cancel, redeem, or order placement controls are exposed.</p>
            </div>
            <nav aria-label="Read-only API endpoints">
              <ul>
                <li><a href="/api/overview">Overview JSON</a></li>
                <li><a href="/api/signals">Signals JSON</a></li>
                <li><a href="/api/rejected-signals">Rejected JSON</a></li>
                <li><a href="/api/positions">Positions JSON</a></li>
                <li><a href="/api/trades">Trades JSON</a></li>
                <li><a href="/api/leaderboard">Leaderboard JSON</a></li>
              </ul>
            </nav>
            <div class="status" role="status"><span class="badge">Read-only</span><span>Storage health is served from <code>/health</code>.</span></div>
          </header>
          <main id="content">
            <section aria-labelledby="counts-title">
              <h2 id="counts-title">Stored row counts</h2>
              <div class="grid">
                <article><h2>Signals</h2><strong>{counts["signals"]}</strong></article>
                <article><h2>Rejected</h2><strong>{counts["rejected_signals"]}</strong></article>
                <article><h2>Positions</h2><strong>{counts["paper_positions"]}</strong></article>
                <article><h2>Trades</h2><strong>{counts["paper_trade_results"]}</strong></article>
                <article><h2>Reports</h2><strong>{counts["daily_reports"]}</strong></article>
              </div>
            </section>
            <section class="panel" aria-labelledby="report-title">
              <h2 id="report-title">Latest stored daily report</h2>
              {report_summary}
            </section>
            <section class="panel" aria-labelledby="all-counts-title">
              <h2 id="all-counts-title">Audit stream inventory</h2>
              <div class="table-wrap"><table><caption>SQLite row counts by PRD audit stream</caption><tbody>{rows}</tbody></table></div>
            </section>
            <section class="panel" aria-labelledby="signals-title">
              <h2 id="signals-title">Recent stored signals</h2>
              <div class="table-wrap"><table><caption>Last five signal payload rows</caption><thead><tr><th>Signal</th><th>Strategy</th><th>Market</th><th>Side</th><th>Confidence</th></tr></thead><tbody>{signal_rows}</tbody></table></div>
            </section>
            <section class="panel" aria-labelledby="trades-title">
              <h2 id="trades-title">Recent stored paper trades</h2>
              <div class="table-wrap"><table><caption>Last five paper trade result payload rows</caption><thead><tr><th>Trade</th><th>Strategy</th><th>Result</th><th>PnL</th><th>ROI</th></tr></thead><tbody>{trade_rows}</tbody></table></div>
            </section>
            <section class="panel" aria-labelledby="leaderboard-title">
              <h2 id="leaderboard-title">Strategy leaderboard preview</h2>
              <p><a href="/api/leaderboard">Open full leaderboard JSON</a></p>
              <div class="table-wrap"><table><caption>Leaderboard restored from stored daily report rows</caption><thead><tr><th>Strategy</th><th>Closed</th><th>Win rate</th><th>Total PnL</th></tr></thead><tbody>{leaderboard_preview}</tbody></table></div>
            </section>
          </main>
          <footer>Read-only FastAPI dashboard. Write methods return framework method errors.</footer>
        </body></html>
        """

    return app

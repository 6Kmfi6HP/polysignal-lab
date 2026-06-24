from __future__ import annotations

from html import escape
from typing import TypeAlias

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from polysignal_lab.storage.sqlite_store import SQLiteStore

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

CALIBRATION_MIN_SAMPLE_SIZE = 30


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


def _as_int(value: JsonValue) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: JsonValue) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _health_payload(store: SQLiteStore) -> dict[str, JsonValue]:
    counts = store.counts()
    recent_system_events = store.query_json(
        "system_events",
        where="ORDER BY created_at DESC, rowid DESC",
        limit=10,
    )
    snapshot = store.restore_latest_system_event("health_snapshot")
    if isinstance(snapshot, dict):
        return {
            "status": str(snapshot.get("status", "degraded")).lower(),
            "generated_at": snapshot.get("generated_at") or snapshot.get("created_at"),
            "components": snapshot.get("components", []),
            "counts": counts,
            "recent_system_events": recent_system_events,
        }
    return {
        "status": "ok",
        "generated_at": None,
        "components": [
            {
                "name": "sqlite_storage",
                "status": "ok",
                "last_success_at": None,
                "last_error_at": None,
                "last_error": None,
                "metrics": {"row_counts_available": True},
            }
        ],
        "counts": counts,
        "recent_system_events": recent_system_events,
    }


def _calibration_from_reports(reports: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    merged: dict[str, JsonValue] = {}
    average_weighted_sum: dict[str, dict[str, float]] = {}
    average_sample_size: dict[str, dict[str, int]] = {}
    count_keys = ("sample_size", "wins", "losses")
    for report in reports:
        rows = report.get("calibration_breakdown", {})
        if not isinstance(rows, dict):
            continue
        for bucket, raw_row in rows.items():
            if not isinstance(raw_row, dict):
                merged[bucket] = raw_row
                continue
            row = raw_row
            entry = merged.get(bucket)
            if not isinstance(entry, dict):
                entry = {
                    key: value
                    for key, value in row.items()
                    if key not in count_keys and not key.startswith("average_")
                }
                merged[bucket] = entry
            sample_size = _as_int(row.get("sample_size"))
            for key in count_keys:
                entry[key] = _as_int(entry.get(key)) + _as_int(row.get(key))
            for key, value in row.items():
                if key.startswith("average_"):
                    weighted_sum = average_weighted_sum.setdefault(bucket, {})
                    weighted_count = average_sample_size.setdefault(bucket, {})
                    weighted_sum[key] = weighted_sum.get(key, 0.0) + (
                        _as_float(value) * sample_size
                    )
                    weighted_count[key] = weighted_count.get(key, 0) + sample_size
    for bucket, entry in merged.items():
        if isinstance(entry, dict):
            sample_size = _as_int(entry.get("sample_size"))
            entry["calibration_status"] = (
                "calibrated"
                if sample_size >= CALIBRATION_MIN_SAMPLE_SIZE
                else "insufficient_data"
            )
            for key, weighted_sum in average_weighted_sum.get(bucket, {}).items():
                divisor = average_sample_size.get(bucket, {}).get(key, 0)
                entry[key] = weighted_sum / divisor if divisor else 0.0
    return merged


def create_dashboard_app(store: SQLiteStore) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    def strategy_status_rows(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "strategy_status",
            where="ORDER BY created_at ASC",
            limit=_bounded_limit(limit),
        )


    @app.get("/health", response_model=None)
    def health() -> dict[str, JsonValue]:
        return _health_payload(store)

    @app.get("/api/overview", response_model=None)
    def overview() -> dict[str, JsonValue]:
        counts = store.counts()
        latest_report = store.restore_daily_reports(limit=1)
        report = latest_report[0] if latest_report else None
        return {
            "counts": counts,
            "latest_report": report,
            "calibration_breakdown": (
                report.get("calibration_breakdown", {}) if report else {}
            ),
            "strategy_status": strategy_status_rows(),
        }

    @app.get("/api/signals", response_model=None)
    def signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("signals", limit=_bounded_limit(limit))

    @app.get("/api/rejected-signals", response_model=None)
    def rejected_signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("rejected_signals", limit=_bounded_limit(limit))

    @app.get("/api/strategy-status", response_model=None)
    def strategy_status(limit: int = 100) -> list[dict[str, JsonValue]]:
        return strategy_status_rows(limit)

    @app.get("/api/paper-orders", response_model=None)
    def paper_orders(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "paper_orders",
                where="WHERE status=?",
                params=(status.upper(),),
                limit=_bounded_limit(limit),
            )
        return store.query_json("paper_orders", limit=_bounded_limit(limit))

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
        report_limit = _bounded_limit(limit)
        reports = store.restore_daily_reports(limit=report_limit)
        return {
            "leaderboard": store.restore_strategy_leaderboard(limit=report_limit),
            "calibration_breakdown": _calibration_from_reports(reports),
        }

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
        reject_reason_rows = ""
        if report:
            rejects = report.get("paper_rejects_by_reason", {})
            if isinstance(rejects, dict) and rejects:
                reject_reason_rows = "".join(
                    f"<li><code>{_text(reason)}</code>: {_text(count)}</li>"
                    for reason, count in sorted(rejects.items())
                )
        execution_summary = (
            f"<div><dt>Paper fills</dt><dd>{_text(report.get('paper_fills', 0))}</dd></div>"
            f"<div><dt>Paper rejects</dt><dd>{_text(report.get('rejected_paper_orders', 0))}</dd></div>"
            f"<div><dt>Avg exec lag</dt><dd>{_text(report.get('average_execution_staleness_ms', 'n/a'))} ms</dd></div>"
            if report
            else ""
        )
        reject_summary = (
            f"<div><dt>Reject reasons</dt><dd><ul>{reject_reason_rows}</ul></dd></div>"
            if reject_reason_rows
            else ""
        )
        report_summary = (
            f"<dl class='summary'><div><dt>Report date</dt><dd>{_text(report.get('report_date', ''))}</dd></div>"
            f"<div><dt>Total signals</dt><dd>{_text(report.get('total_signals', 0))}</dd></div>"
            f"<div><dt>Closed positions</dt><dd>{_text(report.get('closed_positions', 0))}</dd></div>"
            f"<div><dt>Paper PnL</dt><dd>{_fmt_money(report.get('total_pnl_usdc', 0.0))}</dd></div>"
            f"{execution_summary}{reject_summary}</dl>"
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
                <li><a href="/api/paper-orders">Paper Orders JSON</a></li>
                <li><a href="/api/positions">Positions JSON</a></li>
                <li><a href="/api/trades">Trades JSON</a></li>
                <li><a href="/api/leaderboard">Leaderboard JSON</a></li>
                <li><a href="/api/strategy-status">Strategy Status JSON</a></li>
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

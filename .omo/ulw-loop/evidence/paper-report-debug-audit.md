# Paper report split debugging audit

Runtime snapshot:
- python: Python 3.14.5
- uv: uv 0.11.16 (x86_64-unknown-linux-gnu)
- git head: 3ef19dc

Hypotheses and observed evidence:
1. H1: report.py split broke public reporting behavior. Evidence: paper-report-focused-regression.txt and paper-report-full-pytest.txt exit 0; focused reporting/storage/settlement surface passed. Status: refuted.
2. H2: report.py still violates code quality gate via object annotations or file size. Evidence: paper-report-broad-no-excuse.txt says no violations in 13 file(s); paper-report-loc-after.txt lists report.py 217 and report_helpers.py 140. Status: refuted.
3. H3: split introduced stale active-code imports or protected reference drift. Evidence: basedpyright evidence ends 0 errors; paper-report-refs-check.txt says no protected refs/docs/nautilus_reference changes. Status: refuted.

Silent-failure scan:

Cleanup: no debugger, tmux, server, browser, container, or debug port was started for this audit.

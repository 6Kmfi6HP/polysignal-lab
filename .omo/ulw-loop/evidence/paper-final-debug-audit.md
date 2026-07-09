# Paper final debugging audit

Runtime snapshot:
- python: Python 3.14.5
- uv: uv 0.11.16 (x86_64-unknown-linux-gnu)
- git head: 3ef19dc

Hypotheses and observed evidence:
1. H1: Python bool coercion still fabricates non-zero money/size. Evidence: paper-bool-money-red.txt, paper-report-boundaries-red.txt, and paper-numeric-bool-red.txt failed before fixes; paper-bool-money-green.txt, paper-report-boundaries-green.txt, and paper-final-focused-pytest.txt passed after bool rejection. Status: refuted after fix.
2. H2: concept split broke reporting imports or behavior. Evidence: paper-final-import-rg.txt shows active imports use report_rejections and no report_helpers; paper-final-focused-pytest.txt passed. Status: refuted.
3. H3: storage restore still accepts invalid closed-position/wallet payloads. Evidence: paper-storage-closed-wallet-red.txt failed before fixes; paper-storage-closed-wallet-green.txt and paper-final-focused-pytest.txt passed after rejecting zero closed-position money and malformed wallet snapshot JSON. Status: refuted after fix.
4. H4: valid JSON hostile wallet/daily report payloads and non-finite report numbers can fabricate money or crash reporting. Evidence: paper-final-current-security-review.md found the gaps; new focused tests in test_paper_report_boundaries.py and test_storage_restore.py pass in paper-final-focused-pytest.txt after finite numeric filtering, wallet/daily report semantic restore filtering, and terminal timestamp fail-closed handling. Status: refuted after fix.
5. H5: incomplete closed position events can restore without side, money fields, or timestamps. Evidence: paper-closed-position-state-red.txt reproduced the leak; paper-closed-position-state-green.txt and paper-final-security-probe.txt show closed_positions [] after applying the same semantic state requirements to closed events. Status: refuted after fix.
6. H6: valid JSON trade-result details with nonnumeric confidence can crash report calibration. Evidence: paper-confidence-bad-red.txt reproduced the ValueError; paper-confidence-bad-green.txt and paper-final-security-probe.txt show confidence_bucket low and report calibration succeeds. Status: refuted after fix.
7. H7: huge integer persisted JSON counts can raise OverflowError in restore validators. Evidence: paper-wallet-overflow-red.txt reproduced the wallet restore crash; paper-wallet-overflow-green.txt and paper-final-security-probe.txt show wallet_restore None after count validation rejects unsafe counts. Status: refuted after fix.
8. H8: contradictory position lifecycle state can restore as both open and closed. Evidence: paper-position-conflict-red.txt reproduced the duplicate restore; paper-position-conflict-green.txt and paper-final-security-probe.txt show open_positions [] and closed_positions [] after explicit state contradiction rejection. Status: refuted after fix.
9. H9: final changes left code-quality/protected-path drift. Evidence: paper-final-no-excuse.txt no violations in 18 files; paper-final-refs-check.txt protected paths clean; paper-final-full-pytest.txt passed; paper-final-compileall.txt exit=0. Status: refuted.

Silent-failure scan:

Cleanup: no debugger, tmux, server, browser, container, or debug port was started for this audit.

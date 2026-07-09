# Manual QA Verdict

verdict: PASS

manualQa:
  surfaceEvidence:
    - scenarioId: S1-focused-smoke
      criterionRef: C1 focused smoke pytest
      surface: CLI pytest
      exactInvocation: `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q`
      verdict: PASS
      artifactRefs: [A1]
    - scenarioId: S2-required-artifacts
      criterionRef: C2 required artifacts non-empty
      surface: filesystem artifact integrity check
      exactInvocation: `test -s` loop for the nine required .omo/ulw-loop/evidence/paper-final-* files
      verdict: PASS
      artifactRefs: [A2]
    - scenarioId: S3-protected-subset
      criterionRef: C3 corrected protected subset untouched
      surface: git working tree
      exactInvocation: `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference`
      verdict: PASS
      artifactRefs: [A3]
    - scenarioId: S4-cleanup
      criterionRef: C4 QA cleanup receipt
      surface: shell resource receipt
      exactInvocation: `jobs -pr; tmux ls; docker ps --format ...` plus no-spawn receipt
      verdict: PASS
      artifactRefs: [A4]
  adversarialCases:
    - scenarioId: A1-focused-regression
      criterionRef: C1
      adversarialClass: focused test regression or collection failure
      expectedBehavior: pytest exits 0 only when all selected paper/reporting/storage tests pass
      verdict: PASS
      artifactRefs: [A1]
    - scenarioId: A2-missing-empty-prior-evidence
      criterionRef: C2
      adversarialClass: required artifact missing or zero bytes
      expectedBehavior: any missing or empty required artifact fails the gate
      verdict: PASS
      artifactRefs: [A2]
    - scenarioId: A3-protected-path-drift
      criterionRef: C3
      adversarialClass: dirty protected refs path
      expectedBehavior: any status or diff under refs, @refs, docs/nautilus_reference fails the gate
      verdict: PASS
      artifactRefs: [A3]
    - scenarioId: A4-leftover-qa-resource
      criterionRef: C4
      adversarialClass: uncleaned server/browser/tmux/container/port from QA
      expectedBehavior: no QA-spawned long-lived resource remains after execution
      verdict: PASS
      artifactRefs: [A4]
  artifactRefs:
    - id: A1
      kind: command transcript
      description: focused pytest smoke output with exit code
      path: .omo/evidence/paper-final-current-qa-final/focused-smoke-pytest.txt
    - id: A2
      kind: command transcript
      description: required prior artifact non-empty check
      path: .omo/evidence/paper-final-current-qa-final/required-artifacts.txt
    - id: A3
      kind: command transcript
      description: protected subset git status and diff output
      path: .omo/evidence/paper-final-current-qa-final/protected-subset.txt
    - id: A4
      kind: cleanup receipt
      description: no server/browser/tmux/container/port spawned by this QA run
      path: .omo/evidence/paper-final-current-qa-final/cleanup-receipt.txt
    - id: A5
      kind: verdict
      description: manual QA matrix and PASS/FAIL verdict
      path: .omo/evidence/paper-final-current-qa-final/manual-qa-verdict.md

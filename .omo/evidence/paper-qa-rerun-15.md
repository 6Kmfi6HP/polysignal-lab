# Paper QA Rerun 15

verdict: PASS

Scope: `/home/debian/polysignal-lab`

manualQa:
  surfaceEvidence:
    - scenarioId: C1
      criterionRef: required artifacts non-empty
      surface: CLI/data artifact inventory
      exactInvocation: `for f in <required evidence files>; do test -s "$f" && wc -c "$f"; done`
      verdict: PASS
      artifactRefs: [A1]
    - scenarioId: C2
      criterionRef: red/green proofs, LOC ceiling, regressions, diff, refs
      surface: CLI/data evidence verification
      exactInvocation: `awk pure LOC over split files; grep required RED/GREEN/pass markers in .omo/ulw-loop/evidence/*.txt`
      verdict: PASS
      artifactRefs: [A2, A3]
    - scenarioId: C3
      criterionRef: final QA deliverable exists
      surface: filesystem report validation
      exactInvocation: `test -s .omo/evidence/paper-qa-rerun-15.md && rg 'manualQa|verdict: PASS' .omo/evidence/paper-qa-rerun-15.md`
      verdict: PASS
      artifactRefs: [A4]

  adversarialCases:
    - scenarioId: A-C1
      criterionRef: required artifacts non-empty
      adversarialClass: missing or empty evidence artifact
      expectedBehavior: verification fails if any required artifact is absent or zero bytes
      verdict: PASS
      artifactRefs: [A1]
    - scenarioId: A-C2
      criterionRef: red/green proofs
      adversarialClass: missing RED or GREEN proof for callable-cache, timestamp, or exit_mode
      expectedBehavior: verification fails unless each fix has both a failing RED artifact and passing GREEN artifact
      verdict: PASS
      artifactRefs: [A2]
    - scenarioId: A-C3
      criterionRef: split file LOC ceiling
      adversarialClass: split file at or above 250 pure LOC
      expectedBehavior: verification fails if any split file has pure LOC >= 250
      verdict: PASS
      artifactRefs: [A3]
    - scenarioId: A-C4
      criterionRef: focused/full regressions
      adversarialClass: missing passing pytest or basedpyright marker
      expectedBehavior: verification fails unless focused pytest, full pytest, and basedpyright report pass/no-error markers
      verdict: PASS
      artifactRefs: [A2]
    - scenarioId: A-C5
      criterionRef: diff/refs pass
      adversarialClass: whitespace errors or protected refs/docs changes
      expectedBehavior: verification fails unless diff check reports pass and refs check artifact is present
      verdict: PASS
      artifactRefs: [A2]

  artifactRefs:
    - id: A1
      kind: command transcript
      description: required evidence file inventory with byte counts and PASS verdict
      path: `.omo/evidence/paper-qa-rerun-15/artifact-inventory.txt`
    - id: A2
      kind: command transcript
      description: marker verification for RED/GREEN proofs, regressions, basedpyright, diff, refs, and LOC verdict
      path: `.omo/evidence/paper-qa-rerun-15/verification-transcript.txt`
    - id: A3
      kind: command transcript
      description: current pure LOC counts for split paper/scheduler files; all below 250
      path: `.omo/evidence/paper-qa-rerun-15/loc-details.txt`
    - id: A4
      kind: command transcript
      description: final report non-empty/content validation
      path: `.omo/evidence/paper-qa-rerun-15/deliverable-check.txt`

Observed evidence summary:
- All 13 requested `.omo/ulw-loop/evidence/` artifacts are non-empty.
- RED/GREEN proof exists for `exit_mode`, callable-cache, and timestamp restore handling.
- Current split pure LOC counts are 33, 57, 81, 236, 94, 171, and 144; all are under 250.
- Focused pytest, full pytest, basedpyright, diff check, and refs check artifacts report passing/no-error markers.

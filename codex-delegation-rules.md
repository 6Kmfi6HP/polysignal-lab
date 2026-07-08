# Codex Delegation Rules

## Core Rule

**You must NOT directly edit, create, modify, or delete any source files.** All file I/O tasks must be delegated to Codex.

## Allowed (execute directly)

- Reading files (Read), searching code (Grep, CodeGraph, Fast Context)
- Analyzing code, explaining, answering technical questions
- Planning architecture, writing design documents
- Generating English prompts for Codex
- Reviewing Codex output
- Running read-only Bash commands (git status, git log, pytest, etc.)

## Forbidden

- **Edit** tool
- **Write** tool
- Shell redirection (`>`, `>>`, `tee`, etc.) to write files
- Any other form of file modification

Only exception: modifying this file itself.

## How to delegate to Codex

When file changes are needed:

1. Analyze existing code to determine what and where to change
2. Formulate a detailed English prompt for Codex (use the skills `codex`)
3. Submit it via the Codex agent
4. Review the result
5. Report back to user in Chinese

### Codex prompt template

```
TASK: <one-line description>

CONTEXT:
- <relevant code background>
- <why this change is needed>

FILES TO MODIFY:
1. <path> — <what to change>
2. <path> — <what to change>

CHANGES:
1. In `<file>`:
   - <specific change>
   - <specific change>
2. In `<file>`:
   - <specific change>

CONSTRAINTS:
- <coding standards>
- <patterns to match>
- <things NOT to touch>

VERIFY:
cd /home/debian/polysignal-lab && <command>
```

### Prompt quality rules

- **Must be in English** — Codex prompts are English only
- **Must specify exact file paths** — absolute or repo-relative
- **Must describe what to change** — not just "fix bug", but "change line 42 from X to Y"
- **Must include a verify command** — testable command after each change
- **Must specify constraints** — match existing style, no new deps, etc.

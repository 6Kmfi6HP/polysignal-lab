# Welcome to PolySignal Lab

## How We Use Claude

Based on 6Kmfi6HP's usage over the last 30 days:

**Work Type Breakdown:**
  _No session data available for the last 30 days._

**Top Skills & Commands:**
  _No session data available for the last 30 days._

**Top MCP Servers:**
  _No session data available for the last 30 days._

## Your Setup Checklist

### Codebases
- [x] [polysignal-lab](https://github.com/6kmfi6hp/polysignal-lab) — Polymarket short-cycle signal and Nautilus-backed paper trading validation system. Python project with NautilusTrader integration, deployed via Docker.

### MCP Servers to Activate
- [x] **CodeGraph** — Code intelligence over an indexed knowledge graph. Pre-computed symbol lookup so you don't grep/read blindly. Already wired as a project hook (runs automatically on every prompt). No setup needed.
- [ ] **Fast Context** — Semantic code search across the workspace. Use before manual search/read loops. Requires a Windsurf installation on this machine. **Not configured** (no Windsurf found). CodeGraph covers most needs — can skip unless you specifically want semantic search.

### Environment
- [x] **Python venv** — `.venv/` exists with dependencies installed (`pip install -e '.[dev]'`)
- [x] **Docker** — `polysignal-lab` container is running and healthy
- [x] **Test suite** — `uv run pytest -q` passes on current `main`.

### Skills to Know About
- **`/superpowers`** — The Superpowers plugin is the team's core workflow toolkit. Includes brainstorming, plan writing, subagent-driven development, systematic debugging, code review, test-driven development, and verification-before-completion. **Always invoke a skill before starting any task** — the CLAUDE.md rules (especially "think before you code" and "goal-driven execution") map directly to Superpowers skills like brainstorming and writing-plans.
- **`/code-review`** — Review the current diff for correctness bugs and cleanups. Run before committing or merging.
- **`/verify`** — End-to-end verification that a change actually does what it's supposed to. Run before claiming work is done.
- **`/loop`** — Recursively run a prompt on a schedule. Useful for monitoring or polling tasks.

### CLAUDE.md Ground Rules

The project's `CLAUDE.md` is mandatory reading. It's not boilerplate — it documents failure modes the team has seen repeatedly:

1. **Read before you write** — especially NautilusTrader reference docs in `docs/nautilus_reference/`
2. **Think before you code** — state assumptions, name tradeoffs, don't guess
3. **Simplicity** — minimum code that solves the problem, no premature abstraction
4. **Surgical changes** — touch only what you were asked to, match the existing style
5. **Verification** — test first when fixing bugs, run existing tests before and after
6. **Goal-driven execution** — state a plan before multi-step work
7. **Debugging** — read the error message, reproduce first, change one thing at a time
8. **Dependencies** — think before adding packages, check what's already in the project
9. **Communication** — say what you did and why, flag concerns
10. **Common failure modes** — kitchen sink, wrong abstraction, invisible decisions, etc.

## Team Tips

_TODO — 6Kmfi6HP will fill these in after review._

## Get Started

_TODO — 6Kmfi6HP will fill these in after review._

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->

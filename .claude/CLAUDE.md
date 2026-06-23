<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

<!-- FAST_CONTEXT_START -->
## Fast Context

Fast Context is often more precise than manual grep/find for broad semantic code discovery. When CodeGraph is unavailable, stale, or insufficient, use `mcp__fast_context_search` before manual search/read loops.

- Start lightweight with `include_code_snippets: false`; request snippets only if ranges are not enough.
- Set `project_path` to the repo root and exclude generated, vendored, build, or cache paths.
- If credentials are missing, run `mcp__fast_context_extract_windsurf_key`.

Use targeted `read`, `search`, CodeGraph, or LSP after Fast Context returns candidates. Do not replace symbol-aware LSP operations with semantic search.
<!-- FAST_CONTEXT_END -->

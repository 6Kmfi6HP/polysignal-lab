# CLAUDE.md

## NautilusTrader

- For any NautilusTrader-related development, refactor, testing, or integration work in this project, consult `docs/nautilus_reference/` before implementation.
- Treat `docs/nautilus_reference/developer_guide/` as the default guidance for design principles, coding standards, Python/Rust implementation details, testing, adapters, and FFI constraints unless the current task explicitly overrides it.

## Reference code

- **Never modify the @refs directory.** The @refs directory contains reference code that should not be changed. Use it only for reference and understanding patterns, but do not make any modifications to files within this directory.

## 仓库布局

结构以代码为准——用 CodeGraph 或 `ls` 查证，不要依赖文档里的目录树。

- Python 命令在仓库根目录运行；前端命令在 `frontend/` 目录运行。
- `docs/nautilus_reference/` 包含 NautilusTrader 开发者指南。
- `data/`、`logs/`、`state/` 是运行时目录，通常不提交。
- 版本与镜像统一遵循 `docs/versioning.md`：`debug/**`、`main` 和 `vX.Y.Z` 分别对应调试、候选和正式渠道，生产部署须通过 `POLYSIGNAL_IMAGE_REF` 固定镜像引用，除非用户明确要求否则 Agent 不得创建 PR。

## Agent skills

### Issue 追踪器

Issues 托管在 GitHub Issues。外部 PR 不作为 triage 来源。详见 `docs/agents/issue-tracker.md`。

### Triage 标签

五个标准标签全部使用默认名称（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。详见 `docs/agents/triage-labels.md`。

### 领域文档

无独立领域文档。术语与设计决定以 `src/polysignal_lab/domain/` 的代码为准。

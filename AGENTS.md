# AGENTS.md

## 硬约束

- **Never modify the `@refs` directory.** 仅供参考与理解模式，不得修改其中任何文件。
- NautilusTrader 相关开发、重构、测试或集成工作，实现前须查阅 `docs/nautilus_reference/`；默认以 `docs/nautilus_reference/developer_guide/` 为设计原则、编码规范、Python/Rust 实现细节、测试、适配器与 FFI 约束的指引，除非当前任务明确覆盖。

## 仓库布局

结构以代码为准——用 CodeGraph 或 `ls` 查证，不要依赖文档里的目录树。

- Python 命令在仓库根目录运行；前端命令在 `frontend/` 目录运行。
- `docs/nautilus_reference/` 包含 NautilusTrader 开发者指南。
- `data/`、`logs/`、`state/` 是运行时目录，通常不提交。
- 版本与镜像统一遵循 `docs/versioning.md`：`debug/**`、`main` 和 `vX.Y.Z` 分别对应调试、候选和正式渠道，生产部署须通过 `POLYSIGNAL_IMAGE_REF` 固定镜像引用，除非用户明确要求否则 Agent 不得创建 PR。
- 领域术语与设计决定以 `src/polysignal_lab/domain/` 的代码为准（无独立领域文档）。

## 协作流程

- Issues 托管在 GitHub Issues，外部 PR 不作为 triage 来源。详见 `docs/agents/issue-tracker.md`。
- 五个标准 triage 标签使用默认名称（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。详见 `docs/agents/triage-labels.md`。

## 行为守则

行为守则（最小代码、反过度工程、快速失败）见 `@.cursor/rules/behavior.mdc`。
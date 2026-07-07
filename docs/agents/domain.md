# 领域文档

工程技能在探索代码库时如何消费本仓库的领域文档。

## 探索前先阅读

- **`CONTEXT.md`** 位于仓库根目录，或
- **`CONTEXT-MAP.md`** 位于仓库根目录（若存在）——它指向每个上下文的 `CONTEXT.md`。阅读与当前主题相关的每一个。
- **`docs/adr/`**——阅读与你即将工作的区域相关的 ADR。在多上下文仓库中，同时检查 `src/<上下文>/docs/adr/` 中的上下文级决策。

如果这些文件不存在，**静默继续**。不要提示缺失，也不要建议预先创建它们。`/domain-modeling` 技能（通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 访问）会在术语或决策实际得到解决时惰性创建它们。

## 文件结构

单一上下文仓库（大多数仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文仓库（根目录存在 `CONTEXT-MAP.md`）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文级决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用词汇表中的术语

当你的输出命名一个领域概念时（在 issue 标题、重构提案、假设、测试名称中），使用 `CONTEXT.md` 中定义的术语。不要使用词汇表明确排除的同义词。

如果你需要的概念不在词汇表中，那是一个信号——要么你在编造项目不用的语言（重新考虑），要么存在真正的空白（记录给 `/domain-modeling`）。

## 标记 ADR 冲突

如果你的输出与现有 ADR 矛盾，显式地提出来，而不是静默覆盖：

> _与 ADR-0007（事件溯源订单）矛盾——但值得重新讨论，因为…_

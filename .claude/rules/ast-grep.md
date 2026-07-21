# ast-grep（优先使用）

结构化代码搜索和大规模同构改写优先用 `ast-grep`，不用 grep/rg/sed。文本搜索只用于字符串、日志等非结构化内容。

```bash
# 搜索
ast-grep run --pattern 'old_api($ARG)' --lang python src/
# 批量改写：先预览 diff，确认后加 -U 写入
ast-grep run --pattern 'old_api($ARG)' --rewrite 'new_api($ARG)' --lang python src/ [-U]
# 复杂规则（YAML，含 fix 改写）
ast-grep scan --rule rule.yml src/ [-U]
```

要点：关系规则（`inside`/`has`）必须加 `stopBy: end`；pattern 不匹配时用 `--debug-query=cst` 查节点 kind；改写必须先预览再 `-U`，之后跑测试。

详细语法见 `.claude/skills/ast-grep/SKILL.md`。

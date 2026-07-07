# Issue 追踪器：GitHub

本仓库的 issues 和 PRD 均以 GitHub Issues 形式存在。所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`。多行内容使用 heredoc。
- **读取 issue**：`gh issue view <编号> --comments`，用 `jq` 过滤评论并获取标签。
- **列出 issues**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，配合 `--label` 和 `--state` 过滤。
- **评论 issue**：`gh issue comment <编号> --body "..."`
- **添加/移除标签**：`gh issue edit <编号> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <编号> --comment "..."`

仓库从 `git remote -v` 自动推断——`gh` 在克隆内运行时自动处理。

## Pull Request 作为 triage 来源

**PR 作为请求来源：否。**（若此仓库将外部 PR 视为功能请求，设为 `yes`；`/triage` 会读取此标志。）

设为 `yes` 时，PR 会与 issue 使用相同的标签和状态流转，通过 `gh pr` 对应命令操作：

- **读取 PR**：`gh pr view <编号> --comments` 和 `gh pr diff <编号>` 查看 diff。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，然后只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的（排除 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论/标签/关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共享同一编号空间，因此裸 `#42` 可能是其中任何一个——先用 `gh pr view 42` 解析，失败则回退到 `gh issue view 42`。

## 当技能说「发布到 issue 追踪器」

创建一个 GitHub issue。

## 当技能说「获取相关工单」

运行 `gh issue view <编号> --comments`。

## 导航操作（Wayfinding）

由 `/wayfinder` 使用。**地图**是一个带子 issue 作为工单的独立 issue。

- **地图**：一个带有 `wayfinder:map` 标签的 issue，包含 Notes/Decisions-so-far/Fog 正文。`gh issue create --label wayfinder:map`。
- **子工单**：通过 GitHub 子 issue 关联到地图的 issue（通过 `gh api` 使用子 issue 端点）。子 issue 不可用时，在地图正文的任务列表中添加子项，并在子工单正文顶部写上 `Part of #<地图编号>`。标签：`wayfinder:<类型>`（`research`/`prototype`/`grilling`/`task`）。被认领后，工单分配给负责的开发人员。
- **阻塞关系**：GitHub 原生的 issue 依赖关系——规范且 UI 可见的表示。通过 `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>` 添加边，其中 `<blocker-db-id>` 是阻塞项的数值型**数据库 ID**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，*不是* `#编号` 或 `node_id`）。GitHub 返回 `issue_dependencies_summary.blocked_by`（仅开放的阻塞项——即实时门控）。依赖关系不可用时，回退到在子工单正文顶部添加 `Blocked by: #<n>, #<n>` 行。所有阻塞项关闭后工单解除阻塞。
- **前沿查询**：列出地图的开放子 issue（`gh issue list --state open`，限定于地图的子 issue / 任务列表），排除有开放阻塞项（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行中有开放 issue）或被分配人的项；按地图顺序取第一个。
- **认领**：`gh issue edit <编号> --add-assignee @me`——会话的首次写入。
- **解决**：`gh issue comment <编号> --body "<答案>"`，然后 `gh issue close <编号>`，最后将上下文指针（gist + 链接）追加到地图的 Decisions-so-far 部分。

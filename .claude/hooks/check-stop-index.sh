#!/bin/bash
# Stop Hook: 检查修改的代码文件数量，>= 3 时提示运行 /check-index
# 输出: 标准 hook 输出格式，始终 continue=true
set -euo pipefail

# 如果不在 git 仓库中，直接静默退出
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo '{"continue":true,"suppressOutput":true}'
  exit 0
fi

# 获取当前未提交的变更中，代码文件的个数
# 只统计 staged + unstaged 中扩展名为代码文件的改动
code_file_count=$(git diff --name-only HEAD 2>/dev/null | awk -F. '
{
  ext = $NF
  if (ext ~ /^(js|jsx|ts|tsx|py|java|rs|go|cpp|c|cxx|h|hpp|kt|rb|php|swift|cs|scala|elm|ex|exs)$/)
    count++
}
END { print count+0 }
')

# 防止因错误返回 0
code_file_count="${code_file_count:-0}"

if [ "$code_file_count" -ge 3 ]; then
  echo "{\"continue\":true,\"suppressOutput\":false,\"systemMessage\":\"本轮修改了 ${code_file_count} 个代码文件，建议运行 /check-index 检查索引一致性。\"}"
else
  echo '{"continue":true,"suppressOutput":true}'
fi

exit 0

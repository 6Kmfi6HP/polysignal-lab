#!/bin/bash
# PostToolUse Hook: 检测文件结构变更，静默退出不打断主流程
# 输入: stdin JSON { tool_name, tool_input: { file_path }, tool_result, ... }
# 输出: 始终 {"continue":true,"suppressOutput":true} 不打断主流程
set -euo pipefail

# 读取输入
input=$(cat)

# 提取文件路径
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')

# 无文件路径则跳过
if [ -z "$file_path" ] || [ "$file_path" = "null" ]; then
  echo '{"continue":true,"suppressOutput":true}'
  exit 0
fi

filename=$(basename "$file_path")

# 跳过索引文件自身
if [ "$filename" = "PROJECT_INDEX.md" ] || [ "$filename" = "FOLDER_INDEX.md" ]; then
  echo '{"continue":true,"suppressOutput":true}'
  exit 0
fi

# 跳过非代码文件
extension="${filename##*.}"
case "$extension" in
  js|jsx|ts|tsx|py|java|rs|go|cpp|c|cxx|h|hpp|kt|rb|php|swift|cs)
    ;; # 代码文件，继续
  *)
    echo '{"continue":true,"suppressOutput":true}'
    exit 0
    ;;
esac

# 跳过排除路径中的文件
exclude_patterns="node_modules|\.git|dist|build|\.next|target|vendor|__pycache__|\.cache|coverage|\.turbo|\.venv|venv|pnpm-store|\.yarn"
if echo "$file_path" | grep -qE "$exclude_patterns"; then
  echo '{"continue":true,"suppressOutput":true}'
  exit 0
fi

# 跳过大文件 (>500KB)
if [ -f "$file_path" ]; then
  size=$(stat -c%s "$file_path" 2>/dev/null || stat -f%z "$file_path" 2>/dev/null || echo 0)
  if [ "$size" -gt 512000 ]; then
    echo '{"continue":true,"suppressOutput":true}'
    exit 0
  fi
fi

# 结构变更检测（供后续 /check-index 使用，此处仅检测不执行更新）
# 检测到变更时可选择创建标记文件供 Stop hook 提示
structural_keywords="\b(import|require|export|class|interface|struct)\b|^use |^def |^fn |^async |^public "
if [ -f "$file_path" ]; then
  if grep -qE "$structural_keywords" "$file_path" 2>/dev/null; then
    # 结构变更已检测到 - 可以触达项目根目录的标记文件
    touch "${CLAUDE_PROJECT_DIR:-.}/.claude/.needs-index-update" 2>/dev/null || true
  fi
fi

# 静默退出
echo '{"continue":true,"suppressOutput":true}'
exit 0

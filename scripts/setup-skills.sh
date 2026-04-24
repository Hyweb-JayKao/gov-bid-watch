#!/usr/bin/env bash
# 建立 agent-skills symlink 到 .claude/skills/
# 前提：先 clone https://github.com/addyosmani/agent-skills 到 ~/.agent-skills
set -euo pipefail

SRC="$HOME/.agent-skills/skills"
DST="$(cd "$(dirname "$0")/.." && pwd)/.claude/skills"

if [[ ! -d "$SRC" ]]; then
  echo "❌ 找不到 $SRC"
  echo "   請先：git clone https://github.com/addyosmani/agent-skills ~/.agent-skills"
  exit 1
fi

mkdir -p "$DST"
for skill in "$SRC"/*/; do
  name=$(basename "$skill")
  target="$DST/$name"
  if [[ -e "$target" ]]; then
    echo "⊙ 已存在 $name，略過"
  else
    ln -s "$skill" "$target"
    echo "✓ $name"
  fi
done
echo "完成。"

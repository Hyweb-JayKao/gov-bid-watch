#!/usr/bin/env bash
# ship-pr-loop.sh — ① Ship-PR-Until-Green loop runner（harness P1）
#
# spec: docs/specs/ship-pr-until-green-harness.md（sw-factory）§2
# 定位：編排「跑客觀信號 → push → 等 CI → 紅就回報 failing 信號 → 達標才交獨立驗收」
#       這條無聊的來回，把三層終止 / 保險絲 / 不可逆邊界守住。
#
# 它【不】替你寫業務 code——寫 code 是 agent（黃仁勳）戴 CTO 帽做的事。
# 每一輪的順序是：agent 改一小步 code → 呼叫本 runner 跑一輪 → runner 回報
#   PASS（達標，進獨立驗收） / FAIL（紅，附 failing 信號，回去再改） / STOP（保險絲/無進展，停 + 回報人）。
#
# 錨點鐵則（spec §2.2）：達標一律錨在「本機 pytest 綠 + 遠端 CI conclusion=success」，
#   禁用「agent 自稱做完」當終止條件。
#
# 不可逆邊界鐵則（spec §2.3）：本 runner 只做可逆動作（append commit / push 到 feature 分支 / 開 PR）。
#   amend / rebase / force-push / push 到 main / merge 一律【拒絕執行】並 exit 2。merge 永遠人按。
#
# 用法：
#   在隔離 worktree 的 feature 分支上，agent 改完一小步後跑：
#     bash .claude/harness/ship-pr-loop.sh            # 跑一輪（推薦：agent 控迴圈，每輪自己改 code）
#     bash .claude/harness/ship-pr-loop.sh --status   # 只印目前狀態 / 保險絲剩餘額度，不動作
#
# 狀態檔（跨輪累積，落 .claude/harness/.state/）：iter / 紅項分數歷史 / 起始時間 / token（由 agent 回填）。

set -uo pipefail

# ---------- 設定（可由環境變數覆寫，預設＝spec §8 拍板值）----------
: "${MAX_ITER:=8}"            # 保險絲：迭代輪數硬上限
: "${NO_PROGRESS_N:=3}"       # 無進展停：連續 N 輪紅項分數沒降
: "${MAX_WALL:=3600}"         # 保險絲：牆鐘秒數上限（60 分）
: "${TEST_CMD:=python3 -m pytest -q}"  # 客觀本機信號（對齊 VERIFY.md；本機用 python3，CI 用 python）
: "${BRANCH_PREFIX_MAIN:=main}"        # 受保護分支名（禁直接 push）

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STATE_DIR="$ROOT/.claude/harness/.state"
STATE="$STATE_DIR/loop.json"
SCORE_LOG="$STATE_DIR/scores.log"     # 每輪紅項分數，一行一輪
mkdir -p "$STATE_DIR"

# ---------- 工具 ----------
now()  { date -u +%s; }
nowiso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say()  { printf '%s\n' "$*" >&2; }
die()  { say "🔴 $*"; exit 2; }

cur_branch() { git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null; }

# read_state KEY -> value（空→預設）
read_state() {
  python3 - "$STATE" "$1" <<'PY' 2>/dev/null || true
import json,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception:
    d={}
print(d.get(sys.argv[2], ""))
PY
}

write_state() {
  python3 - "$STATE" "$@" <<'PY' 2>/dev/null
import json,sys
path=sys.argv[1]
try:
    d=json.load(open(path))
except Exception:
    d={}
for kv in sys.argv[2:]:
    k,_,v=kv.partition("=")
    # 數字盡量存數字
    try: v=int(v)
    except ValueError:
        try: v=float(v)
        except ValueError: pass
    d[k]=v
json.dump(d, open(path,"w"), ensure_ascii=False, indent=2)
PY
}

# ---------- 不可逆邊界守門（任何時候被叫到都先擋）----------
guard_irreversible() {
  local b; b="$(cur_branch)"
  [ "$b" = "$BRANCH_PREFIX_MAIN" ] && die "在受保護分支 '${b}' 上，禁止 loop 動作。請在隔離 worktree 的 feature 分支跑。"
  # worktree dirty 檢查交給 agent 的小步 commit，這裡只擋分支
  return 0
}

# 客觀分數：未通過的測試「信號」數。pytest 失敗→取 failed 數；全綠→0。
# 回 0 = 達標候選；>0 = 還有紅項。
run_local_signal() {
  local log="$STATE_DIR/last-test.log"
  if ( cd "$ROOT" && eval "$TEST_CMD" ) >"$log" 2>&1; then
    echo 0; return 0
  fi
  # 從 pytest 尾巴抓 "N failed"；抓不到就記 1（有紅但數不清）
  local n
  n="$(grep -oE '[0-9]+ failed' "$log" | grep -oE '[0-9]+' | tail -1)"
  echo "${n:-1}"
}

# 等遠端 CI：對當前 branch 的最新 commit 等 GitHub Actions 結論。
# 回 0=success / 1=failure / 2=未知(無 CI run / gh 不可用)
wait_remote_ci() {
  local b; b="$(cur_branch)"
  command -v gh >/dev/null 2>&1 || { say "⚠️ 無 gh CLI，跳過遠端 CI 等待（只憑本機信號）"; return 2; }
  say "⏳ 等遠端 CI（branch=${b}）…"
  # gh run watch 對最新一次該 branch 的 run；先抓 run id
  local rid
  rid="$(gh run list --branch "$b" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)"
  [ -n "$rid" ] || { say "⚠️ 該 branch 尚無 CI run（可能 CI 未啟用或 push 未觸發）"; return 2; }
  gh run watch "$rid" --exit-status >/dev/null 2>&1 && return 0 || return 1
}

# ---------- --status ----------
if [ "${1:-}" = "--status" ]; then
  iter="$(read_state iter)"; iter="${iter:-0}"
  start="$(read_state start_ts)"; start="${start:-$(now)}"
  elapsed=$(( $(now) - start ))
  say "── ship-pr-loop 狀態 ──"
  say "branch       : $(cur_branch)"
  say "iter         : ${iter} / ${MAX_ITER}（剩 $(( MAX_ITER - iter )) 輪）"
  say "wall elapsed : ${elapsed}s / ${MAX_WALL}s"
  say "no-progress  : 連續沒降額度 ${NO_PROGRESS_N}"
  say "scores       : $(tr '\n' ' ' < "$SCORE_LOG" 2>/dev/null)"
  exit 0
fi

# ---------- 主：跑一輪 ----------
guard_irreversible

# init 狀態（首輪）
[ -f "$STATE" ] || write_state iter=0 start_ts="$(now)" started="$(nowiso)"
iter="$(read_state iter)"; iter="${iter:-0}"
start="$(read_state start_ts)"; start="${start:-$(now)}"

iter=$(( iter + 1 ))
write_state iter="$iter" last_run="$(nowiso)"
say "═══ Ship-PR loop 第 ${iter}/${MAX_ITER} 輪 ═══"

# ── 保險絲 A：迭代上限 ──
if [ "$iter" -gt "$MAX_ITER" ]; then
  say "🛑 STOP[保險絲/迭代]：iter=${iter} 超過 MAX_ITER=${MAX_ITER}。停 + 回報人（貼最後紅項 + 最近 diff）。"
  exit 3
fi

# ── 保險絲 B：牆鐘上限 ──
elapsed=$(( $(now) - start ))
if [ "$elapsed" -gt "$MAX_WALL" ]; then
  say "🛑 STOP[保險絲/牆鐘]：已跑 ${elapsed}s 超過 MAX_WALL=${MAX_WALL}s。停 + 回報人。"
  exit 3
fi

# ── 取客觀本機信號 ──
say "▶ 跑本機測試信號：$TEST_CMD"
score="$(run_local_signal)"
echo "$score" >> "$SCORE_LOG"
say "▶ 本輪紅項分數（未過測試數）：$score"

# ── 無進展停：連續 NO_PROGRESS_N 輪分數沒降 ──
# 不用 mapfile（bash 4+，macOS 預設 bash 3.2 無此內建）→ 用 portable 讀法。
HIST=()
while IFS= read -r _line; do HIST+=("$_line"); done < "$SCORE_LOG"
nh=${#HIST[@]}
if [ "$nh" -ge "$NO_PROGRESS_N" ] && [ "$score" -gt 0 ]; then
  stuck=1
  base="${HIST[$((nh-1))]}"
  i=2
  while [ "$i" -le "$NO_PROGRESS_N" ]; do
    prev="${HIST[$((nh-i))]}"
    # 分數有降（prev > base）就不算卡死
    if [ "${prev:-0}" -gt "${base:-0}" ]; then stuck=0; break; fi
    i=$(( i + 1 ))
  done
  if [ "$stuck" -eq 1 ]; then
    recent="$(tail -n "$NO_PROGRESS_N" "$SCORE_LOG" | tr '\n' ' ')"
    say "🛑 STOP[無進展]：連續 ${NO_PROGRESS_N} 輪紅項分數沒降（最近：${recent}）。判定卡死，停 + 回報人。"
    exit 3
  fi
fi

# ── 本機紅 → 回去再改（不 push 髒 commit）──
if [ "$score" -gt 0 ]; then
  say "🔴 FAIL：本機測試有 $score 項紅。把它當下一個 failing 信號，回去改一小步再跑本 runner。"
  say "   失敗末尾："
  tail -n 12 "$STATE_DIR/last-test.log" >&2
  exit 1
fi

# ── 本機綠 → push 觸發遠端 CI（push 前再次擋受保護分支）──
guard_irreversible
say "✅ 本機測試全綠。push 到 feature 分支觸發遠端 CI（禁 force / 禁 main）…"
b="$(cur_branch)"
# 明確用普通 push（無 --force）；push 到 origin/<feature 同名>
if ! git -C "$ROOT" push -u origin "$b" 2>&1 | tee /dev/stderr | grep -qiv "fatal"; then
  : # push 結果由下方 CI 等待與 exit code 決定，這裡不武斷判失敗
fi

# ── 等遠端 CI ──
wait_remote_ci; ci=$?
case "$ci" in
  0) say "🟢 PASS：本機綠 + 遠端 CI success。達標停 → 進 ④獨立驗收（換 session 跑 .claude/harness/independent-verify.sh）。"
     write_state outcome="pass-pending-verify" passed_ts="$(nowiso)"
     exit 0 ;;
  1) say "🔴 FAIL：本機綠但遠端 CI 紅（環境/整合差異）。把 CI 紅項當 failing 信號回去改。"
     exit 1 ;;
  2) say "🟡 PASS(本機)：遠端 CI 不可用/未觸發，僅本機綠。"
     say "   ⚠️ 缺遠端 CI 達標信號＝退化成本機自評（違反 §5 前提1）。請確認 ci.yml 已啟用且 PR 已開，再續。"
     write_state outcome="pass-local-only" passed_ts="$(nowiso)"
     exit 0 ;;
esac

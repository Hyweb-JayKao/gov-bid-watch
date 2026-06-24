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

set -euo pipefail

# ---------- 設定（可由環境變數覆寫，預設＝spec §8 拍板值）----------
: "${MAX_ITER:=8}"            # 保險絲：迭代輪數硬上限（語意：最多跑 MAX_ITER 輪，第 MAX_ITER 輪後停）
: "${NO_PROGRESS_N:=3}"       # 無進展停：連續 N 輪紅項分數沒降
: "${MAX_WALL:=3600}"         # 保險絲：牆鐘秒數上限（60 分）
: "${TEST_CMD:=python3 -m pytest -q}"  # 客觀本機信號（對齊 VERIFY.md；本機用 python3，CI 用 python）

# ──────────────────────────────────────────────────────────────────────────
# 受保護分支守門（codex#3 第 2 輪：env 不可放寬/清空，只能收緊）
# ──────────────────────────────────────────────────────────────────────────
# spec §2.3 不可逆邊界硬要求：受保護分支守門「env 無法關掉」。
#
# 上一輪用 `: "${PROTECTED_RE:=...}"` / `: "${ALLOWED_FEATURE_RE:=...}"` 仍可被
# 普通 env 完全覆寫：`PROTECTED_RE='^$' ALLOWED_FEATURE_RE='.*'` 就同時清空硬擋 +
# 放寬白名單，讓 main 兩層都繞過（= 假修）。
#
# 第 2 輪改法：
#   (1) 受保護判定錨在【程式內建常數】PROTECTED_BUILTIN_RE，完全不吃 env，env 動不了它。
#   (2) env 只開「收緊」一個方向：PROTECTED_EXTRA_RE 可【追加】更多受保護分支，
#       不存在「移除/清空內建保護」的 env 路徑。
#   (3) feature 白名單同理：實際放行條件＝命中白名單 AND 不命中內建保護；
#       ALLOWED_FEATURE_RE 可由 env 收窄；即使被放成 '.*'，內建保護仍先硬擋，
#       不存在「把 main 加進白名單」這條路。
# 內建受保護分支常數——【不可由 env 覆寫或清空】。
readonly PROTECTED_BUILTIN_RE='^(main|master|develop|release([/-].*)?|prod([/-].*)?|production([/-].*)?|hotfix([/-].*)?)$'
# env 只能【追加】更多受保護分支（收緊），預設不追加。設了也只會「多擋」，不會少擋。
: "${PROTECTED_EXTRA_RE:=}"
# feature 白名單：env 可收窄（少放行），放寬無效——下方 guard 內建保護永遠先擋。
: "${ALLOWED_FEATURE_RE:=^(feat|fix|chore|docs|test|refactor|perf|ci|build|style)/.+}"

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
# codex#3（第 2 輪）：受保護判定錨在內建常數 PROTECTED_BUILTIN_RE，env 動不了它；
# env 只能用 PROTECTED_EXTRA_RE 追加更多保護（收緊）。三層：
#   第一層：內建受保護清單硬擋（env 無法清空/放寬）。
#   第一層+：env 追加的額外受保護分支（只多擋不少擋）。
#   第二層：feature 白名單——非 feature 分支一律拒絕（env 放寬白名單也越不過第一層）。
guard_irreversible() {
  local b; b="$(cur_branch)"
  [ -n "$b" ] || die "無法取得當前分支名，拒絕 loop 動作。"
  # 第一層：內建受保護清單（程式常數，env 無法覆寫/清空）。
  if printf '%s' "$b" | grep -Eq "$PROTECTED_BUILTIN_RE"; then
    die "在受保護分支 '${b}' 上，禁止 loop 動作（內建保護硬擋，env 無法繞過）。請在隔離 worktree 的 feature 分支跑。"
  fi
  # 第一層+：env 追加的額外受保護分支（只能收緊；空字串＝不追加）。
  if [ -n "$PROTECTED_EXTRA_RE" ] && printf '%s' "$b" | grep -Eq "$PROTECTED_EXTRA_RE"; then
    die "在受保護分支 '${b}' 上，禁止 loop 動作（PROTECTED_EXTRA_RE 追加保護）。"
  fi
  # 第二層：白名單——非 feature 分支一律拒絕（放寬白名單越不過第一層內建保護）。
  if ! printf '%s' "$b" | grep -Eq "$ALLOWED_FEATURE_RE"; then
    die "分支 '${b}' 非 feature 分支（未命中白名單 ${ALLOWED_FEATURE_RE}），禁止 loop 動作。"
  fi
  return 0
}

# 驗 TEST_CMD 白名單（在主流程前置呼叫，非 command substitution 內，避免 die 被 subshell 吞）。
# 不用 eval（防注入）：只允許 python / python3 / pytest 開頭。其他拒絕 → die(exit 2)。
assert_test_cmd_safe() {
  local first
  read -ra _TEST_ARGV <<<"$TEST_CMD"
  first="${_TEST_ARGV[0]:-}"
  case "$first" in
    python|python3|pytest) return 0 ;;
    *) die "TEST_CMD 首字 '${first}' 不在白名單(python/python3/pytest)，拒絕執行。" ;;
  esac
}

# 執行 TEST_CMD（陣列分詞，不經 eval）。前提：已先跑 assert_test_cmd_safe。
run_test_cmd() {
  read -ra _TEST_ARGV <<<"$TEST_CMD"
  ( cd "$ROOT" && "${_TEST_ARGV[@]}" )
}

# 客觀分數：未通過的測試「信號」數。pytest 失敗→取 failed 數；全綠→0。
# 回 0 = 達標候選；>0 = 還有紅項。
run_local_signal() {
  local log="$STATE_DIR/last-test.log" n
  if run_test_cmd >"$log" 2>&1; then
    echo 0; return 0
  fi
  # 從 pytest 尾巴抓 "N failed"；抓不到就記 1（有紅但數不清）
  n="$(grep -oE '[0-9]+ failed' "$log" | grep -oE '[0-9]+' | tail -1 || true)"
  echo "${n:-1}"
}

# 等遠端 CI：對【本輪 push 的 commit SHA】等 GitHub Actions 結論。
# codex#2：原本抓 branch 最新 run，可能是上一輪舊 commit 的 run → 拿舊綠當本輪成功。
#   改為：只認 headSha == 本輪 HEAD 的 run；找不到對應本輪 SHA 的 run 視為「未知」。
# 參數：$1 = 期望的 commit SHA（本輪 push 的 HEAD）。
# 回 0=success / 1=failure / 2=未知(gh 不可用 / 無對應本輪 SHA 的 run / 逾時)
wait_remote_ci() {
  local b expect rid head_sha tries
  b="$(cur_branch)"
  expect="${1:-}"
  command -v gh >/dev/null 2>&1 || { say "⚠️ 無 gh CLI，無法取得遠端 CI 達標信號"; return 2; }
  [ -n "$expect" ] || { say "⚠️ 未提供本輪 commit SHA，無法綁定 CI run"; return 2; }
  say "⏳ 等遠端 CI（branch=${b}，commit=${expect:0:8}）…"
  # 輪詢等「該 branch 上 headSha==本輪 SHA」的 run 出現。
  # 次數/間隔可 env 覆寫（CI_POLL_TRIES/CI_POLL_SLEEP，預設 ~10 分鐘；測試可調快）。
  : "${CI_POLL_TRIES:=60}"
  : "${CI_POLL_SLEEP:=10}"
  tries=0
  rid=""
  while [ "$tries" -lt "$CI_POLL_TRIES" ]; do
    rid="$(gh run list --branch "$b" --limit 20 \
            --json databaseId,headSha \
            -q ".[] | select(.headSha==\"$expect\") | .databaseId" 2>/dev/null | head -1 || true)"
    [ -n "$rid" ] && break
    tries=$(( tries + 1 ))
    sleep "$CI_POLL_SLEEP"
  done
  [ -n "$rid" ] || { say "⚠️ 逾時：找不到 commit ${expect:0:8} 對應的 CI run（CI 未觸發或未啟用）"; return 2; }
  # 二次確認該 run 的 headSha 確實==本輪 SHA（防競態抓錯）
  head_sha="$(gh run view "$rid" --json headSha -q '.headSha' 2>/dev/null)"
  [ "$head_sha" = "$expect" ] || { say "⚠️ run ${rid} 的 headSha(${head_sha:0:8}) 不等於本輪(${expect:0:8})，拒認"; return 2; }
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
assert_test_cmd_safe   # TEST_CMD 白名單前置驗（die 在主流程才不被 subshell 吞）

# init 狀態（首輪）
[ -f "$STATE" ] || write_state iter=0 start_ts="$(now)" started="$(nowiso)"
iter="$(read_state iter)"; iter="${iter:-0}"
start="$(read_state start_ts)"; start="${start:-$(now)}"

# ── 保險絲 A：迭代上限（codex#7 off-by-one 修正）──
# 語意：最多跑 MAX_ITER 輪。iter 記的是「已完成的輪數」。
#   若已完成 MAX_ITER 輪（iter >= MAX_ITER），本次不再起新一輪 → STOP。
#   檢查放在自增【前】，故 MAX_ITER=8 時最後實際執行的是第 8 輪，第 9 次呼叫即停。
if [ "$iter" -ge "$MAX_ITER" ]; then
  say "🛑 STOP[保險絲/迭代]：已完成 ${iter} 輪，達 MAX_ITER=${MAX_ITER} 上限。停 + 回報人（貼最後紅項 + 最近 diff）。"
  exit 3
fi

iter=$(( iter + 1 ))
write_state iter="$iter" last_run="$(nowiso)"
say "═══ Ship-PR loop 第 ${iter}/${MAX_ITER} 輪 ═══"

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
# codex#2：push 失敗即 FAIL，不可吞 exit code。明確用普通 push（無 --force）。
if ! git -C "$ROOT" push -u origin "$b"; then
  say "🔴 FAIL：push origin/${b} 失敗（網路 / 權限 / non-fast-forward）。"
  say "   未推上＝沒有可被 CI 驗的遠端 commit。修好 push 問題再跑本 runner（禁用 --force 繞過）。"
  exit 1
fi
# 取本輪實際 push 上去的 HEAD SHA，綁定後面要等的 CI run（codex#2）
HEAD_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)"
[ -n "$HEAD_SHA" ] || { say "🔴 FAIL：無法取得本輪 HEAD SHA。"; exit 1; }

# ── 等遠端 CI（綁定本輪 HEAD SHA）──
# set -e 安全：用 `|| ci=$?` 取回傳碼，否則 wait_remote_ci 回非 0 會直接終止腳本。
ci=0
wait_remote_ci "$HEAD_SHA" || ci=$?
case "$ci" in
  0) say "🟢 PASS：本機綠 + 遠端 CI success（commit ${HEAD_SHA:0:8}）。達標停 → 進 ④獨立驗收（換 session 跑 .claude/harness/independent-verify.sh）。"
     write_state outcome="pass-verified" passed_ts="$(nowiso)" passed_sha="$HEAD_SHA"
     exit 0 ;;
  1) say "🔴 FAIL：本機綠但遠端 CI 紅（環境/整合差異）。把 CI 紅項當 failing 信號回去改。"
     write_state outcome="fail-ci-red"
     exit 1 ;;
  2) # codex#1：CI 不可用 / 未觸發 / 找不到本輪 SHA 的 run ≠ 達標。【不可】exit 0 放行為綠。
     say "🛑 STOP[缺客觀 CI 信號]：遠端 CI 不可用 / 未觸發 / 找不到 commit ${HEAD_SHA:0:8} 對應的 run。"
     say "   依 spec §2.2 達標鐵則：必須【本機綠 + 遠端 CI conclusion=success】。"
     say "   缺遠端 CI＝無法達標，禁止當綠放行。請確認 ci.yml 已啟用且該 commit 觸發了 CI，再跑本 runner。"
     write_state outcome="stop-no-ci"
     exit 3 ;;
esac

#!/usr/bin/env bash
# independent-verify.sh — ④ Independent Verifier（harness P1）
#
# spec: docs/specs/ship-pr-until-green-harness.md（sw-factory）§3
# 定位：①loop 跑到綠之後，【換一個乾淨 session / 獨立 agent】重驗一遍。
#   CI 綠只代表「建者想到要寫的測試都過了」，不代表「沒有他沒想到的洞」。
#   建者與自身盲點共用同一套假設（FLUX feedback_builder_not_self_verify）。
#
# 錨點鐵則（§3.3）：判定錨在【非 LLM 信號】——build 成功 / pytest 綠 / CI conclusion=success /
#   AC 對照表全勾，不是「另一個 agent 說 OK」。
#
# 此腳本做機械可驗的那半（重跑測試 + 撈 CI 結論），輸出一份「verifier 報告骨架」；
# 探索測試 / AC 逐條對照 / 補洞 由 qa-automation-architect agent 在【另起 session】填。
# 守則與分工見同目錄 INDEPENDENT-VERIFIER.md。
#
# 用法（必在另起 session 跑，非①的開發 session）：
#   bash .claude/harness/independent-verify.sh <PR_NUMBER>
#   bash .claude/harness/independent-verify.sh        # 不帶 PR 號＝只重跑本機，不撈 CI

set -euo pipefail
: "${TEST_CMD:=python3 -m pytest -q}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PR="${1:-}"
say() { printf '%s\n' "$*" >&2; }

say "═══ ④ Independent Verifier ═══"
say "branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)  PR: ${PR:-<none>}"
say ""

# ── (a) 重跑 build + 全測試（確認 CI 綠非環境僥倖）──
# codex 建議：不用 eval（白名單前綴 + 陣列分詞）；/tmp 檔用 mktemp 防並發/搶佔。
say "▶ (a) 本機重跑全測試：$TEST_CMD"
LOG="$(mktemp -t independent-verify-test.XXXXXX)"
trap 'rm -f "$LOG"' EXIT
read -ra _TEST_ARGV <<<"$TEST_CMD"
case "${_TEST_ARGV[0]:-}" in
  python|python3|pytest) ;;
  *) say "🔴 TEST_CMD 首字不在白名單(python/python3/pytest)，拒絕執行。"; exit 2 ;;
esac
if ( cd "$ROOT" && "${_TEST_ARGV[@]}" ) >"$LOG" 2>&1; then
  LOCAL_PASS=1; say "   ✅ 本機測試全綠"
else
  LOCAL_PASS=0; say "   🔴 本機測試紅 → 驗收不過，退回①loop（CI 綠是僥倖）"
  tail -n 15 "$LOG" >&2
fi

# ── (b) 撈遠端 CI 結論（非 LLM 錨信號）──
# codex#6：原本只看 LOCAL_PASS、忽略 CI_STATE。
#   獨立驗收的達標鐵則（spec §3.3）＝【本機綠 AND 遠端 required CI success】。
#   CI_PASS 三態：1=全綠且至少一個 check；0=有 fail；2=未知(無 PR / gh 不可用 / pending / 無 check)。
CI_PASS=2
CI_STATE="skipped(無 PR 號或 gh 不可用)"
if [ -n "$PR" ] && command -v gh >/dev/null 2>&1; then
  say "▶ (b) 撈 PR #$PR 的 CI 結論"
  # gh pr checks 第二欄＝狀態(pass/fail/pending/skipping)。逐行判定。
  CHECKS="$(gh pr checks "$PR" 2>/dev/null | awk 'NF{print $2}')"
  CI_STATE="$(printf '%s' "$CHECKS" | sort | uniq -c | tr '\n' ',' )"
  if [ -z "$CHECKS" ]; then
    CI_PASS=2; CI_STATE="無 CI check（CI 未啟用或未觸發）"
  elif printf '%s\n' "$CHECKS" | grep -qiE '^(fail|failure|error)'; then
    CI_PASS=0
  elif printf '%s\n' "$CHECKS" | grep -qiE '^(pending|in_progress|queued|waiting)'; then
    CI_PASS=2; CI_STATE="${CI_STATE} (尚有 pending，未定論)"
  else
    # 全部 pass/skipping 且至少有一個 check
    CI_PASS=1
  fi
  say "   CI checks: ${CI_STATE}"
fi

say ""
say "── 機械驗收結果 ──"
say "本機測試全綠     : $([ "$LOCAL_PASS" = 1 ] && echo PASS || echo FAIL)"
say "遠端 CI          : $(case $CI_PASS in 1) echo PASS;; 0) echo FAIL;; *) echo UNKNOWN;; esac) (${CI_STATE})"
say ""
say "下一步（qa-automation-architect 在【本 session】續做，非開發 session）："
say "  1. 讀 spec 的 AC，逐條確認有對應測試且涵蓋（填 AC 對照表）"
say "  2. 探索測試：邊界 / 亂打輸入 / 不照 happy path（找①沒想到的洞）"
say "  3. 找到洞 → 寫回測試案例（變 failing 信號）→ 退回①loop 修綠 → 再驗"
say "  4. 全綠 + AC 全勾 + 探索無洞 → 在 PR 留『獨立驗收已過』記錄 → 轉交人 review"
say ""

# codex#6：機械驗收門＝本機綠 AND 遠端 CI success，缺一不可 exit 0。
if [ "$LOCAL_PASS" != 1 ]; then
  say "🔴 機械驗收不過：本機測試紅。退回①loop。"
  exit 1
fi
if [ "$CI_PASS" = 0 ]; then
  say "🔴 機械驗收不過：遠端 CI 紅。退回①loop。"
  exit 1
fi
if [ "$CI_PASS" != 1 ]; then
  # 帶了 PR 卻拿不到明確 CI success（pending / 無 check / gh 不可用）＝無客觀遠端信號，不可放行
  if [ -n "$PR" ]; then
    say "🛑 機械驗收未定論：本機綠但遠端 CI 非 success（${CI_STATE}）。"
    say "   獨立驗收鐵則須【本機綠 + 遠端 CI success】；缺 CI 信號不可判過。等 CI 出結論再驗。"
    exit 2
  fi
  # 未帶 PR 號＝只做本機半，明示這不是完整驗收，仍以非 0 退出避免被誤當「過」
  say "🛑 機械驗收半套：未提供 PR 號，只重跑了本機（無遠端 CI 信號）。"
  say "   完整獨立驗收須帶 PR 號錨遠端 CI：bash $0 <PR_NUMBER>"
  exit 2
fi

say "🟢 機械驗收通過：本機綠 + 遠端 CI success。交 qa-automation-architect 續做探索測試/AC 對照。"
exit 0

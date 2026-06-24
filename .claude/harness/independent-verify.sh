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

set -uo pipefail
: "${TEST_CMD:=python3 -m pytest -q}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PR="${1:-}"
say() { printf '%s\n' "$*" >&2; }

say "═══ ④ Independent Verifier ═══"
say "branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)  PR: ${PR:-<none>}"
say ""

# ── (a) 重跑 build + 全測試（確認 CI 綠非環境僥倖）──
say "▶ (a) 本機重跑全測試：$TEST_CMD"
LOG="/tmp/independent-verify-test.log"
if ( cd "$ROOT" && eval "$TEST_CMD" ) >"$LOG" 2>&1; then
  LOCAL_PASS=1; say "   ✅ 本機測試全綠"
else
  LOCAL_PASS=0; say "   🔴 本機測試紅 → 驗收不過，退回①loop（CI 綠是僥倖）"
  tail -n 15 "$LOG" >&2
fi

# ── (b) 撈遠端 CI 結論（非 LLM 錨信號）──
CI_STATE="skipped"
if [ -n "$PR" ] && command -v gh >/dev/null 2>&1; then
  say "▶ (b) 撈 PR #$PR 的 CI 結論"
  CI_STATE="$(gh pr checks "$PR" 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ',')"
  say "   CI checks: ${CI_STATE:-<none>}"
fi

say ""
say "── 機械驗收結果 ──"
say "本機測試全綠     : $([ "$LOCAL_PASS" = 1 ] && echo PASS || echo FAIL)"
say "遠端 CI          : ${CI_STATE}"
say ""
say "下一步（qa-automation-architect 在【本 session】續做，非開發 session）："
say "  1. 讀 spec 的 AC，逐條確認有對應測試且涵蓋（填 AC 對照表）"
say "  2. 探索測試：邊界 / 亂打輸入 / 不照 happy path（找①沒想到的洞）"
say "  3. 找到洞 → 寫回測試案例（變 failing 信號）→ 退回①loop 修綠 → 再驗"
say "  4. 全綠 + AC 全勾 + 探索無洞 → 在 PR 留『獨立驗收已過』記錄 → 轉交人 review"
say ""
[ "$LOCAL_PASS" = 1 ] || exit 1
exit 0

# ④ Independent Verifier — 守則與分工

> spec: `docs/specs/ship-pr-until-green-harness.md`（sw-factory）§3。
> 與 `independent-verify.sh` 配套：腳本做機械可驗的半（重跑測試 + 撈 CI），本檔定誰來驗、驗什麼、怎麼回。

## 鐵則（違反＝驗收無效）

1. **換 session / 換 agent**：必在【另起乾淨 session】跑，由本部 `qa-automation-architect` 為主。
   **不**延續①的開發 session、**不**由寫 code 的同一 agent 自驗。建者與盲點共用假設。
2. **錨非 LLM 信號**：判定錨在 build 成功 / pytest 綠 / CI conclusion=success / AC 對照表全勾，
   不是「另一個 agent 說 OK」。evaluator 背後要有 ground-truth test suite 兜底。
3. **驗不過＝退回①，不就地放水**：找到的洞寫回測試案例（成為 failing 信號），退回①loop 修綠，
   再驗（驗者與建者保持不同 session）。

## 驗什麼（四步）

| 步 | 內容 | 錨 |
|----|------|----|
| (a) | 本機重跑 build + check + 全測試（對齊 VERIFY.md），確認 CI 綠非環境僥倖 | pytest exit 0 |
| (b) | 撈 PR 的遠端 CI 結論 | gh pr checks = pass |
| (c) | 讀 spec 的 AC，逐條確認有對應測試且涵蓋（填下方對照表） | AC↔test 對照全勾 |
| (d) | 探索測試：邊界 / 亂打輸入 / 不照 happy path，找①沒想到的洞 | 洞數（>0 須補測退回①）|

## AC ↔ 測試對照表（驗收時填）

| AC | 對應測試 | 涵蓋？ | 備註 |
|----|---------|--------|------|
| （逐條填 spec 的 AC） | | ☐ | |

## 用 `/code-review` 還是獨立 agent

- **獨立 agent 為主**（`qa-automation-architect`）：要跑 deliverable + 探索測試，純讀 diff 抓不到 runtime 盲點。
- `/code-review` 為輔：可在本 session 內當靜態審查一道，不取代「跑起來驗」。

## 驗過之後

在 PR 留「獨立驗收已過」記錄（驗了什麼 / 補了哪些案例 / 結論），PR 轉 ready-for-human-review。
到此 loop 結束，**交人 review + merge**。merge 永遠人按。

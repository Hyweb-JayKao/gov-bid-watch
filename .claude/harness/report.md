# harness P1 試點 report — gov-bid-watch 首輪閉環

> 任務：jooca-tw/hyweb-sw-factory#105｜spec：#94 `ship-pr-until-green-harness`
> 日期：2026-06-24｜分支：`feat/harness-p1-ship-pr-green`｜PR：Hyweb-JayKao/gov-bid-watch#20

## 一、閉環結果（寫 code → CI 綠 → 獨立驗）

| 階段 | 結果 | 客觀信號（錨） |
|------|------|---------------|
| 寫 code（真實小任務：`tests/test_harness_loop.py`）| ✅ | 6 新測試，全套 92→98 passed |
| ① loop 達標停 | ✅ | 本機 pytest 綠 + 遠端 CI `pytest` = pass（run 28089663924，watch exit 0）|
| ④ 獨立驗收（機械半）| ✅ | 本機重跑全綠 + `gh pr checks 20` = pass |
| ④ 獨立驗收（探索/AC 對照）| ⏳ 待獨立 session | 鐵則：建者不自驗，換 qa-automation-architect 乾淨 session |

## 二、保險絲與守門驗收（spec §2.2/§2.3）

runner 自測（子行程餵狀態檔），exit code 契約全符：

| 情境 | 預期 | 實測 |
|------|------|------|
| 超過 MAX_ITER（=2，iter=3）| STOP exit 3 | ✅ exit 3「保險絲/迭代」|
| 連續 3 輪同分（1,1,1）本機紅 | STOP exit 3 | ✅ exit 3「無進展」|
| 分數在降（2,2,→1）| 不誤停，走 FAIL | ✅ exit 1 |
| 首輪本機紅 | FAIL exit 1 | ✅ exit 1 |
| 在受保護分支跑 | 拒絕 exit 2 | ✅ exit 2「受保護分支」|
| pre-commit-gate 閘1（無 message）| block | ✅ block |
| pre-commit-gate 閘3（測試紅）| block | ✅ block |

回歸測試固化於 `tests/test_harness_loop.py`（進 CI，未來改 runner 會被擋）。

## 三、不可逆邊界（鐵則，全程遵守）

- 全程在隔離 worktree + feature 分支，未碰 main，避開每日 08:00 data-commit 窗。
- 只 append commit（5 個），無 amend/rebase/force-push。
- push 僅到 feature 分支。未 merge（做到開 PR 為止，merge 留 Jay）。

## 四、baseline 數字（回填 spec §8 TOKEN_BUDGET）

| 指標 | 本輪實測 | 備註 |
|------|---------|------|
| 迭代輪數（達標前）| 1 輪達標 | 真實小任務一次寫對；非典型多輪場景，僅作下限參考 |
| wall-time（本機 runner 單輪）| < 5s（不含等遠端 CI）| 等遠端 CI 另 ~31s |
| 遠端 CI job 時長 | 31s | ubuntu-latest + pip install + pytest |
| token（本任務 agent 端，估計）| 中量；非 loop 內單輪量 | 本任務含建 harness 本身，非「loop 跑既有專案」代表性樣本 |

> TOKEN_BUDGET 結論：本輪是「建 harness + 1 輪達標」混合樣本，不足以定 TOKEN_BUDGET 預設。
> 建議之後拿 harness 跑 2–3 個「真正多輪修綠」任務，收每輪 token 再定預設。

## 五、未完成 / 待人接手

1. ④ 探索測試 + AC 逐條對照：須換乾淨 session 派 qa-automation-architect（建者不自驗）。本 report 只完成機械半。
2. merge：留 Jay。merge 前主 session 跑 /codex:adversarial-review 跨模型審 PR #20 diff。
3. ci.yml 已加且 PR #20 實證能跑綠；若要設 main branch protection required check，屬 repo 設定＝人類動作。

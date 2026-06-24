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

## 四點五、codex 對抗審查退回修（2026-06-24）

主 session 跑 `/codex:adversarial-review`（GPT-5）審 PR #20，判定退回。根病灶＝harness 不把「遠端 CI 客觀綠」當硬閘，打穿驗收②與「跑到 CI 綠」目標。本輪修以下 5 項（皆有對應回歸測試）：

| # | 漏洞 | 修法 | 驗證測試 |
|---|------|------|---------|
| 1 | CI 不可用 / 無 run 時 ci=2，主流程卻寫 pass-local-only 並 exit 0 | ci=2 改 **exit 3 STOP**（缺客觀 CI 信號≠達標，禁當綠放行）| `test_ci_unavailable_stops_not_pass` |
| 2 | push 失敗被吞；等 CI 抓 branch 最新 run（可能是舊 commit）當成功 | push 失敗即 **exit 1 FAIL**；`wait_remote_ci` 帶本輪 HEAD SHA，只認 `headSha==本輪 SHA` 的 run，找不到→STOP | `test_push_failure_fails`、`test_ci_run_sha_must_match_head` |
| 3 | 受保護分支守門是可覆寫黑名單（`BRANCH_PREFIX_MAIN` env 可改、不擋 master/release/prod）| 改**白名單制**：只允 `feat/fix/...` 等 feature 分支；`PROTECTED_RE` 硬擋層 + 白名單層兩層獨立，env 無法繞過放行 | `test_protected_branch_hard_block`、`test_non_feature_branch_blocked_by_whitelist`、`test_protected_block_not_bypassable_by_widening_whitelist` |
| 6 | independent-verify 最後只看 `LOCAL_PASS`、不看 CI 狀態 | 機械驗收門改 **本機綠 AND 遠端 CI success**；CI 有 fail→exit1、pending/無 check/無 PR→exit2、全綠→exit0 | smoke 三態實測（pass→0 / fail→1 / pending→2）|
| 7 | `MAX_ITER=8` 實際跑到 iter=9 才停（off-by-one）| 迭代上限檢查移到自增**前**用 `-ge`：iter=已完成輪數，達 MAX_ITER 即停＝最多 8 輪；README 對齊 | `test_fuse_max_iter_off_by_one`、`test_max_iter_allows_exactly_n_rounds` |

**一併採納的建議改**：
- `set -uo`→`set -euo pipefail`，並逐處加固 `set -e` 副作用（`wait_remote_ci || ci=$?` 取回傳碼；TEST_CMD 白名單檢查前移出 command substitution 以免 die 被 subshell 吞）。
- `eval "$TEST_CMD"` → 白名單前綴（python/python3/pytest）+ `read -ra` 陣列分詞執行，去除注入面（`test_test_cmd_whitelist_rejects_non_python`）。
- 固定 `/tmp/independent-verify-test.log` → `mktemp` + `trap rm` 清理，去並發搶佔。

**測試補強**：原測試刻意避開的最危險路徑（ci=2 應 STOP / push 失敗應 FAIL / CI run SHA 必須==HEAD / protected branch env 不可繞）全部補上。harness 測試 6→13 個，全 repo 105 passed（原 98 + 新 7）。

**不在本輪**：pre-commit-gate（codex#4/#5，既有 sw-factory hook 問題）已另開 sw-factory#106，本 PR 不動。

## 五、未完成 / 待人接手

1. ④ 探索測試 + AC 逐條對照：須換乾淨 session 派 qa-automation-architect（建者不自驗）。本 report 只完成機械半。
2. merge：留 Jay。merge 前主 session 跑 /codex:adversarial-review 跨模型審 PR #20 diff。
3. ci.yml 已加且 PR #20 實證能跑綠；若要設 main branch protection required check，屬 repo 設定＝人類動作。

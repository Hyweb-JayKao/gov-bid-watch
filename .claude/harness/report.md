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

## 四點六、codex 第 2 輪複審退回修（2026-06-24）

第 1 輪 7 問 → 第 2 輪剩 3 點（codex 確認上輪 #1/#2/#5 真修好）。本輪修以下 3 點，皆有回歸測試釘住：

| # | 漏洞（為何上輪是假綠） | 修法 | 怎麼證明真修好 |
|---|------|------|---------|
| #3（核心）| 上輪 `PROTECTED_RE`/`ALLOWED_FEATURE_RE` 用 `:=` 預設賦值，仍可被普通 env **完全覆寫**。`PROTECTED_RE='^$' ALLOWED_FEATURE_RE='.*'` 即同時清空硬擋 + 放寬白名單 → main 兩層全繞。上輪測試只測「放寬白名單但 PROTECTED_RE 仍命中」，沒測「兩層同時放寬」＝刻意避開根因。 | 受保護判定錨在程式**內建常數** `readonly PROTECTED_BUILTIN_RE`（env 完全動不了）；env 只開 `PROTECTED_EXTRA_RE` 一個**收緊**方向（追加更多受保護分支，無清空/放寬路徑）。白名單放寬越不過第一層內建保護。 | `test_protected_block_not_bypassable_by_env_clearing_and_widening`：對 main+master 同時下 `PROTECTED_RE='^$' ALLOWED_FEATURE_RE='.*' PROTECTED_EXTRA_RE='^$'`，**仍須 exit 2 拒絕**——這條正是上輪假綠根因，現在釘死。另 `test_protected_extra_re_can_only_tighten` 驗 env 只能加擋（staging/x 被 EXTRA 列保護→拒絕）。 |
| #4 | `independent-verify.sh` 把「全 skipping/neutral」（什麼都沒真跑）也判 PASS。 | 改：必須**至少一個 check 真 pass** 且無 fail/pending 才 success；全 skip/neutral/空 → UNKNOWN(2)，不可放行。順手修 line 74 `case` 嵌在 `$(...)` 內的 bash syntax error（拆成獨立 `case` 算 `CI_LABEL`，原 bug 會讓判定漏接而誤 exit 0）。 | 新增 `tests/test_independent_verify.py` 10 案：`test_all_skipping_is_not_pass`、`test_all_neutral_is_not_pass`、`test_no_check_is_not_pass` 全須 exit 2；`test_real_pass_passes`（真 pass→0）、`test_pass_plus_skipping_still_passes`（真 pass+skip→0）守住不過度收緊。 |
| 流程不一致 | `ci.yml` 只在 `PR→main`/`push→main` 觸發，但流程是「loop 綠才開 PR」→ feature branch 還沒 PR 時無 CI 信號 → runner `wait_remote_ci` 找不到本輪 SHA 的 run → STOP(3) 卡死。 | `push` 觸發放寬到所有分支（`branches: ["**"]`）：feature branch 一 push 就跑 CI，runner 等的客觀 CI 信號實際會產生；`PR→main` 仍各自跑（含 fork PR）。 | push 後 GitHub Actions 對 feature commit 觸發 CI（PR #20 push 即驗）；runner `wait_remote_ci` 綁本輪 HEAD SHA 能撈到對應 run。 |

**本輪驗證結果**：harness 兩檔測試 `test_harness_loop.py`(14) + `test_independent_verify.py`(10) 全綠；全 repo `116 passed, 5 xfailed`。本機綠，已 push 同 branch 觸發遠端 CI。

## 五、未完成 / 待人接手

1. ④ 探索測試 + AC 逐條對照：須換乾淨 session 派 qa-automation-architect（建者不自驗）。本 report 只完成機械半。
2. merge：留 Jay。merge 前主 session 跑 /codex:adversarial-review 跨模型審 PR #20 diff。
3. ci.yml 已加且 PR #20 實證能跑綠；若要設 main branch protection required check，屬 repo 設定＝人類動作。

## 四點七、CI 紅修復：detached HEAD 環境回歸（2026-06-24）

**症狀**：本機在 `feat/...` 分支 `116 passed`，但 PR #20 的 CI（run 28096163131）pytest **FAIL**。

**根因（#3 修法引入的環境回歸）**：`actions/checkout` 預設 checkout 出來是 **detached HEAD**，`git rev-parse --abbrev-ref HEAD` 回 `HEAD`（非分支名）。#3 新加的 feature 分支白名單守門（`ALLOWED_FEATURE_RE`）命中「`HEAD` 非 feature 分支」→ `guard_irreversible` 在主流程開頭（runner line 204）**exit 2 搶先攔掉**，harness 行為測試（off-by-one / no-progress / local-red / push / ci 三態）全在跑到目標斷言前就被擋紅。本機在 feat/ 分支跑剛好命中白名單所以全綠，遮住了這個洞。

**修法（只動測試、不動 runner）**：問題不在守門邏輯（守門擋 detached HEAD 是正確的——不該在無分支上下文跑不可逆動作），在於**行為測試不該依賴 CI 實際 checkout 的分支**。`tests/test_harness_loop.py` 的 `_run` 一律前置「分支攔截」stub：攔 `rev-parse --abbrev-ref HEAD` 回測試指定分支（行為測試預設 `feat/harness-test`，分支判定測試經 `_run_on_branch(stub_branch=...)` 指定），其餘 git 子命令照舊 delegate 真 git。branch context 由測試明確注入，與 runner 在哪個 checkout 跑無關。

**未動 #3 protected 守門**：本次 diff **只改 `tests/test_harness_loop.py`**，`ship-pr-loop.sh` 一個字沒動 → #3 成果（`readonly PROTECTED_BUILTIN_RE` 內建常數、env 只能 `PROTECTED_EXTRA_RE` 收緊、白名單放寬越不過內建保護）原封保住，protected branch 仍不可被任何 env 組合繞過。

**怎麼證明 detached HEAD 也綠**：worktree 內 `git checkout --detach`（`rev-parse --abbrev-ref HEAD` 確認回 `HEAD`，與 CI 同態）後跑 `pytest`：
- `tests/test_harness_loop.py`：14 passed（修前同環境 3 failed）。
- 全 repo：`116 passed, 5 xfailed`，與 feat/ 分支結果一致。
re-attach 回 feat/ 分支後再跑亦 116 passed，兩態一致。

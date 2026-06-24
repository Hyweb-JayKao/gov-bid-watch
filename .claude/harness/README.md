# harness P1 — Ship-PR-Until-Green + Independent Verifier

> spec: `docs/specs/ship-pr-until-green-harness.md`（hyweb-sw-factory）。
> 試點裝進 gov-bid-watch。本目錄＝harness 落地件，把「跑 CI → 看紅綠 → 紅就修」的來回交給機器，
> 跑到 CI 綠才叫人，且綠了還要換 session 獨立再驗一遍，人留下的只有 review + 按 merge。

## 件清單

| 檔 | 角色 |
|----|------|
| `ship-pr-loop.sh` | ① Ship-PR-Until-Green runner：每輪跑客觀信號 → push → 等 CI，判三層終止 / 保險絲 / 不可逆邊界 |
| `independent-verify.sh` + `INDEPENDENT-VERIFIER.md` | ④ 獨立驗收：換 session 重驗，錨非 LLM 信號 |
| `../hooks/pre-commit-gate` | ② commit 前三閘（message / diff≤150 / 測試綠），loop step 3 用（沿用 sw-factory，不重造）|
| `../../VERIFY.md` | 測試指令單一來源，三方對齊 |
| `.state/` | loop 跨輪狀態（iter / 分數歷史 / 起始時間），gitignore |

## 怎麼跑（agent 視角）

前提（spec §5，缺任一不套）：CI 在 PR→main 跑全測試（`.github/workflows/ci.yml`）｜AI-owned 無真人並發｜spec AC 可測｜測試基建到位。

```bash
# 0. 隔離工作樹 + feature 分支（撞車防護，gov-bid-watch 有每日 data-commit）
git worktree add -b feat/xxx <worktree-path> origin/main
export PRECOMMIT_TEST_CMD="python3 -m pytest -q"  # 啟用 commit 前閘3

# 1. ① loop：agent 改一小步 code → 跑一輪 runner，依回報決定下一步
bash .claude/harness/ship-pr-loop.sh
#   exit 0 = PASS（達標，進 ④）   exit 1 = FAIL（紅，回去改再跑）   exit 3 = STOP（保險絲/無進展，回報人）
bash .claude/harness/ship-pr-loop.sh --status   # 看額度

# 2. 達標後開 PR（draft 或 ready），人 merge 前最後一道
gh pr create ...

# 3. ④ 獨立驗收：【另起乾淨 session】派 qa-automation-architect 跑
bash .claude/harness/independent-verify.sh <PR_NUMBER>
#   驗過 → PR 留「獨立驗收已過」→ 交人 review + merge
```

## 三層終止（錨客觀信號，spec §2.2）

| 層 | 條件 | 預設 | 行為 / exit |
|----|------|------|------|
| 達標停 | 本機 pytest 綠 **且** 遠端 CI success（CI run 的 commit SHA 必須==本輪 HEAD）| — | exit 0 → 進 ④ |
| 保險絲（迭代）| 已完成 `MAX_ITER` 輪後再呼叫即停（**最多跑 MAX_ITER 輪**；第 8 輪是最後一輪，第 9 次呼叫 STOP）| 8 | exit 3，停 + 回報人 |
| 保險絲（牆鐘）| 牆鐘 > `MAX_WALL` | 3600s | exit 3 |
| 無進展停 | 連續 `NO_PROGRESS_N` 輪紅項分數沒降 | 3 | exit 3 |
| 缺客觀 CI 信號 | push 後找不到本輪 SHA 對應的 CI run / gh 不可用 / 逾時 | — | **exit 3 STOP**（不可當綠 exit 0）|
| 本機綠但 CI 紅 / push 失敗 | — | — | exit 1 FAIL，回去改 |

> ⚠️ **CI 不可用 ≠ 達標**（codex#1）：缺遠端 CI success 信號一律 STOP，禁退化成本機自評放行。
> ⚠️ **CI run 必須對齊本輪 commit**（codex#2）：runner 只認 `headSha==本輪 HEAD` 的 run，不拿 branch 舊 run 充當成功；push 失敗即 FAIL。

`TOKEN_BUDGET` 試點期先收 baseline 實測（agent 回填），再定預設。覆寫：`MAX_ITER=N bash ship-pr-loop.sh`。
CI 輪詢覆寫：`CI_POLL_TRIES` / `CI_POLL_SLEEP`（預設 60 × 10s）。

## 不可逆邊界（鐵則，spec §2.3）

runner 只做可逆動作：append commit / push feature 分支 / 開 PR。
**禁** amend / rebase / force-push / push main / **auto-merge**。

**受保護分支守門＝白名單制**（codex#3）：
- 只有命中 `ALLOWED_FEATURE_RE`（預設 `feat|fix|chore|docs|test|refactor|perf|ci|build|style` 開頭）的 feature 分支可被 loop 動作。
- `PROTECTED_RE`（`main|master|develop|release*|prod*|production*|hotfix*`）為第一層硬擋，與白名單**獨立兩層**——放寬任一層，另一層仍把關，故 env 無法繞過放行受保護分支。
- 非 feature 分支 / 受保護分支 → exit 2 拒絕。merge 永遠人按。

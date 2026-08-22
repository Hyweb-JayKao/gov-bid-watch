# ADR 0002 — watcher 間歇 401 retry + 失敗告警

- 狀態：Proposed（待 Jay/RD review，issue #17）
- 日期：2026-06-23
- 脈絡：issue #17（watcher ~50% 間歇失敗且靜默無人知）

## 背景

`daily-watcher.yml` 每日跑，6/16 起呈 ✅❌✅❌ 約 50% 間歇失敗，且 workflow 無任何告警 → 靜默。
6/23 失敗根因：`fetch_pcc.py` 對 TwinkleAI 的請求收到 401 直接 raise、無 retry。

## 決策

### D1. 401 判讀為「閘道間歇抖動」，retry 是對症解（非 key 問題）

失敗 run 的 401 回的是**裸 nginx HTML 401 頁**，不是 MCP app 層的 JSON-RPC 認證 error。

- 判讀：key 失效會回 JSON-RPC error（帶 code/message）；裸 nginx 401＝請求沒到達 app，被閘道層擋（rate-limit / upstream 抖動）。run 歷史間歇成功也證明 key 有效。
- 為何重要：若是 key 死掉，retry 無用、該停下喊人；既然是閘道抖動，retry + backoff 正中要害。
- 反方：萬一哪天真是配額耗盡，retry 會多燒幾次配額。取捨：retry 設 5 次上限 + 指數 backoff 封頂，最壞多打 4 次；且配額耗盡會走「連續無成功」心跳升級成 high 喊人。

### D2. retry 用 tenacity 包在 `MCP._post`，區分暫時/永久錯

- 包 `_post`（HTTP 邊界）而非更上層：所有對 TwinkleAI 的請求（initialize / query_rows）都過 `_post`，一處收斂。
- **暫時性**（401/429/5xx/timeout/connection）→ raise `TransientHTTPError` → 觸發 retry；**永久性**（400 session 錯、403 永久拒、app 層 JSON-RPC error）→ raise 一般 `RuntimeError`，不重試、立即失敗喊人。避免對邏輯錯誤盲目重試。
- backoff：`wait_exponential(1, max=10)` = 1→2→4→8s，`stop_after_attempt(5)`。最壞累計 sleep ~15s，遠在 job 10 分鐘 timeout 內。
- tenacity 顯式加進 requirements.txt（原本只透過 streamlit 傳遞性帶入，不該依賴傳遞依賴）。

### D3. 失敗告警寫 markdown alert，CI 落 repo、本機落 FLUX Inbox

GitHub Actions runner 寫不到 Jay 本機 `~/Documents/FLUX/`，故告警 script `notify_failure.py` 用 `--out-dir` 參數化落點。

- CI：`if: failure()` step 呼叫 → 寫進 repo `data/alerts/`，隨 commit step（改 `if: always()`）留痕；Jay 從 repo / commit 看得到。本機跑預設寫 FLUX Inbox `agent-alert/`，沿用既有 agent-alert markdown 格式。
- 為何 markdown 不 JSON：告警給人讀，沿用 FLUX agent-alert 慣例（H1 + 條列脈絡）。既有 `data/alerts/` 的 push_cap JSON 是機器留痕用途，兩者不同目的、不混。
- 反方：alert 落 repo 需 commit step `always()`，失敗時也跑 commit/push。取捨：`git push || true` 不讓告警提交再次連鎖失敗。

### D4. 心跳升級：連續 ≥3 天無成功 → high

`notify_failure.py` 讀 `watcher_state.json` 的 `last_run`（只在成功跑完才更新 → 代表最後一次成功），算距今天數。

- < 3 天：中度（可能間歇，retry 已擋一層，觀察隔日自動恢復）。
- ≥ 3 天：升級 high，文案提示人工介入（查 key / 配額 / 對外聯絡 / 換源）。
- 為何 3：間歇抖動最多連兩天巧合，連 3 天無成功＝系統性問題非運氣，該喊人。閾值 `--stale-days` 可調。
- state 讀不到（缺失/損壞）→ 保守不升級 high（避免誤判），但仍寫告警標明「無法判讀 state」。

## 驗收對應

- ① retry 對 401/5xx/timeout 生效 + 測試 → D1/D2 + `test_fetch_pcc_retry.py`
- ② pytest 全綠 → 86 passed
- ③ 任一日失敗 → 寫 Inbox alert → D3 + workflow `if: failure()` step + `test_notify_failure.py`
- ④ dispatch 驗證 → 見 issue #17 comment（手動 dispatch 結果）

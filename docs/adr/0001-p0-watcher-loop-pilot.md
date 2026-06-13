# ADR 0001 — P0 標案 watcher loop pilot 架構決策

- 狀態：Proposed（待 Jay/RD review，PR #issue-14）
- 日期：2026-06-13
- 脈絡：issue #14（loop engineering 首個常駐 loop pilot）

## 背景

在 gov-bid-watch 既有 fetch→merge 管線末端加「P0 標案 watcher → Slack 推播」。
真交付物是 **observability + 成本封頂** 的工程實踐，標案推播只是載體。
SDD 已由 Jay + 馬斯克定案，本 ADR 記實作期拍板的架構決策供 reviewer 跟上推理鏈。

## 決策

### D1. P0 evaluator 純布林、零 LLM（pilot 鐵則）

`is_p0(row) = NOT 排除詞命中 AND (機關白名單命中 OR P0 關鍵字命中)`。

- 為何：loop 的 evaluator 必須錨在**非 LLM 客觀信號**，才能可重複、可審、零成本。LLM 判「值不值得投」留未來，pilot 不碰。
- 反方：布林規則會誤報（如「整合/維護」泛詞）。取捨：pilot 期**寬鬆寧可誤報**（brief），run-log 記足以事後收緊；誤報不設硬上限，靠成本封頂擋爆量。
- 反悔成本：低。規則集中在 `scripts/p0_rules.py`，加 LLM 層只是在布林之後串一段，不動既有管線。

### D2. 複用既有 KEYWORDS/BLACKLIST，P0 只加「加強層」（單一事實源）

既有 `fetch_bids.py` 的字典負責「是不是軟體類」；`p0_rules.py` 只定義既有沒有的
機關白名單 + P0 專屬詞（借閱/無障礙/監視系統排除等），重疊詞不重抄。

- 為何：兩份平行字典必然 drift。brief 明確要求單一事實源。
- 反方：分層後讀者需看兩檔才知完整字典。取捨：在 p0_rules docstring 註明分層，可接受。

### D3. diff 用獨立水位 state，不改 merge.py

`merge.py` 只去重合併進 master、不輸出 new rows（既有行為不動）。新增
`scripts/watcher_diff.py` 維護 `data/watcher_state.json`（seen key 水位 + run-log），
key 沿用 merge 主鍵 `(unit_id, job_number, date)`。

- 為何：merge 是資料層、watcher 是通知層，職責分離。改 merge 輸出 new rows 會牽動既有 weekly.yml commit 流程，風險高於另開模組。
- 反方：兩處各記一份「見過什麼」。取捨：key 定義共用同一主鍵函數對齊，drift 風險可控。
- 反悔成本：中。若日後要合併，把 watcher_diff 的 key 邏輯回收進 merge 即可。

### D4. 成本封頂 = loop 終止/降級錨點

單輪 P0 候選 > 20 → **不推、寫 alert**（`data/alerts/`）+ 水位仍前進避免下輪重複爆量；
單輪 > 5 分鐘 → alert（硬 kill 靠 CI step timeout）。

- 為何：loop 最大風險是「規則錯/資料異常 → 轟爆 Slack」。封頂讓 loop 在失控時**停下喊人**而非繼續輸出。這是 pilot 要驗的兩個工程真空之一。
- 反方：>20 真的有 20 個 P0 時會被誤擋。取捨：pilot 階段「停下喊人」優於「誤轟」；閾值可調（`--push-cap`）。
- 中止演練（`drill_abort.py`）= 回退水位人造爆量，驗證封頂確實觸發，可重複執行。

### D5. Slack 停在 dry-run（checkpoint，issue #14 §7）

推播函數讀 env `SLACK_WEBHOOK_URL`，預設 dry-run 印 payload。**不建 webhook、不推真頻道**。

- 為何：外部系統設定 = 對外動作，留 Jay。實際 webhook URL 由 Jay 設 repo secret，確認 payload 格式後才接真 Slack。
- 反悔成本：零。`notify(dry_run=False)` 一個 flag 即切真推。

### D6. 頻率每日 1 次、cron 預設停用

新增 daily workflow，schedule 預設註解停用，靠 workflow_dispatch 手動驗證；
sequence：fetch → merge → watcher（dry-run）→ commit state/run-log。

- 為何：沿用既有 weekly.yml「先手動 dispatch 驗證再啟自動」紀律。pilot 不自啟正式 schedule（brief 鐵則）。

## 觀測（observability）

每輪寫 run-log 進 `watcher_state.json.runs`：時間 / fetched / new / pushed / watermark / note。
誤報數可由 run-log + 人工標註事後算，供 7 天後收緊規則。alert 落 `data/alerts/` 可查。

## 未採用

- LLM 判標案價值（schema 填充率不足 + pilot 鐵則禁）
- 真得標率分析、金額/截止日維度（pcc 招標公告無結構化欄位）
- 改 merge.py 輸出 new rows（風險見 D3）

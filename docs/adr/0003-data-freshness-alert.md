# ADR 0003：以「批次發布節奏」做新案偵測與斷糧告警

- 狀態：已採納（2026-06-29 根因翻轉後重做，取代初稿的「公告日距今」版）
- 日期：2026-06-29
- 關聯：issue #22、ADR 0002（watcher retry + 失敗告警）

## 背景與根因翻轉

最初症狀：daily watcher 每天 `fetch_pcc.py --days 2`（抓近 2 天公告日）→ 天天 0 筆
→ `no_p0` → 不推 Slack，看起來像「上游斷糧」靜默失敗。

初稿（本 ADR 第一版）判成「資料源斷糧、用公告日距今 14 天告警」。**但實證推翻了
這個前提**：

1. 官方政府電子採購網開放資料頁逐字寫明「**每個月 5 號會產出 2 個月前的資料**」
   → 官方**天生延遲 ~2 個月**。今天（2026-06-29）官方最新批次就是
   `tender_20260402.xml`（4 月下半月），無 5/6 月檔屬正常。
2. 資料以「**半月批次檔**」發布，檔名 `tender_YYYYMM0H.xml` / `award_YYYYMM0H.xml`
   （末 2 碼 0H＝半月期別 01/02，**不是日**）。
3. `date` 欄是標案公告/截止日（可未來），**不等於發布時點**——同一個 `tender_20260302`
   批次裡混有 2026-05、甚至 09 的 date。

→ 結論：
- watcher 用「公告日最近 2 天」對一個永遠落後 ~2 月的源，**結構性抓不到**，0 筆是必然。
- 用「公告日距今 14 天」量新鮮度會**天天誤報**（健康狀態資料本就 ~60 天舊）。
- 換源直連官方（原工項 3）也救不了——官方一樣延遲 2 月。

## 決策：一切以 `filename` 批次為錨

唯一可靠的「發布批次」訊號是 `filename`。fetch 層把 `filename` 帶進 schema，
watcher 的新案偵測與新鮮度判斷都改用批次。

**批次識別**（`freshness.batch_key`）：取 filename 的 8 碼日期段 `YYYYMM0H`，
跨 tender_/award_ 前綴統一用日期段比較（避免前綴字典序混比）。
`batch_period` 把 `YYYYMM0H` 轉成連續半月期序號（相鄰半月差 1）方便比節奏。

### 1. 新案偵測（取代 `--days 2` 公告日窗）
- fetch：`fetch_pcc.py --latest-batches N`，先 group_by filename 取最新 N 個批次、
  再抓那幾批的軟體類案（workflow 預設 N=3）。
- watcher：state 記 `last_batch`（已處理過的最新批次日期段）。每輪只把
  **批次 > last_batch** 的案子當新案做 P0 篩選 + 推 Slack，處理後推進 last_batch。
- **冷啟動基線**：state 從未記過 last_batch → 只設基線、不回補整個歷史 backlog
  （否則首輪湧入數千案必觸成本封頂），本輪不推。
- **無批次訊號 fallback**：若 rows 完全沒有 filename（非 pcc / 舊資料 / drill 合成
  資料）→ 退回既有 seen_keys 水位法，向後相容。

### 2. 斷糧告警（取代公告日距今）
- `freshness.check_batch_freshness`：比較「資料源最新批次」與「依官方節奏應有的
  最新批次」。官方每月約 5 號發布 2 月前整月 → 預期最新到「今天 -2 月」的下半月
  （5 號前保守抓 -3 月）。落後超過 `grace_periods` 個半月期 → 判真斷糧。
- `grace_periods` 預設 **1**：容忍落後 1 個半月期（某半月剛好還沒發的正常時點差），
  落後 ≥2 期才告警 → 不把「正常半月延遲」誤報成斷糧。
- 實證（2026-06-29）：TwinkleAI 最新批次 `20260302`、預期 `20260402` → 落後 **2 期**
  → 正當觸發告警（**非誤報**，TwinkleAI mirror 確實缺 4 月、落後官方 2 批次）。

## 保留 PR #23 已修好的健壯性（codex 兩輪審查）

判準從「公告日」改「批次」，但下列防護沿用、改成批次語意：
1. dry-run 只回報 `would_alert`，不寫 alert 檔、不更新節流 state。
2. 壞掉的節流紀錄（last_alert_date 非法）不丟例外，視為無節流續推。
3. workflow `concurrency` 防 schedule×dispatch 雙推 / state 競態。
4. 批次/節流節點忽略非法值（batch_period 拒 13 月、03 半月等髒值）。
5. master 讀取/檢查失敗只降級 warning，不中斷既有 P0 推播。
6. 一律用 `Asia/Taipei` 日界線（影響發布日 5 號邊界判斷）。
7. webhook 空字串不 fallback env（測試環境不誤送）。
8. 節流只在 `notify_freshness` 回傳 `sent=True` 才啟動（沒送達不消耗 realert 窗）。

## 取捨 / 替代方案

- **沿用公告日距今**（初稿）：作廢——量錯對象，健康狀態天天誤報。
- **換源直連官方**（原工項 3）：暫不做——官方一樣 2 月延遲，換源不解決查詢窗問題；
  且官方下載有 Cloudflare 反爬（當初繞道 TwinkleAI 正為此）。TwinkleAI 落後官方
  2 批次的事另議（催 mirror 或日後換源）。
- **用 `date` 推批次**：錯——date 可未來、與批次不對應（同批次混多月 date）。

## 影響

- `fetch_pcc.py`：COLS/OUT_FIELDS/map_row 加 `filename`；新增 `--latest-batches`
  批次抓取（`fetch_batches` / `latest_batch_keys` / `pick_latest_batch_keys`）；
  `MCP.query_rows` 支援 order_by/group_by。
- `freshness.py`：改為批次模型（`batch_key`/`batch_period`/`period_to_key`/
  `latest_batch`/`expected_latest_batch_period`/`check_batch_freshness` + `taipei_today`）。
- `watcher.py`：批次新案偵測（`find_new_by_batch`，含 baseline/fallback）+ 批次
  新鮮度（`check_data_freshness`），state 新增 `last_batch`。
- `slack_notify.py`：freshness payload 改批次語意（最新批次 / 預期批次 / 落後期數）。
- `daily-watcher.yml`：fetch 改 `--latest-batches 3`、watcher 用 `--freshness-grace`。
- 測試：全套 146 passed / 5 xfailed（`tests/test_freshness.py` 重寫為批次模型 +
  `tests/test_fetch_batches.py` 批次抓取純函式）。

## ⚠️ 待 CI 實測（本機無 token / MCP 不可用，無法在開發 session 驗）

`--latest-batches` 對真 TwinkleAI 的抓取需在 CI（有 `TWINKLE_API_KEY`）或可存取
MCP 的環境驗一次：確認 `latest_batch_keys` 真能取回最新批次、`fetch_batches`
的 `filename ILIKE '%YYYYMM0H%'` 抓得到該批案子。協調者已用 MCP 確認：filename
欄存在且有值、TwinkleAI 最新 `tender_20260302`、官方已 `tender_20260402`。

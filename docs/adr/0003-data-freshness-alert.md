# ADR 0003：資料新鮮度告警（消滅「上游斷糧」靜默失敗）

- 狀態：已採納
- 日期：2026-06-29
- 關聯：issue #22、ADR 0002（watcher retry + 失敗告警）

## 背景

daily watcher 每天只 fetch 近 2 天（`--days 2`）。上游 TwinkleAI `pcc-tender`
mirror（政府電子採購網官方半月公開資料）約 2026-04 底起停止更新後，watcher
本身完全正常，但每天抓回 0 筆 → `no_p0` → 不推 Slack。結果「上游斷糧」變成
**靜默失敗**：看起來像「今天沒新標案」，沒人察覺資料源已死 56 天。

ADR 0002 的失敗告警只覆蓋「run 拋錯」；「成功跑但永遠 0 筆」不在其守備範圍。

## 決策

watcher 每輪額外做一道**資料新鮮度檢查**（與 P0 推播流程獨立）：

- 判斷依據＝**master `data/bids.csv` 的最大 `date`**（非本輪 weekly）。斷糧時
  weekly 為空，但 master 最大日期會卡在最後一次有料日；供料恢復後隨 merge 前進、
  停滯天數自動歸零 → 不誤報。
- `today - 最大date > N 天` → 寫 `data/alerts/*-data_freshness.json` + 推一則
  Slack 告警（含資料源 / 最新日期 / 距今天數）。
- 沿用既有 Slack 路徑與 dry-run / no-webhook 安全降級語意（同 `notify`）。
- 只在 `--master` 有給時啟用，保護既有 P0 流程與舊測試。

## N（門檻）為何取 14 天，而非 issue brief 初估的 3–5

pcc-tender 是「半月公開」資料，**正常供料下最新日期本就會落後**。實測健康期
（2026 Jan–Apr）master：有料日多為每日/每 1–3 天，但農曆年假期出現過最大
**10 天**資料空窗（2/13→2/23）；疊加半月發布節奏，下次發布前最新日期可正常
落後到 ~16 天。

- 取 3–5 → 每逢假期/發布前空窗就誤報 → 違反「正常供料不誤報」鐵則。狼來了
  喊久被無視 ＝ 退回靜默失敗，得不償失。
- 取 14 ＝ 大於實測最壞正常空窗（10）+ 裕度，仍能在再次斷糧後約兩週內告警；
  當前已斷糧 56 天 → 立即觸發。
- 可由 `--freshness-days` 覆寫，Jay 可隨上游節奏調整。

並加重提節流（`FRESHNESS_REALERT_DAYS=3`）：首次偵測立即推，之後同一停滯狀態
每 3 天才重提一次，避免長期斷糧每天轟炸 Slack；恢復供料後清節流，再斷糧能立即重提。

## 取捨 / 替代方案

- **改用「連續 N 天 fetched=0」訊號**：對半月節奏更穩，但語意較間接、且與
  issue 要求的「最新日期 > N 天」不一致。最終選日期-age（直觀、可在告警直接讀出
  停滯天數），半月節奏的誤報風險用提高 N（14）吸收。
- **拿 weekly 當新鮮度依據**：錯——斷糧時 weekly 恆空，無法區分「今天剛好無新案」
  與「上游已死」。必須看 master 累積最大日期。

## 影響

- 不動 `fetch_pcc.py`（換源是 issue #22 工項 2/3，未拍板，本 PR 不碰）。
- 新增 `scripts/freshness.py`、`slack_notify.notify_freshness`、watcher `--master`/
  `--freshness-days`、`daily-watcher.yml` 加 `--master data/bids.csv`。
- 測試 baseline：92 → 105+（新增 `tests/test_freshness.py`）。

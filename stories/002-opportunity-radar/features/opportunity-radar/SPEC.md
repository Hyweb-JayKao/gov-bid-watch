# SPEC: 機會雷達

> 反向工程文件（2026-04-24 補）。位置：`app.py` tab5「雷達」，L416-482。

## 1. Objective
從全部標案中自動篩出「值得投」的候選：強項關鍵字 × Watch List 機關 × 金額門檻，
區分「招標中可投」與「已被拿走（學對手）」。

**User**：業務，找下一個該投的案。

## 2. Commands
`streamlit run app.py` → tab5「雷達」。

## 3. Inputs（三個篩選器）
- **強項關鍵字**：multiselect，選自 `STRENGTH_KEYWORDS` 的 key（圖書館/AI/無障礙 等 6 類），預設全選
- **最小金額（萬）**：number_input，預設 200
- **只看 Watch List 機關**：checkbox，預設 off；勾選後只留機關名包含 `WATCH_UNITS` 任一字串的案

## 4. 過濾邏輯
1. `title` 命中任一強項關鍵字（across 所選類別展開）
2. 若勾 Watch List → 再用 `WATCH_UNITS` 限制 `unit_name`
3. 金額門檻：`award_amount` 優先，無則用 `budget`；若雙皆 NaN 暫予保留（招標中未公告）

## 5. Outputs（兩區塊）
- **🟢 招標中可投**：`type` 含「公開招標/限制性招標/公開取得」→ 依 `budget` 降序顯示
- **🔴 已被拿走**：`type == "決標公告"` → 依 `award_amount` 降序，加「凌網?」欄
- **搶走這塊餅的 Top 10 廠商**：將「已被拿走」explode companies、groupby 取前 10

## 6. Boundaries
- 關鍵字清單在 `helpers.py:STRENGTH_KEYWORDS`，改常數即新增類別
- Watch List 機關在 `helpers.py:WATCH_UNITS`
- 不做即時通知、不爬新資料

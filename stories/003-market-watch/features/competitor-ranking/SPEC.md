# SPEC: 同領域對手排名（Competitor Ranking）

> 新增於 2026-04-24（issue #6）。位置：`app.py` tab9「同領域」。

## 1. Objective
輸入關鍵字（例：「圖書館」「資安」「AI」），回答「這個領域近 12 個月誰是老大、自家排第幾」。

**User**：總經理 / 策略主管，競爭格局情報。

## 2. Commands
`streamlit run app.py` → tab9「同領域」→ 輸入關鍵字。

## 3. 輸入
- 關鍵字文字框（必填）
- 期間：固定近 12 個月（v1 不可調）

## 4. 處理邏輯
1. 過濾 `type 含「決標」 且 award_amount notna 且 companies notna`
2. 只保留近 12 個月（`date >= today - 365d`）
3. 對 `title` 做子字串比對（大小寫敏感，與既有 `count_themes` 一致）
4. `companies` 以 `|` 拆分並 explode 成單一廠商列
5. groupby company → 案數、總金額
6. 市占率 = 廠商總金額 / 搜尋結果內總金額

## 5. 輸出
- **摘要 metrics**：命中案數、參與廠商數、搜尋結果總金額
- **Top 10 表格**：排名 / 廠商 / 案數 / 總金額（萬）/ 市占率（%）/ 自家?
- **自家補行**：若 `OWN_COMPANIES` 任一不在 Top 10，在表格下方顯示「我方排名：第 N 名（案數 X / 金額 Y 萬 / 市占 Z%）」；完全無命中則顯示警示。

## 6. 資料要求
欄位：`type`, `award_amount`, `companies`, `title`, `date`。

## 7. Boundaries（v1 不做）
- 跨年度趨勢 / YoY
- 聯合承攬關係圖
- 子公司合併計算（僅用 `OWN_COMPANIES` 字串比對，多筆匹配算不同廠商）
- 關鍵字 AND/OR 組合（單一關鍵字子字串）

## 8. 設計註記
- **自家公司設定**：沿用 `helpers.OWN_COMPANIES`，不新增常數。
- **與 tab3「競爭」差異**：tab3 是全市場 Top 20，本 tab 是「領域過濾」的 Top 10。

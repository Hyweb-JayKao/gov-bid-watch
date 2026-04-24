# SPEC: 趨勢分析

> 反向工程文件（2026-04-24 補）。位置：`app.py` tab2「趨勢」，L142-182。

## 1. Objective
看哪些分類「正在成長」——找正在膨脹的市場切片，指引策略。

**User**：業務主管，判斷新切入領域。

## 2. Commands
`streamlit run app.py` → tab2「趨勢」。

## 3. 內容（3 區塊）
1. **分類月度環比成長 Top 10**：
   - pivot category × month
   - 最新月 vs 前一月，成長率 = (last/prev - 1) × 100
   - 過濾門檻：last ≥ 5（避免基期太小失真）
2. **分類月度趨勢**：
   - multiselect top 10 分類（預設前 3）
   - line chart 顯示月度案件數
3. **月度標案數（依年分色）**：
   - bar chart，x=月份、color=年、barmode=group
   - 跨年對比同月份案件量

## 4. 資料要求
- 環比成長需 `category` 欄有值 + 跨度 ≥ 2 個月
- 年度對比需跨年資料

## 5. Boundaries
- 環比只用最新 2 個月，不做移動平均
- 資料不足時顯示 info，不報錯

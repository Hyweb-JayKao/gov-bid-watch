# SPEC: 市場大小（Market Overview）

> 反向工程文件（2026-04-24 補）。位置：`app.py` tab1「市場」，L62-139。

## 1. Objective
一頁看懂政府軟體標案整體市場：總金額、筆數、趨勢、金額級距分布、錢往哪去、YoY。

**User**：業務主管 / 策略規劃，年度策略與季度檢討用。

## 2. Commands
`streamlit run app.py` → tab1「市場」。

## 3. 內容（由上至下 6 區塊）
1. **4 個 metric**：決標總金額（億）、決標筆數、平均單案（萬）、機關數
2. **月度金額趨勢**：line chart，決標 groupby month sum（億）
3. **案件金額級距分布**：bar chart，分 6 級距（<100萬 ~ >1億）
4. **Top 10 標的分類金額佔比**：horizontal bar，依 `category` sum award
5. **需求主題金額分布**：依 `DEMAND_THEMES` 關鍵字命中 title 彙總金額
6. **YoY（同月對比）**：pivot 年×月 矩陣，需資料跨度 ≥ 2 年

## 4. 資料要求
全部基於 `type 含「決標」 且 award_amount notna`。

## 5. Boundaries
- 金額級距 bins 寫死（L87），需擴充時改常數
- YoY 在資料不足 2 年時顯示 info 訊息，不報錯

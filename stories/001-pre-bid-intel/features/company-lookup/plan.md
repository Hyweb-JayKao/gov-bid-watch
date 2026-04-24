# Plan: 公司查詢 tab

依 SPEC.md。單檔改動（`app.py`），無新 dep。

## Scope
新增 tab8「公司查詢」，文字輸入公司名 → 列出資料集最新日往前 365 天內的得標案 + 摘要 + Top 5 合作機關。

## Dependency graph
```
tabs 宣告 (L128)
  └─ tab8 區塊
       ├─ 共用：df (load)、is_own
       ├─ Step A: input 與過濾（type=決標、companies 模糊、date 窗）
       ├─ Step B: 摘要 metrics（案數/總額/平均/機關數）
       ├─ Step C: 明細表
       └─ Step D: Top 5 合作機關 + 命中 distinct 公司名提示
```
A 是 B/C/D 的前置；B/C/D 彼此獨立。

## Vertical slices
一個 PR 即可交付；分三步是為了逐步驗證。

### Task 1 — 新 tab 骨架 + 輸入與過濾（MVP 路徑端對端）
**動作**
- 修改 L128：`tabs` 增加「公司查詢」，保持「清單」在最後 → `tab1..tab8`
- 追加 `with tab7:` → 將原「公司查詢」插在 tab6 之後、「清單」之前；調整變數名為 `tab1..tab8`，清單改 `with tab8`
- 在新 tab：
  - `text_input("公司名（部分即可）")`
  - 決標子集：`df[df["type"].str.contains("決標") & df["award_amount"].notna()]`
  - 日期窗：`cutoff = df["date"].max() - pd.Timedelta(days=365)`；篩 `date >= cutoff`
  - 以 `companies` split `|` → explode → `company.str.contains(kw, case=False, na=False)`
  - 無輸入：`st.info`；有輸入但 0 筆：顯示提示訊息

**驗證**
- `streamlit run app.py`
- 輸入「關貿」顯示表格；空輸入顯示提示；「zzz」顯示 0 筆訊息
- 其他 tab 行為未變

### Task 2 — 摘要 metrics + Top 5 機關
**動作**
- 4 欄 `st.metric`：得標案數 / 總金額（> 1 億用「億」否則「萬」）/ 平均（萬）/ 合作機關數
- `groupby("unit_name").agg(案數, 金額)` → 頭 5 筆 `st.dataframe`，金額轉「萬」

**驗證**
- 輸入「關貿」數字 = 手動 filter CSV 對得上
- 金額 NaN 不造成錯誤

### Task 3 — 命中 distinct 公司名提示 + 明細排序 + 連結欄
**動作**
- `exploded["company"].unique()` 若 > 1 → `st.caption("命中公司：A｜B｜C")`
- 明細表欄位 `date / unit_name / title / award_amount / budget / url`，`sort_values("date", ascending=False)`
- `column_config={"url": st.column_config.LinkColumn("連結")}`
- `award_amount`、`budget` NaN 顯示 `—`（用 `column_config.NumberColumn` 或先轉字串）

**驗證**
- 輸入「關貿」顯示多家命中（若存在）
- 連結欄可點擊
- 排序由新到舊

## Checkpoint
Task 1 完成後人工 demo → 確認 UX 再續 2/3。

## Out of scope (v1)
時間軸圖、主題分布、招標公告、自動測試。

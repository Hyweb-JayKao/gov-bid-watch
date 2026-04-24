# SPEC: 公司得標查詢（投標前競爭情報）

## 1. Objective

投標評估階段，快速查某家公司過去 12 個月在現有資料集中得標的所有軟體案，
用來判斷對手強弱、擅長機關、慣常價位。

**Target user**: 內部業務（自己），投標決策前 5 分鐘內需要答案。

**Not for**: 即時情報、全網爬取、通知推播。

## 2. Commands

延用現有：
- `streamlit run app.py` — 啟動 UI
- 無新增 CLI / script

## 3. Project structure

在 `app.py` 新增一個 tab（或擴充 tab3「競爭」），資料源 `data/bids.csv`，
欄位沿用：`date, unit_name, title, award_amount, budget, companies, url, category, type`。

新增 tab7 `公司查詢`，放在現有 tab6「對手查詢」之後（原 tab7「清單」後移為 tab8）。

## 4. Core features（v1 acceptance criteria）

**Input**: 一個文字框，輸入公司名（完整或部分，case-insensitive 子字串比對）。

**Filter**:
- `type == "決標公告"`
- `companies` 欄位以 `|` 分隔後，任一項包含輸入字串
- `date` 在「今天往前 365 天」內（今天取資料集最新日，避免資料集落後）

**Output**（垂直排列）：
1. **摘要卡**：得標案數、總得標金額（億/萬自動）、平均單案金額、合作機關數
2. **明細表**：`date / unit_name / title / award_amount / budget / url`，依 `date` 新→舊排序，`url` 用 `LinkColumn`
3. **Top 5 合作機關**（案數 + 金額）
4. **模糊比對提示**：若輸入字串命中多個不同公司名（例如「關貿」命中「關貿網路股份有限公司」及其他），列出實際命中的 distinct company names 供確認

**Empty state**: 無輸入 → `st.info` 提示；有輸入但 0 筆 → 顯示 "過去 12 個月無得標紀錄"。

## 5. Code style

- 延用現有 pandas 風格：`df.copy()` → filter → `explode("company")`
- 沿用現有 helper：`is_own()`（標註自家）、金額格式化方式（萬/億）
- 不引入新套件
- 不寫註解除非非顯而易見
- 金額欄若為 NaN 顯示 `—`

## 6. Testing strategy

手動驗證（無自動測試框架）：
- 輸入「關貿」→ 結果應包含「關貿網路股份有限公司」最近 365 天的決標
- 輸入空字串 → info 提示
- 輸入亂碼 → 0 筆訊息
- 輸入自家公司名 → 摘要合理（對照 tab3）

## 7. Boundaries

**Always**:
- 只讀 `data/bids.csv`
- 「12 個月」基準日 = 資料集最大 `date`（非系統今天），避免資料落後誤判
- 金額 NaN 視為 0 計入總和但明細顯示 `—`

**Decided**:
- 新開 tab7「公司查詢」
- 12 個月基準日 = 資料集最大 `date`
- 只看決標（`type == "決標公告"`）

**Ask first**:
- 是否加「時間軸圖」、「主題分布」（v1 先不加）

**Never**:
- 不爬新資料、不打外部 API
- 不做排程 / 通知
- 不新增 dependency
- 不改動現有 tab 的行為

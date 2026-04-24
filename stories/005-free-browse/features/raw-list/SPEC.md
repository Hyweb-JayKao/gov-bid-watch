# SPEC: 自由過濾清單

> 反向工程文件（2026-04-24 補）。位置：`app.py` tab8「清單」，L603-631。

## 1. Objective
提供最通用的過濾 UI，任何 ad-hoc 查詢都能靠組合 filter 完成。

**User**：業務或資料使用者，有特殊查詢需求（儀表板沒涵蓋的）。

## 2. Commands
`streamlit run app.py` → tab8「清單」。

## 3. Inputs（5 個 filter）
第一列：
- **類型**：multiselect，source = `df["type"]` 的所有唯一值（公開招標/決標公告/...）
- **標題關鍵字**：text_input，子字串 case-insensitive 比對
- **日期區間**：date_input，預設 = 資料最小日 ~ 最大日

第二列：
- **機關類型**：multiselect，source = `df["unit_type"]` 的所有唯一值（中央部會/學校/醫療/...）
- **只看凌網中標**：checkbox，預設 off；勾選後 `companies` 包含 `OWN_COMPANIES` 任一字串

## 4. 過濾邏輯
五個 filter **AND** 串接：
1. 若選類型 → `type` in 選定
2. 若選機關類型 → `unit_type` in 選定
3. 若有關鍵字 → `title` contains（case insensitive）
4. 若有日期區間 → `date` 在區間內
5. 若勾只看凌網 → `companies` 含 `OWN_COMPANIES` 任一

## 5. Output
顯示欄位：`date, unit_name, unit_type, type, title, budget, award_amount, companies, url`
- `url` 用 LinkColumn
- 標題顯示命中筆數 `{N:,} 筆`

## 6. Boundaries
- 純 client-side 過濾（pandas），資料量大（目前 8K+）仍可接受
- 不做排序控制（Streamlit dataframe 內建欄位點擊排序）
- 不匯出 CSV（v1 先不做）

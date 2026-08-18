> 政府標案觀測（軟體開發類）— 每週自動抓取 + Streamlit Dashboard。

## 版面（左側導覽 + 總覽儀表板）

深色頁首 + 左側導覽列（`streamlit-option-menu`，未安裝時自動退回 `st.radio`），
進站先看「總覽儀表板」，再由 nav 切到各分析頁（每次只算當前頁，省記憶體）。

**總覽儀表板**只放有真實資料源的面板：KPI 列（決標金額/筆數/平均單案/公告案件/
得標廠商數/機關數/凌網表現，delta = 近 90 天 vs 前 90 天）、標案公告趨勢、
標案分類 donut、得標廠商排行（紅=凌網）、金額級距、需求主題金額、機關類型。

> ⚠️ **刻意移除**參考設計中無資料源的面板（硬做＝假數據）：
> 平均招標天數（無截止日欄位）、採購流程漏斗（g0v 無領標/投標/資審/評選階段）、
> 得標率比較與得標關鍵因素、得標/失標原因（皆為問卷資料）、各縣市地圖
> （`unit_name` 僅 ~26% 可推出縣市）。

導覽頁：總覽儀表板｜市場趨勢｜標案趨勢｜廠商競爭｜機關分析｜得標機會雷達｜
對手查詢｜公司查詢｜標案清單｜同領域排名｜法規合規。

## 架構

```
本機 launchd (每週一 08:00 台北)
  ~/Library/LaunchAgents/com.jaykao.gov-bid-watch.plist
  → ~/scripts/gov-bid-watch-weekly.sh
    → scripts/fetch_bids.py --days 7
    → scripts/merge.py → data/bids.csv
    → commit + push
      ↓
Streamlit Community Cloud (app.py)
  → 讀 data/bids.csv 渲染
```

**為什麼用 launchd 不是 GitHub Actions**：
g0v API (pcc-api.openfun.app) Cloudflare 擋 GitHub Actions IP 段回 403，
本機跑 OK。Actions workflow 保留手動觸發備用。

**Log 位置**：`~/Library/Logs/gov-bid-watch/run_*.log`（保留最近 10 份）

## 資料來源

**兩套並存（遷移中）**：

1. **g0v 標案瀏覽器 API**（現役）— [pcc-api.openfun.app](https://pcc-api.openfun.app/)，
   `scripts/fetch_bids.py`。痛點：Cloudflare 擋 Actions IP、僅約 16 個月資料。
2. **TwinkleAI pcc-tender**（新，`scripts/fetch_pcc.py`）— 行政院公共工程委員會
   政府電子採購網 web.pcc.gov.tw 官方半月公開資料 mirror，**2015→今、16 萬+ 筆、21 欄、無 403**。

> 📘 **TwinkleAI MCP 的操作細節與踩坑**（transport 升級、`offset` 帶 WHERE 失效、
> 資料集 caveat、token 撈取路徑）見 **[docs/TWINKLE-MCP-KN.md](docs/TWINKLE-MCP-KN.md)**。
> 改 `fetch_pcc.py` 之前先讀，那些坑都踩過了。

### 切換到 pcc-tender（fetch_pcc.py）

純 HTTP（JSON-RPC over SSE）打 TwinkleAI MCP endpoint，**不依賴 Claude Code**，
launchd 可直接跑。token 走環境變數 `TWINKLE_API_KEY`（不寫死、不進 git）。

```bash
export TWINKLE_API_KEY=sk-xxxx
# 週度增量
python scripts/fetch_pcc.py --days 14 --out data/weekly.csv
python scripts/merge.py --weekly data/weekly.csv
# 一次性 backfill（11 年）
python scripts/fetch_pcc.py --since 2015-04-01 --out data/bids_full.csv
```

輸出 schema 對齊 bids.csv，外加 pcc 欄位：`notice_date / award_way / county /
county_code / town_code / contact_person / contact_phone / losing_supplier`。

> ⚠️ **遷移注意（實測）**：
> - pcc 無「預算金額」欄 → 招標公告無金額（雷達招標中不能用金額篩）
> - `category` 只有粗分類（勞務類/財物類）→ 軟體篩選靠 `fetch_pcc.py` 的關鍵字+黑名單；
>   `app.py load()` 已放行粗分類
> - `county_code` 僅決標公告有（縣市分析限決標）；`detail_url` 多空（退回 Google）；
>   `losing_supplier`（未得標廠商）填充率低，無法穩定推「真得標率」
> - 切換時 `bids.csv` 不會被自動覆蓋；backfill 產生新檔、人工確認後再 rename / merge

## 過濾規則

- **正向關鍵字**：系統、軟體、資訊、網站、APP、平台/平臺、維運、數位、雲端、AI...
- **黑名單**：工程、營造、建築、道路、橋樑、管線...（排除土木/建築類誤抓）
- **分類白名單**：g0v 用細分碼 `勞務類*`+`財物類4*`；pcc 用粗分類 `勞務類`+`財物類`
  （`KEYWORDS`/`BLACKLIST` 兩 fetcher 共用，定義在 `fetch_bids.py`）

## 過濾規則

- **正向關鍵字**：系統、軟體、資訊、網站、APP、平台/平臺、維運、數位、雲端、AI...
- **黑名單**：工程、營造、建築、道路、橋樑、管線...（排除土木/建築類誤抓）
- **分類白名單**（tender detail 模式）：`勞務類*` + `財物類4*`（資訊設備）

## 本地開發

```bash
# repo 路徑：~/repos/gov-bid-watch
cd ~/repos/gov-bid-watch
pip install -r requirements.txt

# 抓過去 N 天
python scripts/fetch_bids.py --days 30 --out data/weekly.csv

# 合併到主檔
python scripts/merge.py --weekly data/weekly.csv

# 本地跑 dashboard
streamlit run app.py
```

## Streamlit Cloud 部署

1. 到 https://share.streamlit.io
2. 連 GitHub → 選本 repo → main 分支 → `app.py`
3. Deploy，自動給 URL

## 手動觸發 launchd（即刻跑一次）

```bash
launchctl start com.jaykao.gov-bid-watch
tail -f ~/Library/Logs/gov-bid-watch/run_*.log
```

## TODO

- [ ] 近 2 年 backfill（一次性跑 `--days 730` 再 commit）
- [ ] 廠商關聯（同統編、同負責人）
- [ ] 熱度定義調整（僅絕對數 >= 5 才算）

> 政府標案觀測（軟體開發類）— 每週自動抓取 + Streamlit Dashboard。

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

[g0v 標案瀏覽器 API](https://pcc-api.openfun.app/)（原 pcc.g0v.ronny.tw 已搬遷）。

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

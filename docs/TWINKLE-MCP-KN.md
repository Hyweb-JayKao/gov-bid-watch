# TwinkleAI opendata MCP — 操作知識與踩坑

> **來源**：從 FLUX 個人記憶卡 `reference_twinkle_opendata_hub.md` 下放（2026-08-18，FLUX#175）。
> **為什麼要搬**：sub-agent 看不到 FLUX 的記憶，執行細節留在那裡等於讓 agent 蒙著眼改 `scripts/fetch_pcc.py`。
> 執行類知識（怎麼做／踩坑／SOP）一律住對應 repo。
>
> ⚠️ **本 repo 的自動抓取已於 2026-08-04 停用**（`Weekly fetch` 與 `Daily P0 watcher` 兩個 workflow 皆
> `disabled_manually`，Jay 拍板整座雷達退役——上游 mirror 停在 20260302 批次且零回應）。
> 這份文件是**知識保存**：日後若重啟雷達、或改直連官方源時，這些踩坑不必重踩一次。

## Endpoint 與認證

| 項 | 值 |
|---|---|
| Endpoint | `https://api.twinkleai.tw/mcp/` |
| Transport | MCP **streamable HTTP**，Bearer token |
| Scope | user scope（已掛） |
| 本 repo 取用方式 | 環境變數 `TWINKLE_API_KEY`（不寫死、不進 git） |

**token 撈取路徑**：`~/.claude.json` → `mcpServers.twinkle-hub.headers.Authorization`（`Bearer sk-...`）。

> 🔴 **自動化撈 token 時要精準走這個路徑，不要泛抓檔內第一個 `sk-`**。
> 2026-06-13 就是泛抓撈到別的 key，害 fetch 401，盲猜了兩輪才發現。

## 🔴 Transport 升級踩坑（2026-06-13）

**自寫 HTTP client 必知；透過 MCP 工具呼叫的話用法不變。**

1. **工具名去掉 prefix** — `opendata-` / `twtools-` 前綴拿掉，直接用 `query_rows` / `search_datasets`。
   舊名 `opendata-query_rows` 會回 unknown tool。
2. **要帶 session id** — `initialize` 的 response header 帶 `Mcp-Session-Id`，後續每個請求都要回帶，
   否則 400 Missing session ID。
3. **`notifications/initialized` 回 202 Accepted**（無 body）——這是正常的，別當失敗處理。
4. **HTTP client 不要吞 status** — 非 200/202 一律 raise 並帶上 body。
   否則錯誤被吞成籠統的 "no valid response"，只能盲猜。（已修進 `scripts/fetch_pcc.py`。）

## 可用工具

- `query_rows` / `search_datasets` / `get_dataset` — data.gov.tw 資料集（含專利、國考、判決書）
- 台灣工具：統編／身分證驗證、公司登記、地址正規化、民國西元轉換、機關代碼…

## `pcc-tender` 資料集

政府電子採購網 web.pcc.gov.tw 的**官方半月公開資料 mirror**。

| 項 | 值 |
|---|---|
| 範圍 | 2015-04 → 今 |
| 筆數 | 16 萬+ |
| 欄位 | 21 |
| Cloudflare | **無 403**（g0v 那個會擋 Actions IP，這正是當初遷移的理由） |

### `query_rows` 用法

```
query_rows(dataset_id, where=<原生 SQL WHERE>, columns=[...], limit=N)
```

- 中文欄名要加雙引號
- `award_price` 是 **VARCHAR**，比大小要先 cast

### 🔴 踩坑①：`offset` 帶 WHERE 時被忽略

`offset` 0 / 500 / 1000 回**完全相同的列** → **不能用 offset 分頁**。

**替代做法：按月切窗 + 高 limit**。pcc 每月軟體類僅 70–300 筆，遠低於單次約 5000 筆上限，
一次撈全即可；跨窗用 `seen` set 去重。

### 🟡 踩坑②：資料本身的 caveat

- **無「預算金額」欄**——招標公告本來就不含金額
- `category` 只有粗分類（工程／財物／勞務），**無細分碼**
- `agency_county_code` **僅決標公告有**
- `detail_url` 多為空（退而用 Google 搜尋）
- `not_obtain_supp_name`（未得標廠商）填充率低 → **推不出穩定的「真得標率」**
- **決標涵蓋率 2022 年中才完整**（2022-06 從每月約 120 筆跳到 700+）
  → 早年偏少，**跨年趨勢／YoY 要從 2022H2 之後看才準**

## 相關

- 消費者：`scripts/fetch_pcc.py`（原 weekly Actions 自動跑，2026-08-04 起停用）
- 另一個也碰台灣政府資料的專案：`jooca-tw/project_corpus_ai`（主權 AI）
- 退役決議：`Hyweb-JayKao/gov-bid-watch#22`、FLUX#169

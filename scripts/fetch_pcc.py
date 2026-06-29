"""pcc-tender fetcher via TwinkleAI opendata MCP（取代 g0v fetch_bids.py）。

資料源：TwinkleAI hub → dataset `pcc-tender`
  = 行政院公共工程委員會 政府電子採購網 web.pcc.gov.tw 官方半月公開資料 mirror
    （2015-04 起、16 萬+ 筆、21 欄、無 Cloudflare 403）。

設計：純 HTTP（JSON-RPC over SSE），**不依賴 Claude Code**，launchd 可直接跑。
token 走環境變數 `TWINKLE_API_KEY`（不寫死、不進 git）。

用法：
    export TWINKLE_API_KEY=sk-xxxx
    python scripts/fetch_pcc.py --since 2026-03-01 --until 2026-04-23 --out data/bids_pcc_sample.csv
    python scripts/fetch_pcc.py --days 14 --out data/weekly.csv      # 週度增量
    python scripts/fetch_pcc.py --since 2015-04-01 --out data/bids_pcc_full.csv   # 一次性 backfill

輸出 schema 對齊現有 bids.csv（date/unit_name/unit_id/type/title/category/budget/
award_amount/awarded_at/companies/job_number/url）+ pcc 額外欄（notice_date/
award_way/county/county_code/town_code/contact_person/contact_phone/losing_supplier）。
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# 軟體開發類過濾規則沿用 g0v fetcher（單一事實源，不重複維護）
from fetch_bids import BLACKLIST, KEYWORDS, pre_filter  # noqa: E402
from freshness import valid_batch_key  # noqa: E402 — 合法批次日期段（issue #22 方案 A）


# ---------- 暫時性錯誤 → 觸發 retry（永久性錯誤不重試，免燒配額）----------
class TransientHTTPError(RuntimeError):
    """閘道層間歇錯誤（裸 nginx 401 / 5xx / timeout）→ 值得 retry。

    與 app 層 JSON-RPC error 區分：後者是邏輯錯（工具名/SQL/配額耗盡），
    retry 無用，由 query_rows 另行 raise RuntimeError 不進這條。
    """


# 401 = TwinkleAI 閘道間歇抖動（回裸 nginx 頁、非 JSON-RPC 認證錯，run 歷史呈
#       ✅❌✅❌ 間歇 → 非 key 死掉）；5xx = 上游暫時不可用；皆暫時性值得 retry。
RETRY_STATUS = frozenset({401, 429, 500, 502, 503, 504})

# retry 上限 5 次嘗試（首發 + 4 retry），指數 backoff 1→2→4→8s（封頂 10s），
# 設上限避免閘道持續 401 時無限重試燒配額/CI 時間（job timeout 10 分鐘內收斂）。
_RETRY_KW = dict(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(
        (TransientHTTPError, requests.Timeout, requests.ConnectionError)
    ),
    reraise=True,
)

ENDPOINT = "https://api.twinkleai.tw/mcp/"
DATASET = "pcc-tender"
# ⚠️ query_rows 的 offset 帶 WHERE 時會被忽略（實測 offset 0/500/1000 回傳相同），
#    且單次最多回 ~5000 列 → 不能用 offset 分頁。改按「月」切窗，每月軟體類
#    約 70-300 筆（遠低於上限），一次撈全、跨月用 seen set 去重。
MONTH_LIMIT = 5000

# pcc 只給粗分類；軟體類保留勞務類 + 財物類（工程類整批排除）
KEEP_ATTR = ("勞務類", "財物類")

# 內政部縣市代碼 → 名稱（agency_county_code 前 2-5 碼）
COUNTY_CODE = {
    "63000": "臺北市", "64000": "高雄市", "65000": "新北市", "66000": "臺中市",
    "67000": "臺南市", "68000": "桃園市", "10002": "宜蘭縣", "10004": "新竹縣",
    "10005": "苗栗縣", "10007": "彰化縣", "10008": "南投縣", "10009": "雲林縣",
    "10010": "嘉義縣", "10013": "屏東縣", "10014": "臺東縣", "10015": "花蓮縣",
    "10016": "澎湖縣", "10017": "基隆市", "10018": "新竹市", "10020": "嘉義市",
    "09007": "連江縣", "09020": "金門縣",
}

# 要從 pcc-tender 撈的欄位
# filename（issue #22 方案 A）：批次檔名（如 tender_20260402.xml），唯一可靠的
#   「發布批次」識別——date 是公告/截止日（可未來），不能當批次/新鮮度依據。
COLS = [
    "date", "announcement_type", "title", "agency", "agency_id", "job_number",
    "companies", "detail_url", "notice_date", "procurement_type", "procurement_attr",
    "award_way", "award_price", "contact_phone", "contact_person",
    "agency_county_code", "agency_town_code", "not_obtain_supp_name", "filename",
]


# ---------- MCP HTTP client（JSON-RPC over SSE）----------
class MCP:
    def __init__(self, token):
        self.s = requests.Session()
        self.h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._id = 0
        self._post({"jsonrpc": "2.0", "id": self._next(), "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "gov-bid-watch", "version": "1.0"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _next(self):
        self._id += 1
        return self._id

    @retry(**_RETRY_KW)
    def _post(self, payload):
        # @retry：閘道層間歇 401/5xx/timeout 自動指數 backoff 重試（見 _RETRY_KW）。
        # 每次重試重新發 POST，session header（含 Mcp-Session-Id）沿用。
        try:
            r = self.s.post(ENDPOINT, headers=self.h, json=payload, timeout=120)
        except (requests.Timeout, requests.ConnectionError):
            # 連線層暫時性失敗 → 原樣往上拋，由 @retry 攔截重試
            raise
        r.encoding = "utf-8"
        # MCP streamable HTTP（2025 transport）：initialize 的 response header 帶
        # Mcp-Session-Id，後續所有請求必須回帶，否則 server 回 400 Missing session ID。
        # （2026-06-13 TwinkleAI transport 升級踩過）
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            self.h["Mcp-Session-Id"] = sid
        # 不吞 HTTP 錯誤：非 200 直接 raise 帶 body 摘要（避免下游收到籠統的
        # "no valid response" 而盲猜根因——2026-06-13 token/工具名 debug 教訓）
        # 200 = 有 body 的回應；202 = notification 被接受（無 body，正常）
        if r.status_code not in (200, 202):
            msg = f"HTTP {r.status_code} from {ENDPOINT}: {r.text[:300]}"
            # 暫時性狀態（裸 nginx 401 閘道抖動 / 5xx / 429）→ 觸發 retry；
            # 其餘（如 400 session 錯、403 永久拒）→ 永久性錯，不重試直接 raise。
            if r.status_code in RETRY_STATUS:
                raise TransientHTTPError(msg)
            raise RuntimeError(msg)
        out = []
        for line in r.text.splitlines():
            if line.startswith("data:"):
                try:
                    out.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
        return out

    def query_rows(self, where, columns, limit, offset=0, retries=4,
                   order_by="date DESC", group_by=None):
        rid = self._next()
        args = {"dataset_id": DATASET, "where": where, "columns": columns,
                "limit": limit, "offset": offset, "order_by": order_by}
        if group_by:
            args["group_by"] = group_by
        last_res = None
        for i in range(retries):
            # 工具名 = query_rows（TwinkleAI 2026 改版已去掉 opendata- prefix；
            # 用舊名 server 回 unknown tool → 解析不到 → 籠統失敗，2026-06-13 踩過）
            res = self._post({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                              "params": {"name": "query_rows", "arguments": args}})
            last_res = res
            for m in res:
                if m.get("id") == rid:
                    txt = "".join(x.get("text", "") for x in m.get("result", {}).get("content", [])
                                  if x.get("type") == "text")
                    d = json.loads(txt)
                    if "error" in d:
                        raise RuntimeError(f"query_rows error: {d['error']}")
                    return d
            time.sleep(1 + i * 2)
        # raise 時帶最後一批訊息線索（不再盲猜：是工具名錯/SSE 格式變/限流）
        raise RuntimeError(
            f"query_rows: no valid response after {retries} retries; "
            f"last batch={len(last_res or [])} msgs, sample={str(last_res)[:300]}")


def _kw_clause():
    """title 正向關鍵字的 SQL ILIKE OR（DB 端粗篩，減少傳輸；細篩仍在 python）。"""
    uniq = sorted({k for k in KEYWORDS if k.strip()})
    return " OR ".join(f"title ILIKE '%{k}%'" for k in uniq)


def _to_ymd(s):
    """'2026-03-31' → '20260331'（對齊既有 bids.csv 的 %Y%m%d）。"""
    if not s:
        return ""
    return str(s).replace("-", "").strip()[:8]


def _to_int(s):
    try:
        return int(float(str(s).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _county(code):
    if not code:
        return ""
    c = str(code).strip()
    return COUNTY_CODE.get(c) or COUNTY_CODE.get(c[:5]) or ""


def map_row(rec):
    """pcc-tender row dict → 既有 bids.csv schema + 額外欄。"""
    job = rec.get("job_number") or ""
    title = rec.get("title") or ""
    detail = rec.get("detail_url")
    # detail_url 多為空 → 退回 Google 搜尋（沿用既有 app 行為）
    if detail and str(detail).strip().lower() not in ("none", ""):
        url = str(detail).strip()
    else:
        from urllib.parse import quote_plus
        url = f"https://www.google.com/search?q={quote_plus(str(job) + ' ' + title)}"
    return {
        "date": _to_ymd(rec.get("date")),
        "unit_name": rec.get("agency") or "",
        "unit_id": rec.get("agency_id") or "",
        "type": rec.get("announcement_type") or "",
        "title": title,
        "category": rec.get("procurement_attr") or "",      # 粗分類（勞務類/財物類）
        "budget": "",                                        # pcc 招標公告不揭露預算 → 無
        "award_amount": _to_int(rec.get("award_price")) or "",
        "awarded_at": _to_ymd(rec.get("date")),
        "companies": rec.get("companies") or "",
        "job_number": job,
        "url": url,
        # --- pcc 額外欄（既有 app 忽略，新面板可用）---
        "notice_date": _to_ymd(rec.get("notice_date")),
        "award_way": rec.get("award_way") or "",
        "county": _county(rec.get("agency_county_code")),
        "county_code": rec.get("agency_county_code") or "",
        "town_code": rec.get("agency_town_code") or "",
        "contact_person": rec.get("contact_person") or "",
        "contact_phone": rec.get("contact_phone") or "",
        "losing_supplier": rec.get("not_obtain_supp_name") or "",
        "filename": rec.get("filename") or "",   # 批次識別（issue #22 方案 A）
    }


def _month_windows(since, until):
    """[(start,end), ...] 逐月（含跨年），yyyy-mm-01 ~ 該月底。"""
    s = datetime.strptime(since, "%Y-%m-%d").replace(day=1)
    u = datetime.strptime(until, "%Y-%m-%d")
    wins = []
    cur = s
    while cur <= u:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)  # 下月 1 號
        end = min(nxt - timedelta(days=1), u)
        wins.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = nxt
    return wins


def pick_latest_batch_keys(filenames, n):
    """從一堆 filename 取最新 n 個不同批次日期段（'YYYYMM0H'，新→舊）。

    純函式（無網路）：跨 tender_/award_ 前綴統一成日期段、**只取合法批次**（擋
    half 03 / 月 13 等髒值，codex #3）、去重再排序。
    """
    keys = {bk for f in filenames if (bk := valid_batch_key(f))}
    return sorted(keys, reverse=True)[:n]


def latest_batch_keys(mcp, n):
    """查資料源最新 n 個批次日期段（issue #22 方案 A）。

    group_by filename 取所有檔名（半月批次數量有限、遠低於 5000），再抽日期段。
    """
    d = mcp.query_rows("filename IS NOT NULL", ["filename"], MONTH_LIMIT,
                       order_by="filename DESC", group_by=["filename"])
    cols, rows = d.get("columns", []), d.get("rows", [])
    fi = cols.index("filename") if "filename" in cols else 0
    files = [r[fi] for r in rows if r]
    return pick_latest_batch_keys(files, n)


def fetch_batches(token, n_batches):
    """抓資料源最新 n_batches 個批次的軟體類案子（issue #22 方案 A）。

    取代「公告日最近 N 天」窗：資料源永遠落後 ~2 月、date 還可能是未來/截止日，
    用公告日窗結構性抓不到。改以批次檔（filename）為錨抓最新幾批。
    """
    mcp = MCP(token)
    kw = _kw_clause()
    keys = latest_batch_keys(mcp, n_batches)
    print(f"=== fetch pcc-tender 最新 {n_batches} 批次：{keys} ===", file=sys.stderr)
    rows, seen, dropped_bl = [], set(), 0
    for bk in keys:
        # 同一批次跨 tender_/award_ 兩個檔名 → 用日期段 ILIKE 一網打盡
        where = (f"filename ILIKE '%{bk}%' "
                 f"AND procurement_attr IN ('勞務類','財物類') AND ({kw})")
        d = mcp.query_rows(where, COLS, MONTH_LIMIT, order_by="filename DESC")
        cols, batch = d.get("columns", []), d.get("rows", [])
        if len(batch) >= MONTH_LIMIT:
            print(f"⚠️ 批次 {bk} 回傳達上限 {MONTH_LIMIT}，可能截斷", file=sys.stderr)
        added = 0
        for r in batch:
            rec = dict(zip(cols, r))
            if not pre_filter(rec.get("title") or ""):
                dropped_bl += 1
                continue
            key = (rec.get("agency_id") or rec.get("agency"),
                   rec.get("job_number"), rec.get("filename"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(map_row(rec))
            added += 1
        print(f"[批次 {bk}] raw {len(batch)} +{added} (total {len(rows)}, bl drop {dropped_bl})",
              file=sys.stderr)
        time.sleep(0.2)
    return rows


def fetch(since, until, token):
    mcp = MCP(token)
    kw = _kw_clause()
    rows, seen = [], set()
    dropped_bl = 0
    wins = _month_windows(since, until)
    for i, (ws, we) in enumerate(wins, 1):
        where = (f"date >= '{ws}' AND date <= '{we}' "
                 f"AND procurement_attr IN ('勞務類','財物類') AND ({kw})")
        d = mcp.query_rows(where, COLS, MONTH_LIMIT)
        cols = d.get("columns", [])
        batch = d.get("rows", [])
        if len(batch) >= MONTH_LIMIT:
            print(f"⚠️ {ws} 回傳達上限 {MONTH_LIMIT}，可能截斷（需再細切）", file=sys.stderr)
        added = 0
        for r in batch:
            rec = dict(zip(cols, r))
            title = rec.get("title") or ""
            if not pre_filter(title):  # 細篩：python 端套黑名單
                dropped_bl += 1
                continue
            key = (rec.get("agency_id") or rec.get("agency"), rec.get("job_number"), rec.get("date"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(map_row(rec))
            added += 1
        print(f"[{i}/{len(wins)} {ws}] raw {len(batch)} +{added} (total {len(rows)}, bl drop {dropped_bl})",
              file=sys.stderr)
        time.sleep(0.2)
    return rows


# 輸出 csv 固定欄位（= map_row 的 key 順序）。0 筆時也用它寫 header-only，
# 避免下游 merge/watcher 找不到檔——daily 高頻場景當天常 0 筆新案（2026-06-13 踩過：
# pcc 半月公開資料近期窗常 0 筆，no-rows 不寫檔 → merge step 失敗）
OUT_FIELDS = [
    "date", "unit_name", "unit_id", "type", "title", "category", "budget",
    "award_amount", "awarded_at", "companies", "job_number", "url",
    "notice_date", "award_way", "county", "county_code", "town_code",
    "contact_person", "contact_phone", "losing_supplier", "filename",
]


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tag = " (header-only, 0 筆)" if not rows else ""
    print(f"wrote {len(rows)} rows -> {path}{tag}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest-batches", type=int, default=None,
                    help="抓最新 N 個發布批次（issue #22 方案 A；每日跑用這個，"
                         "取代 --days 公告日窗）")
    ap.add_argument("--days", type=int,
                    help="抓過去 N 天公告日（backfill/相容用；新案偵測請改 --latest-batches）")
    ap.add_argument("--since", help="起日 YYYY-MM-DD（backfill 用）")
    ap.add_argument("--until", help="迄日 YYYY-MM-DD（預設今天）")
    ap.add_argument("--out", default="data/weekly.csv")
    ap.add_argument("--token", default=os.environ.get("TWINKLE_API_KEY", ""))
    args = ap.parse_args()

    if not args.token:
        sys.exit("缺 token：設環境變數 TWINKLE_API_KEY 或傳 --token")

    # 批次模式（每日跑預設路徑）：以發布批次為錨，不受官方 2 月延遲影響
    if args.latest_batches:
        rows = fetch_batches(args.token, args.latest_batches)
        write_csv(rows, args.out)
        return

    # 公告日窗模式（backfill / 一次性回補；不適合每日新案偵測）
    until = args.until or datetime.now().strftime("%Y-%m-%d")
    if args.since:
        since = args.since
    elif args.days:
        since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    else:
        sys.exit("需指定 --latest-batches、--since 或 --days")

    print(f"=== fetch pcc-tender {since} ~ {until} ===", file=sys.stderr)
    rows = fetch(since, until, args.token)
    write_csv(rows, args.out)


if __name__ == "__main__":
    main()

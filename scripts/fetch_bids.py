"""
g0v 標案抓取 v2：黑名單預濾 + tender endpoint 取分類與金額。

用法：
    python fetch_bids.py --days 30 --out ../data/bids.csv
    python fetch_bids.py --days 30 --no-detail --out ../data/bids_fast.csv
"""
import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import quote

import requests

API = "https://pcc-api.openfun.app/api"

# 加 User-Agent 避免 GitHub Actions IP 被 API 當 bot 擋（本機 requests 預設 UA 通常 OK，雲端被擋）
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, */*",
})

# 正向關鍵字（title 命中才算候選）
KEYWORDS = [
    "系統", "軟體", "資訊", "網站", "APP", "App", "app", "應用程式",
    "平台", "平臺", "維運", "數位", "資料庫", "雲端", "AI", "人工智慧",
    "電腦", "網路", "資安", "後臺", "前臺", "MIS", "大數據",
]

# 黑名單（title 命中就排除 — 優先級高於關鍵字）
BLACKLIST = [
    "工程", "營造", "建築", "建物", "道路", "舖設", "鋪設",
    "橋樑", "管線", "庫房", "場址", "步道", "站房", "建造物",
    "候車", "宿舍", "廚藝", "植栽", "景觀", "下水道", "污水",
    "電力", "機房冷氣", "空調", "消防", "耐震", "屋頂",
    "車棚", "車道", "停車場", "隔音", "外牆", "鋼構",
    "除濕", "鍋爐", "逆洗", "機電", "燈具",
    # 軍武排除
    "火力打擊", "飛彈", "火砲", "彈藥", "軍艦", "戰機", "魚雷", "火力",
    # 純水電/線路類
    "線路架設", "佈線工程", "配線工程",
]

# 保留的分類（從 brief.category）
KEEP_CATEGORY_PREFIX = ("勞務類", "財物類4")  # 財物類 4xxx 為資訊設備


def pre_filter(title: str) -> bool:
    if not title:
        return False
    if any(b in title for b in BLACKLIST):
        return False
    return any(k in title for k in KEYWORDS)


def list_by_date(yyyymmdd: str):
    r = SESSION.get(f"{API}/listbydate?date={yyyymmdd}", timeout=30)
    r.raise_for_status()
    return r.json()


def get_tender(unit_id: str, job_number: str, retries: int = 6):
    url = f"{API}/tender?unit_id={unit_id}&job_number={quote(str(job_number))}"
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** i)
                continue
            r.raise_for_status()
            data = r.json()
            # API 限速時會靜默回 200 + 空 records，需當成 retry
            if len(data.get("records", [])) == 0 and i < retries - 1:
                time.sleep(1 + i * 2)
                continue
            time.sleep(0.3)  # per-call rate limit
            return data
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(1 + i)
    return {}


_AMOUNT_RE = re.compile(r"([\d,]+)\s*元")


def parse_amount(s):
    if not s:
        return None
    m = _AMOUNT_RE.search(str(s))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def extract_from_tender(tender_json: dict, target_filename: str):
    """從 tender records 裡找對應公告，取 category / 預算 / 決標金額。"""
    out = {"category": None, "budget": None, "award_amount": None, "awarded_at": None}
    for rec in tender_json.get("records", []):
        brief = rec.get("brief") or {}
        detail = rec.get("detail") or {}
        if brief.get("category") and not out["category"]:
            out["category"] = brief["category"]
        # 預算金額
        for k, v in detail.items():
            if "預算金額" in k and "是否" not in k:
                amt = parse_amount(v)
                if amt:
                    out["budget"] = amt
                    break
        # 決標金額
        for k, v in detail.items():
            if "決標金額" in k or "總決標金額" in k:
                amt = parse_amount(v)
                if amt:
                    out["award_amount"] = amt
                    out["awarded_at"] = rec.get("date")
                    break
    return out


def flatten(rec, extra=None):
    brief = rec.get("brief") or {}
    companies = (brief.get("companies") or {}).get("names", [])
    row = {
        "date": rec.get("date"),
        "unit_name": rec.get("unit_name"),
        "unit_id": rec.get("unit_id"),
        "type": brief.get("type"),
        "title": brief.get("title"),
        "category": None,
        "budget": None,
        "award_amount": None,
        "awarded_at": None,
        "companies": "|".join(companies) if companies else "",
        "job_number": rec.get("job_number"),
        "url": "https://pcc-api.openfun.app" + (rec.get("url") or ""),
    }
    if extra:
        row.update({k: v for k, v in extra.items() if v is not None})
    return row


def fetch_by_days(days: int, fetch_detail: bool = True):
    seen = set()
    candidates = []  # pre-filter 通過的
    today = datetime.now()
    for i in range(days):
        d = today - timedelta(days=i)
        ymd = d.strftime("%Y%m%d")
        try:
            data = list_by_date(ymd)
        except Exception as e:
            print(f"[date {ymd}] error: {e}", file=sys.stderr)
            continue
        kept = 0
        for rec in data.get("records", []):
            key = (rec.get("unit_id"), rec.get("job_number"), rec.get("date"))
            if key in seen:
                continue
            title = (rec.get("brief") or {}).get("title") or ""
            if not pre_filter(title):
                continue
            seen.add(key)
            candidates.append(rec)
            kept += 1
        print(f"[date {ymd}] kept {kept} (total candidates {len(candidates)})", file=sys.stderr)
        time.sleep(0.3)

    if not fetch_detail:
        return [flatten(r) for r in candidates]

    # 只抓「決標公告」detail（歷史金額；招標中暫不抓）
    detail_targets = [r for r in candidates if ((r.get("brief") or {}).get("type") or "") == "決標公告"]
    skip_records = [r for r in candidates if r not in detail_targets]
    print(f"--- fetching tender detail for {len(detail_targets)} 決標公告 (跳過 {len(skip_records)}) ---", file=sys.stderr)
    candidates = detail_targets
    out = []
    dropped_by_category = 0
    done = 0

    def work(rec):
        try:
            tj = get_tender(rec.get("unit_id"), rec.get("job_number"))
            extra = extract_from_tender(tj, rec.get("filename"))
            return rec, extra, None
        except Exception as e:
            return rec, None, str(e)

    errors = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(work, r) for r in candidates]
        for fut in as_completed(futures):
            done += 1
            rec, extra, err = fut.result()
            if err:
                errors += 1
                out.append(flatten(rec))
                continue
            out.append(flatten(rec, extra))
            if done % 200 == 0:
                print(f"  [{done}/{len(candidates)}] kept {len(out)} errors {errors}", file=sys.stderr)

    # 補回沒抓 detail 的記錄（非決標類）
    for r in skip_records:
        out.append(flatten(r))
    print(f"--- final: {len(out)} kept ({len(detail_targets)} with detail, {len(skip_records)} skipped), {errors} errors ---", file=sys.stderr)
    return out


def write_csv(rows, path):
    if not rows:
        print("no rows", file=sys.stderr)
        return
    fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-detail", action="store_true", help="跳過 tender 詳情（不取金額/分類）")
    ap.add_argument("--out", default="bids.csv")
    args = ap.parse_args()
    rows = fetch_by_days(args.days, fetch_detail=not args.no_detail)
    write_csv(rows, args.out)


if __name__ == "__main__":
    main()

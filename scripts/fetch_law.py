"""
同步政府採購法（全國法規資料庫 A0030057）條文，輸出結構化 JSON。

用法：
    python scripts/fetch_law.py

輸出：data/law/procurement_act.json

僅依賴標準庫（urllib + re），與既有 fetch_bids.py 一致風格。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

import requests

LAW_CODE = "A0030057"
LAW_NAME = "政府採購法"
SOURCE_URL = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={LAW_CODE}"
UA = "Mozilla/5.0 (gov-bid-watch fetch_law.py)"

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "law" / "procurement_act.json"


def fetch_html(url: str) -> str:
    """抓取 HTML；law.moj.gov.tw 憑證缺 Subject Key Identifier，
    需放寬 OpenSSL 3.x 的 VERIFY_X509_STRICT。"""
    import ssl

    import urllib3
    from requests.adapters import HTTPAdapter

    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT

    class LegacyAdapter(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            kw["ssl_context"] = ctx
            return super().init_poolmanager(*a, **kw)

    s = requests.Session()
    s.mount("https://", LegacyAdapter())
    r = s.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


# 法條容器：每一段以 <h3 class="char-2"> 章名起頭，後接多個 row（條文）
CHAPTER_RE = re.compile(r'<div class="h3 char-2">\s*(第\s*[一二三四五六七八九十百]+\s*章[^<]*?)\s*</div>')
ROW_SPLIT_RE = re.compile(r'<div class="row">')
ARTICLE_HEAD_RE = re.compile(
    r'name="([0-9\-]+)">\s*第\s*[0-9\- ]+?\s*條\s*</a>', re.S
)
LINE_RE = re.compile(r'<div class="line-[^"]*"[^>]*>(.*?)</div>', re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
DATE_RE = re.compile(
    r"修正日期[：:].*?(\d{1,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", re.S
)


def clean_text(s: str) -> str:
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    return WS_RE.sub("", s).strip()


def parse_amended_date(h: str) -> str | None:
    m = DATE_RE.search(h)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):03d}-{int(mo):02d}-{int(d):02d}"


def parse_articles(h: str) -> list[dict]:
    """以章為單位切片，逐章解析條文，保留章節歸屬。"""
    chapter_marks = [(m.start(), clean_text(m.group(1))) for m in CHAPTER_RE.finditer(h)]
    if not chapter_marks:
        chapter_marks = [(0, "")]
    chapter_marks.append((len(h), ""))

    articles: list[dict] = []
    for i in range(len(chapter_marks) - 1):
        start, name = chapter_marks[i]
        end = chapter_marks[i + 1][0]
        segment = h[start:end]
        for chunk in ROW_SPLIT_RE.split(segment)[1:]:
            head = ARTICLE_HEAD_RE.search(chunk)
            if not head:
                continue
            art_no = head.group(1).strip()
            paragraphs = [clean_text(p) for p in LINE_RE.findall(chunk)]
            paragraphs = [p for p in paragraphs if p]
            articles.append(
                {
                    "article_no": art_no,
                    "chapter": name,
                    "content": "\n".join(paragraphs),
                    "paragraphs": paragraphs,
                }
            )
    return articles


def article_sort_key(art_no: str) -> tuple[int, int]:
    """'26-2' → (26, 2); '5' → (5, 0)。"""
    if "-" in art_no:
        a, b = art_no.split("-", 1)
        return (int(a), int(b))
    return (int(art_no), 0)


def build_dataset(h: str) -> dict:
    articles = parse_articles(h)
    articles.sort(key=lambda a: article_sort_key(a["article_no"]))
    return {
        "law_name": LAW_NAME,
        "law_code": LAW_CODE,
        "source_url": SOURCE_URL,
        "amended_date": parse_amended_date(h),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "article_count": len(articles),
        "articles": articles,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--dry-run", action="store_true", help="只印 metadata 不寫檔")
    args = ap.parse_args()

    h = fetch_html(SOURCE_URL)
    data = build_dataset(h)

    print(
        f"[fetch_law] {data['law_name']} 修正日期={data['amended_date']} "
        f"條文數={data['article_count']}",
        file=sys.stderr,
    )

    if not data["articles"]:
        print("[fetch_law] ERROR: 0 articles parsed — HTML 結構可能已變更", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(data["articles"][0], ensure_ascii=False, indent=2))
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[fetch_law] wrote {out} ({out.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

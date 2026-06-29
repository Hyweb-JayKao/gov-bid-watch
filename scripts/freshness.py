"""資料新鮮度檢查 — 偵測上游資料源「斷糧」（issue #22，根因翻轉後重做）。

問題背景（已實證翻轉）：官方政府電子採購網開放資料**天生有 ~2 個月發布延遲**
（官方頁逐字：「每個月 5 號會產出 2 個月前的資料」），且資料以「半月批次檔」
為單位發布，檔名如 `tender_20260402.xml` / `award_20260402.xml`（末 2 碼＝
半月期別 01/02，非日）。

→ 因此「公告日距今」**量錯對象**：健康狀態下最新資料本就 ~60 天舊，用
  「距今 14 天」會天天誤報。前一版（PR #23 初稿）的日期距今門檻已作廢。

判斷依據改成 **批次發布節奏**：
- **批次識別**＝檔名 `filename` 的 8 碼日期段 `YYYYMM0H`（跨 tender_/award_
  前綴統一用日期段比較，避免前綴字典序混比）。
- **新鮮度**＝資料源「最新批次」是否落後「依官方節奏應有的最新批次」超過寬限。
  官方每月約 5 號發布 2 月前整月（兩個半月批次）→ 預期最新批次 = 今天往前
  2 個月（5 號前保守抓 3 個月）的下半月。落後超過 `grace_periods` 個半月期 →
  判定真斷糧（mirror/ETL 沒跟上），非正常延遲。

實證（2026-06-29）：TwinkleAI 最新批次 `tender_20260302`（3 月下半月）、官方已到
`tender_20260402`（4 月下半月）→ 落後 2 個半月期 → 正當觸發告警（非誤報）。
"""
import re
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
    _TPE = ZoneInfo("Asia/Taipei")
except Exception:  # 極端環境無 tzdata → 退回 naive（CI 已設 TZ）
    _TPE = None

_BATCH_RE = re.compile(r"(\d{8})")


def taipei_today() -> date:
    """以 Asia/Taipei 為準的今天（issue #22 #6）。

    CI runner 多為 UTC，台北凌晨排程用 UTC date 會差 1 天、在發布日 5 號邊界
    附近誤判。一律用台北日界線。
    """
    if _TPE is not None:
        return datetime.now(_TPE).date()
    return date.today()


# ---------- 批次識別 ----------
def batch_key(filename: str) -> str:
    """從 filename 取 8 碼批次日期段 `YYYYMM0H`；取不到回 ''。

    'tender_20260402.xml' / 'award_20260402.xml' 都 → '20260402'（跨前綴統一）。
    用日期段比較才不會把 'award_...' 與 'tender_...' 的前綴字典序混進來。
    """
    if not filename:
        return ""
    m = _BATCH_RE.search(str(filename))
    return m.group(1) if m else ""


def batch_period(bkey: str):
    """'YYYYMM0H' → 連續半月期序號（int）；非法回 None。

    序號＝year*24 + (month-1)*2 + (half-1)，相鄰半月差 1，可直接相減比節奏。
    末 2 碼 half 僅接受 01/02（半月期別），其餘視為髒值。
    """
    if not bkey or len(bkey) != 8 or not bkey.isdigit():
        return None
    y, mo, half = int(bkey[:4]), int(bkey[4:6]), int(bkey[6:8])
    if not (1 <= mo <= 12 and half in (1, 2)):
        return None
    return y * 24 + (mo - 1) * 2 + (half - 1)


def period_to_key(period) -> str:
    """半月期序號 → 'YYYYMM0H'（display 用）；None → ''。"""
    if period is None:
        return ""
    y, rem = divmod(period, 24)
    mo = rem // 2 + 1
    half = rem % 2 + 1
    return f"{y:04d}{mo:02d}{half:02d}"


def latest_batch(rows: list) -> str:
    """rows 中最大的批次日期段（'YYYYMM0H'）；無有效批次回 ''。"""
    keys = [bk for r in rows if (bk := batch_key(r.get("filename", "")))]
    return max(keys) if keys else ""


def expected_latest_batch_period(today: date = None):
    """依官方節奏，今天「應該」已有的最新批次期序號。

    官方每月 5 號發布 2 個月前整月（含上/下兩個半月批次）→ 預期最新到
    「今天 - 2 個月」的下半月（half=2）。今天 < 5 號時保守抓「-3 個月」，
    避免在發布日前一兩天就誤報「沒出新批次」。
    """
    today = today or taipei_today()
    months_back = 2 if today.day >= 5 else 3
    y, m = today.year, today.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return y * 24 + (m - 1) * 2 + (2 - 1)   # 該月下半月


def check_batch_freshness(rows: list, today: date = None,
                          grace_periods: int = 1) -> dict:
    """以批次節奏判斷資料源是否斷糧。

    回傳 dict：
      - stale: bool          最新批次落後預期超過 grace_periods（或完全無批次）
      - latest_batch: str    資料源最新批次 'YYYYMM0H'（無則 ''）
      - expected_batch: str  依今天節奏應有的最新批次 'YYYYMM0H'
      - lag_periods: int|None 落後幾個半月期（無批次則 None）
      - grace_periods: int   容忍幾個半月期（發布時點 jitter）

    grace_periods 預設 1：容忍落後 1 個半月期（官方某半月剛好還沒發的正常時點差），
    落後 ≥2 個半月期才判真斷糧——避免把「正常半月延遲」誤報成斷糧。
    """
    today = today or taipei_today()
    latest = latest_batch(rows)
    lp = batch_period(latest)
    exp = expected_latest_batch_period(today)
    if lp is None:
        # 完全沒有有效批次 → 視為斷糧（資料集空 / filename 全缺）
        return {"stale": True, "latest_batch": "", "expected_batch": period_to_key(exp),
                "lag_periods": None, "grace_periods": grace_periods}
    lag = exp - lp
    return {"stale": lag > grace_periods, "latest_batch": latest,
            "expected_batch": period_to_key(exp), "lag_periods": lag,
            "grace_periods": grace_periods}

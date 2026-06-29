"""資料新鮮度檢查 — 偵測上游資料源「斷糧」（issue #22）。

問題背景：daily watcher 每天只 fetch 近 N 天（`--days 2`），上游 pcc-tender
mirror 2026-04 底起停更後，每天抓回 0 筆 → `no_p0` → 靜默不發 Slack，
「斷糧無人知」。本模組讓 watcher 主動偵測「資料源最新一筆日期距今太久」。

判斷依據＝**master 資料集 `data/bids.csv` 的最大 `date`**（YYYYMMDD），
而非本輪 weekly fetch：斷糧時 weekly 為空，但 master 的最大日期會「卡」在
最後一次有料的日期，today 減它即「資料源停滯天數」。供料恢復後 master
最大日期會隨 merge 前進，停滯天數自然歸零 → 不誤報。

閾值 N：見 watcher.py FRESHNESS_DAYS 的取值理由（為何不是 brief 初估的 3–5）。
"""
from datetime import date


def _parse_yyyymmdd(s: str):
    """'20260504' -> date(2026,5,4)；非 8 碼數字回 None（容錯髒資料）。"""
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def latest_data_date(rows: list) -> str:
    """回傳 rows 中最大的 `date`（YYYYMMDD 字串）；無有效日期回 ''。

    用字串比較找最大（YYYYMMDD 字典序＝時間序），再驗證可解析，
    避免單一髒值（如 '99999999'）灌頂。
    """
    valid = [r.get("date", "") for r in rows if _parse_yyyymmdd(r.get("date", ""))]
    return max(valid) if valid else ""


def check_freshness(rows: list, threshold_days: int, today: date = None) -> dict:
    """檢查資料新鮮度。

    回傳 dict：
      - stale: bool        是否超過閾值（含「完全無有效日期」也算 stale）
      - latest_date: str   master 最新日期 YYYYMMDD（無則 ''）
      - age_days: int|None  距今天數（無有效日期則 None）
      - threshold_days: int 用的閾值
    """
    today = today or date.today()
    latest = latest_data_date(rows)
    if not latest:
        # 完全沒有有效日期 → 視為斷糧（資料集空或全髒）
        return {"stale": True, "latest_date": "", "age_days": None,
                "threshold_days": threshold_days}
    age = (today - _parse_yyyymmdd(latest)).days
    return {"stale": age > threshold_days, "latest_date": latest,
            "age_days": age, "threshold_days": threshold_days}

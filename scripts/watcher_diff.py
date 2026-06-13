"""watcher diff / 水位模組 — 找「上次 baseline 後新出現」的標案。

設計（與 merge.py 解耦）：
- merge.py 只負責去重合併進 master，不輸出 new rows（既有行為不動）。
- 本模組獨立維護一份「已見過 key 水位」state（`data/watcher_state.json`），
  每輪把 fetch 結果的 key 與水位比對，**水位裡沒有的 = 新出現**。
- key 沿用 merge 主鍵 (unit_id, job_number, date)，去重邏輯一致。
- 中止演練（brief §跑偏中止）＝把水位回退（刪掉部分 seen key），
  下一輪會把大量舊案誤判為「新出現」→ 觸發成本封頂降級 alert。

state schema:
{
  "seen_keys": ["unit_id|job_number|date", ...],   # 已推播過/已見過水位
  "last_run": "2026-06-13T10:00:00",
  "runs": [ {ts, fetched, new, pushed, watermark} ... ]  # run-log（保留近 N 筆）
}
"""
import hashlib
import json
import os
from datetime import datetime

STATE_PATH = "data/watcher_state.json"
RUNLOG_KEEP = 60  # 保留近 60 輪 run-log（每日跑 → 約 2 個月）


def row_key(row: dict) -> str:
    """sched 主鍵，對齊 merge.py PRIMARY_KEYS (unit_id, job_number, date)。

    主鍵三欄若全空（"||"），多筆不同標案會被 find_new 的 seen_this_batch
    去重成同一筆 → 漏報（issue #14 §4 0 漏報）。三欄全空時 fallback：
    用 title + unit_name 的 hash 當 key，至少讓內容不同的列各自成 key。
    """
    uid = row.get("unit_id") or row.get("agency_id") or ""
    job = row.get("job_number") or ""
    date = row.get("date") or ""
    if not (uid or job or date):
        seed = f"{row.get('title', '')}|{row.get('unit_name', '')}"
        h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        return f"fallback|{h}"
    return f"{uid}|{job}|{date}"


def load_state(path: str = STATE_PATH) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        st.setdefault("seen_keys", [])
        st.setdefault("runs", [])
        return st
    return {"seen_keys": [], "last_run": None, "runs": []}


def save_state(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # run-log 只保留近 N 筆
    state["runs"] = state.get("runs", [])[-RUNLOG_KEEP:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def find_new(rows: list, state: dict) -> list:
    """回傳水位裡沒見過的列（新出現）。不改 state（推播決策後才更新水位）。"""
    seen = set(state.get("seen_keys", []))
    new = []
    seen_this_batch = set()
    for r in rows:
        k = row_key(r)
        if k in seen or k in seen_this_batch:
            continue
        seen_this_batch.add(k)
        new.append(r)
    return new


def commit_watermark(rows: list, state: dict) -> None:
    """把本輪 fetch 的所有 key 併入水位（無論是否推播，見過就算）。"""
    seen = set(state.get("seen_keys", []))
    for r in rows:
        seen.add(row_key(r))
    state["seen_keys"] = sorted(seen)


def rollback_watermark(state: dict, n: int) -> int:
    """中止演練用：回退水位（刪掉 n 個 seen key）。回傳實際刪除數。

    刪掉後，下一輪同一批舊案會被 find_new 當成新出現 → 大量 new → 觸發封頂。
    """
    keys = state.get("seen_keys", [])
    n = min(n, len(keys))
    state["seen_keys"] = keys[n:]  # 砍掉前 n 個
    return n


def append_runlog(state: dict, fetched: int, new: int, pushed: int,
                  note: str = "") -> None:
    state.setdefault("runs", []).append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "fetched": fetched,
        "new": new,
        "pushed": pushed,
        "watermark": len(state.get("seen_keys", [])),
        "note": note,
    })
    state["last_run"] = datetime.now().isoformat(timespec="seconds")

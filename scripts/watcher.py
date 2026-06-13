"""P0 標案 watcher 主流程 — loop engineering pilot 的常駐 loop。

管線：fetch（weekly.csv 或既有 fetch_pcc）→ diff（水位找新出現）→ P0 過濾
      → 成本封頂檢查 → Slack 推播（dry-run）→ 更新水位 + run-log。

成本封頂（brief §4，loop 終止/降級錨點）：
- 單輪 P0 推播候選 > PUSH_CAP(20) → 判定規則錯/資料異常 → **不推、寫 alert**。
- 單輪耗時 > TIME_CAP_SEC(300) → kill + alert（由呼叫端/CI timeout 或本檔軟檢查）。

evaluator 全程零 LLM：diff 用字串 key、P0 用布林規則。
Slack 停在 dry-run（checkpoint #14 §7）。
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p0_rules import is_p0  # noqa: E402
from slack_notify import notify  # noqa: E402
from watcher_diff import (  # noqa: E402
    append_runlog,
    commit_watermark,
    find_new,
    load_state,
    save_state,
)

PUSH_CAP = 20          # 單輪推播上限，超過 → 降級 alert 不推
TIME_CAP_SEC = 300     # 單輪耗時上限（5 分鐘）
ALERT_DIR = "data/alerts"


def write_alert(kind: str, detail: dict) -> str:
    os.makedirs(ALERT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = os.path.join(ALERT_DIR, f"{ts}-{kind}.json")
    payload = {"ts": datetime.now().isoformat(timespec="seconds"),
               "kind": kind, **detail}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"::warning::[alert:{kind}] {detail} -> {path}", file=sys.stderr)
    return path


def read_rows(csv_path: str) -> list:
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(weekly_csv: str, state_path: str, dry_run: bool = True,
        push_cap: int = PUSH_CAP, time_cap: int = TIME_CAP_SEC) -> dict:
    """跑一輪 watcher。回傳結果 dict（含 status: ok|capped|timeout）。"""
    t0 = time.time()
    state = load_state(state_path)
    rows = read_rows(weekly_csv)

    # 1. diff：水位找新出現
    new_rows = find_new(rows, state)
    # 2. P0 布林過濾
    p0_rows = [r for r in new_rows if is_p0(r)]

    result = {"fetched": len(rows), "new": len(new_rows),
              "p0": len(p0_rows), "pushed": 0, "status": "ok", "alert": None}

    # 3. 成本封頂：推播候選過多 → 規則錯/資料異常 → 不推、alert
    if len(p0_rows) > push_cap:
        alert = write_alert("push_cap_exceeded", {
            "p0_count": len(p0_rows), "cap": push_cap,
            "hint": "可能規則過鬆或水位回退/資料異常，停下檢查，未推 Slack",
        })
        result.update(status="capped", alert=alert)
        # 水位仍前進（避免下輪重複爆量），但不推播
        commit_watermark(rows, state)
        append_runlog(state, fetched=len(rows), new=len(new_rows),
                      pushed=0, note=f"CAPPED p0={len(p0_rows)}>{push_cap}")
        save_state(state, state_path)
        return result

    # 4. 時間封頂（軟檢查；硬 kill 靠 CI step timeout）
    if time.time() - t0 > time_cap:
        alert = write_alert("time_cap_exceeded",
                            {"elapsed": round(time.time() - t0, 1), "cap": time_cap})
        result.update(status="timeout", alert=alert)
        append_runlog(state, fetched=len(rows), new=len(new_rows),
                      pushed=0, note="TIMEOUT")
        save_state(state, state_path)
        return result

    # 5. 推播（dry-run 預設）
    push_res = notify(p0_rows, dry_run=dry_run) if p0_rows else \
        {"sent": False, "count": 0, "reason": "no_p0"}
    result["pushed"] = len(p0_rows) if (push_res.get("sent") or dry_run) else 0
    result["push_reason"] = push_res.get("reason")

    # 6. 更新水位 + run-log
    commit_watermark(rows, state)
    append_runlog(state, fetched=len(rows), new=len(new_rows),
                  pushed=result["pushed"],
                  note=f"dry_run={dry_run} p0={len(p0_rows)}")
    save_state(state, state_path)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", default="data/weekly.csv", help="本輪 fetch 結果 CSV")
    ap.add_argument("--state", default="data/watcher_state.json")
    ap.add_argument("--push", action="store_true",
                    help="實際推 Slack（預設 dry-run；需 env SLACK_WEBHOOK_URL）")
    ap.add_argument("--push-cap", type=int, default=PUSH_CAP)
    args = ap.parse_args()

    res = run(args.weekly, args.state, dry_run=not args.push,
              push_cap=args.push_cap)
    print(json.dumps(res, ensure_ascii=False), file=sys.stderr)
    # capped/timeout 用非零退出碼讓 CI 標紅（但不算 fetch 失敗）
    if res["status"] in ("capped", "timeout"):
        sys.exit(2)


if __name__ == "__main__":
    main()

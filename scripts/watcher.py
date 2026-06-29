"""P0 標案 watcher 主流程 — loop engineering pilot 的常駐 loop。

管線：fetch（weekly.csv 或既有 fetch_pcc）→ diff（水位找新出現）→ P0 過濾
      → 成本封頂檢查 → Slack 推播（dry-run）→ 更新水位 + run-log。

成本封頂（brief §4，loop 終止/降級錨點）：
- 單輪 P0 推播候選 > PUSH_CAP(20) → 判定規則錯/資料異常 → **不推、寫 alert**
  （alert 含被擋 P0 完整清單，供人工補救；issue #14 §4 0 漏報）。
- 時間封頂由 CI step `timeout-minutes` 硬 kill（本檔不做軟檢查，純記憶體操作跑不到上限）。

evaluator 全程零 LLM：diff 用字串 key、P0 用布林規則。
Slack 停在 dry-run（checkpoint #14 §7）。
"""
import argparse
import csv
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freshness import check_freshness, taipei_today  # noqa: E402
from p0_rules import is_p0  # noqa: E402
from slack_notify import notify, notify_freshness  # noqa: E402
from watcher_diff import (  # noqa: E402
    append_runlog,
    commit_watermark,
    find_new,
    load_state,
    save_state,
)

PUSH_CAP = 20          # 單輪推播上限，超過 → 降級 alert 不推
ALERT_DIR = "data/alerts"

# 資料新鮮度門檻（issue #22）：master 最新 date 距今 > 此天數 → 判定上游斷糧、告警。
#
# 為何是 14 而非 brief 初估的 3–5：pcc-tender 是「官方半月公開資料」，正常供料下
# 最新日期本就會隨發布週期落後。實測健康期（2026 Jan–Apr）master 資料：
#   - 有料日多為每日/每 1–3 天一筆，
#   - 但農曆年等假期出現過最大 10 天的資料空窗（2/13→2/23），
#   - 疊加半月一次的發布節奏，下次發布前最新日期可正常落後到 ~16 天。
# 門檻設 3–5 會在每個假期/發布前空窗誤報 → 違反「正常供料不誤報」鐵則，
# 狼來了喊久就被無視＝退回靜默失敗。14 天＝大於實測最壞正常空窗(10)+裕度，
# 仍能在再次斷糧後約兩週內告警；當前已斷糧 56 天 → 立即觸發。可用 --freshness-days 調。
FRESHNESS_DAYS = 14
# 斷糧持續期間的重提間隔（天）：避免長期斷糧每天重複轟炸 Slack。
# 首次偵測立即推；之後同一停滯狀態每 N 天重提一次（最新日期變動也會重提）。
FRESHNESS_REALERT_DAYS = 3


def write_alert(kind: str, detail: dict) -> str:
    os.makedirs(ALERT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S_%f")  # 含微秒：避免同秒多 alert 覆蓋
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


def check_data_freshness(master_csv: str, state: dict, dry_run: bool,
                         freshness_days: int, realert_days: int,
                         today: date = None) -> dict:
    """偵測 master 資料源是否斷糧；stale 時推 Slack 告警（含重提節流）。

    回傳 freshness dict（check_freshness 結果再加 alerted / would_alert: bool）。
    節流：同一停滯狀態（latest_date 不變）每 realert_days 天最多重提一次；
    latest_date 變動（資料前進或回退）視為新狀態，立即重提。

    dry_run=True（issue #22 #1）：只回報「若真推會不會 alert」（would_alert），
    **不寫 alert 檔、不更新節流狀態**。否則手動 dry-run 會消耗 realert_days
    節流，把隨後的真推壓掉。
    """
    today = today or taipei_today()
    rows = read_rows(master_csv)
    fr = check_freshness(rows, freshness_days, today=today)
    fr["alerted"] = False
    fr["would_alert"] = False
    if not fr["stale"]:
        # 恢復供料 → 清掉節流紀錄，下次再斷糧能立即重提。
        # dry-run 不改 state（#1）：只在真跑時清。
        if not dry_run:
            state.pop("freshness_alert", None)
        return fr

    prev = state.get("freshness_alert") or {}
    prev_latest = prev.get("latest_date")
    prev_date = prev.get("last_alert_date")
    should = True
    if prev_latest == fr["latest_date"] and prev_date:
        # 壞掉的節流紀錄（空字串/舊格式/merge 殘留）→ 視為「無有效節流」續推（#2）
        try:
            prev_d = datetime.strptime(prev_date, "%Y-%m-%d").date()
            should = (today - prev_d).days >= realert_days
        except (ValueError, TypeError):
            should = True

    fr["would_alert"] = should
    if dry_run:
        # dry-run：印 payload 供 smoke，但不落 alert 檔、不動節流狀態（#1）
        if should:
            notify_freshness(fr["latest_date"], fr["age_days"], freshness_days,
                             dry_run=True)
        return fr

    if should:
        # 先寫 alert 檔留痕（不論最終有無推到 Slack，都要有可追的紀錄）。
        write_alert("data_freshness", {
            "source": "pcc-tender", "latest_date": fr["latest_date"],
            "age_days": fr["age_days"], "threshold_days": freshness_days,
            "hint": "上游資料源停滯/斷糧；watcher 本身正常。見 issue #22。",
        })
        res = notify_freshness(fr["latest_date"], fr["age_days"], freshness_days,
                               dry_run=dry_run)
        # ⚠️ 節流只在「真的送達 Slack」才啟動（codex 複審）：no_webhook / 送失敗
        #    若也消耗 3 天 realert 窗，告警會被靜默壓掉 → 回到「靜默斷糧」。
        #    沒送達 → 不標 alerted、不寫節流 state，下輪會重試推送。
        if not res.get("sent"):
            return fr
        state["freshness_alert"] = {"latest_date": fr["latest_date"],
                                    "last_alert_date": today.isoformat()}
        fr["alerted"] = True
    return fr


def run(weekly_csv: str, state_path: str, dry_run: bool = True,
        push_cap: int = PUSH_CAP, master_csv: str = None,
        freshness_days: int = FRESHNESS_DAYS,
        realert_days: int = FRESHNESS_REALERT_DAYS, today: date = None) -> dict:
    """跑一輪 watcher。回傳結果 dict（含 status: ok|capped）。

    時間封頂改由 CI step `timeout-minutes` 硬 kill（見 daily-watcher.yml），
    本檔不做軟檢查（純記憶體操作跑不到 300s，軟檢查是擺設；ADR D4）。

    master_csv 有給時，額外做「資料新鮮度檢查」（issue #22）：master 最新日期
    距今 > freshness_days → 推 Slack 斷糧告警。master_csv=None 時跳過（不影響
    既有 P0 推播流程與舊測試）。
    """
    state = load_state(state_path)

    # 0. 資料新鮮度檢查（issue #22）：與 P0 流程獨立，斷糧時即使 0 筆也告警。
    #    #5：master 讀取/檢查失敗（檔不存在/路徑錯/編碼錯）只降級成 warning，
    #    絕不讓既有 P0 推播流程停止——P0 是主業，新鮮度是附加守望。
    freshness = None
    if master_csv:
        try:
            freshness = check_data_freshness(master_csv, state, dry_run,
                                             freshness_days, realert_days, today=today)
        except Exception as e:  # noqa: BLE001 — 任何 master 端錯誤都不得中斷 P0
            print(f"::warning::[freshness] 新鮮度檢查失敗、已跳過（不影響 P0）：{e}",
                  file=sys.stderr)
            freshness = {"error": str(e), "stale": None, "alerted": False}

    rows = read_rows(weekly_csv)

    # 1. diff：水位找新出現
    new_rows = find_new(rows, state)
    # 2. P0 布林過濾
    p0_rows = [r for r in new_rows if is_p0(r)]

    result = {"fetched": len(rows), "new": len(new_rows),
              "p0": len(p0_rows), "pushed": 0, "status": "ok", "alert": None,
              "freshness": freshness}

    # 3. 成本封頂：推播候選過多 → 規則錯/資料異常 → 不推、alert
    #    ⚠️ 0 漏報鐵則（issue #14 §4）：capped 時水位仍前進，被擋的 P0 下輪
    #    不會再被 find_new 看到。因此 alert 必須完整記錄被擋清單，讓人能手動補救。
    if len(p0_rows) > push_cap:
        blocked = [{"title": r.get("title", ""),
                    "unit_name": r.get("unit_name", ""),
                    "job_number": r.get("job_number", "")}
                   for r in p0_rows]
        alert = write_alert("push_cap_exceeded", {
            "p0_count": len(p0_rows), "cap": push_cap,
            "hint": "可能規則過鬆或水位回退/資料異常，停下檢查，未推 Slack",
            "blocked_p0": blocked,  # 被擋的完整清單，供人工補救（水位已前進）
        })
        result.update(status="capped", alert=alert)
        # 水位仍前進（避免下輪重複爆量），但不推播
        commit_watermark(rows, state)
        append_runlog(state, fetched=len(rows), new=len(new_rows),
                      pushed=0, note=f"CAPPED p0={len(p0_rows)}>{push_cap}")
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
    ap.add_argument("--master", default=None,
                    help="master 資料集 CSV；給了才做資料新鮮度檢查（issue #22）")
    ap.add_argument("--freshness-days", type=int, default=FRESHNESS_DAYS,
                    help=f"資料最新日期距今超過此天數判定斷糧（預設 {FRESHNESS_DAYS}）")
    args = ap.parse_args()

    res = run(args.weekly, args.state, dry_run=not args.push,
              push_cap=args.push_cap, master_csv=args.master,
              freshness_days=args.freshness_days)
    print(json.dumps(res, ensure_ascii=False), file=sys.stderr)
    # capped 用非零退出碼讓 CI 標記降級（但不算 fetch 失敗）
    if res["status"] == "capped":
        sys.exit(2)


if __name__ == "__main__":
    main()

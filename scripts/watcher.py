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

from freshness import (  # noqa: E402
    batch_key,
    check_batch_freshness,
    latest_batch,
    taipei_today,
)
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

# 資料新鮮度寬限（issue #22，批次節奏版）：資料源最新「批次」落後「依官方節奏
# 應有的最新批次」超過此半月期數 → 判定上游斷糧、告警。
#
# 為何用批次而非「公告日距今」：pcc 官方天生有 ~2 個月發布延遲（每月 5 號發 2 月
# 前資料）、且以半月批次檔（filename=YYYYMM0H）為單位。健康狀態下最新資料本就
# ~60 天舊，量「公告日距今」會天天誤報。改量「最新批次有沒有如期出現」。
# grace=1：容忍落後 1 個半月期（官方某半月剛好還沒發的正常時點差），落後 ≥2 期
# 才判真斷糧。實證 2026-06-29：TwinkleAI 卡在 20260302、官方已 20260402 → 落後 2
# 期 → 正當觸發。可用 --freshness-grace 調。
FRESHNESS_GRACE_PERIODS = 1
# 斷糧持續期間的重提間隔（天）：避免長期斷糧每天重複轟炸 Slack。
# 首次偵測立即推；之後同一停滯狀態（最新批次不變）每 N 天重提一次。
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
                         grace_periods: int, realert_days: int,
                         today: date = None) -> dict:
    """偵測 master 資料源是否斷糧（批次節奏版）；stale 時推 Slack（含重提節流）。

    回傳 freshness dict（check_batch_freshness 結果再加 alerted / would_alert）。
    節流：同一停滯狀態（latest_batch 不變）每 realert_days 天最多重提一次；
    latest_batch 變動（出新批次或回退）視為新狀態，立即重提。

    dry_run=True（issue #22 #1）：只回報「若真推會不會 alert」（would_alert），
    **不寫 alert 檔、不更新節流狀態**。否則手動 dry-run 會消耗 realert_days
    節流，把隨後的真推壓掉。
    """
    today = today or taipei_today()
    rows = read_rows(master_csv)
    fr = check_batch_freshness(rows, today=today, grace_periods=grace_periods)
    fr["alerted"] = False
    fr["would_alert"] = False
    if not fr["stale"]:
        # 批次如期更新 → 清掉節流紀錄，下次再斷糧能立即重提。
        # dry-run 不改 state（#1）：只在真跑時清。
        if not dry_run:
            state.pop("freshness_alert", None)
        return fr

    prev = state.get("freshness_alert") or {}
    prev_latest = prev.get("latest_batch")
    prev_date = prev.get("last_alert_date")
    should = True
    if prev_latest == fr["latest_batch"] and prev_date:
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
            notify_freshness(fr["latest_batch"], fr["expected_batch"],
                             fr["lag_periods"], dry_run=True)
        return fr

    if should:
        # 先寫 alert 檔留痕（不論最終有無推到 Slack，都要有可追的紀錄）。
        write_alert("data_freshness", {
            "source": "pcc-tender", "latest_batch": fr["latest_batch"],
            "expected_batch": fr["expected_batch"], "lag_periods": fr["lag_periods"],
            "hint": "上游批次沒如期更新（非官方固有 2 月延遲）；watcher 本身正常。見 issue #22。",
        })
        res = notify_freshness(fr["latest_batch"], fr["expected_batch"],
                               fr["lag_periods"], dry_run=dry_run)
        # ⚠️ 節流只在「真的送達 Slack」才啟動（codex 複審）：no_webhook / 送失敗
        #    若也消耗 3 天 realert 窗，告警會被靜默壓掉 → 回到「靜默斷糧」。
        #    沒送達 → 不標 alerted、不寫節流 state，下輪會重試推送。
        if not res.get("sent"):
            return fr
        state["freshness_alert"] = {"latest_batch": fr["latest_batch"],
                                    "last_alert_date": today.isoformat()}
        fr["alerted"] = True
    return fr


def find_new_by_batch(rows: list, state: dict):
    """新案偵測改以「批次」為錨（issue #22 方案 A）。

    資料源永遠落後 ~2 個月、`date` 還可能是未來/截止日 → 不能用「公告日最近 N 天」
    當新案窗。改追「已處理過的最新批次 `last_batch`」：只把 **比 last_batch 新的
    批次** 的案子當新案，再經既有 seen_keys 去重（同批次重抓不重推）。

    回傳 (new_rows, mode, cand)：
    - mode='fallback'：rows 完全沒有批次訊號（filename 全缺，非 pcc/舊資料）→ 退回
      既有 seen_keys 水位法，向後相容（不讓無 filename 的資料整批靜默）。
    - mode='baseline'：冷啟動（state 從未記過 last_batch）→ 只設基線、不回補整個歷史
      backlog（否則首輪一次湧入數千案、必觸成本封頂），本輪不視為新案。
    - mode='batch'：正常批次偵測，cand＝比 last_batch 新的批次的列。
    """
    cur = latest_batch(rows)
    if not cur:
        # 無任何批次訊號 → 退回水位法（drill abort / 非 pcc 測試資料仍可運作）
        return find_new(rows, state), "fallback", rows
    if "last_batch" not in state:
        return [], "baseline", []
    last_b = state.get("last_batch", "") or ""
    cand = [r for r in rows
            if (bk := batch_key(r.get("filename", ""))) and bk > last_b]
    return find_new(cand, state), "batch", cand


def run(weekly_csv: str, state_path: str, dry_run: bool = True,
        push_cap: int = PUSH_CAP, master_csv: str = None,
        grace_periods: int = FRESHNESS_GRACE_PERIODS,
        realert_days: int = FRESHNESS_REALERT_DAYS, today: date = None) -> dict:
    """跑一輪 watcher。回傳結果 dict（含 status: ok|capped）。

    時間封頂改由 CI step `timeout-minutes` 硬 kill（見 daily-watcher.yml），
    本檔不做軟檢查（純記憶體操作跑不到 300s，軟檢查是擺設；ADR D4）。

    新案偵測（issue #22 方案 A）：以批次（filename）為錨，只推「比已處理批次新的
    批次」的案子，廢除舊「公告日最近 2 天」窗。

    master_csv 有給時，額外做「資料新鮮度檢查」（issue #22）：資料源最新批次落後
    官方節奏超過 grace_periods → 推 Slack 斷糧告警。master_csv=None 時跳過（不影響
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
                                             grace_periods, realert_days, today=today)
        except Exception as e:  # noqa: BLE001 — 任何 master 端錯誤都不得中斷 P0
            print(f"::warning::[freshness] 新鮮度檢查失敗、已跳過（不影響 P0）：{e}",
                  file=sys.stderr)
            freshness = {"error": str(e), "stale": None, "alerted": False}

    rows = read_rows(weekly_csv)
    cur_batch = latest_batch(rows)

    # 1. 新案偵測：批次錨（+ seen_keys 去重）；無批次訊號退回水位法
    new_rows, mode, cand = find_new_by_batch(rows, state)
    # 2. P0 布林過濾
    p0_rows = [r for r in new_rows if is_p0(r)]

    result = {"fetched": len(rows), "new": len(new_rows),
              "p0": len(p0_rows), "pushed": 0, "status": "ok", "alert": None,
              "freshness": freshness, "batch": cur_batch,
              "baseline": mode == "baseline", "mode": mode}

    def _advance(note):
        """收尾：推進批次游標 + 水位 + run-log + 存檔（各分支共用）。

        batch 模式只把本批候選列入水位（不灌入舊批次列汙染）；fallback 退回水位
        法時則維持既有「整批列入」行為。游標 last_batch 隨已見最大批次前進。
        """
        commit_watermark(cand if mode == "batch" else rows, state)
        if cur_batch:
            prev = state.get("last_batch", "") or ""
            state["last_batch"] = max(cur_batch, prev)
        append_runlog(state, fetched=len(rows), new=len(new_rows),
                      pushed=result["pushed"], note=note)
        save_state(state, state_path)

    # 3. 冷啟動基線：只設游標不推（不 commit 水位，避免毒化下一批偵測）
    if mode == "baseline":
        if cur_batch:
            state["last_batch"] = cur_batch
        append_runlog(state, fetched=len(rows), new=0, pushed=0,
                      note=f"baseline batch={cur_batch or '-'}")
        save_state(state, state_path)
        return result

    # 4. 成本封頂：推播候選過多 → 規則錯/資料異常 → 不推、alert
    #    ⚠️ 0 漏報鐵則（issue #14 §4）：capped 時游標仍前進，被擋的 P0 下輪
    #    不會再被偵測到。因此 alert 必須完整記錄被擋清單，讓人能手動補救。
    if len(p0_rows) > push_cap:
        blocked = [{"title": r.get("title", ""),
                    "unit_name": r.get("unit_name", ""),
                    "job_number": r.get("job_number", "")}
                   for r in p0_rows]
        alert = write_alert("push_cap_exceeded", {
            "p0_count": len(p0_rows), "cap": push_cap, "batch": cur_batch,
            "hint": "可能規則過鬆或游標回退/資料異常，停下檢查，未推 Slack",
            "blocked_p0": blocked,  # 被擋的完整清單，供人工補救（游標已前進）
        })
        result.update(status="capped", alert=alert)
        _advance(f"CAPPED p0={len(p0_rows)}>{push_cap} batch={cur_batch}")
        return result

    # 5. 推播（dry-run 預設）
    push_res = notify(p0_rows, dry_run=dry_run) if p0_rows else \
        {"sent": False, "count": 0, "reason": "no_p0"}
    result["pushed"] = len(p0_rows) if (push_res.get("sent") or dry_run) else 0
    result["push_reason"] = push_res.get("reason")

    # 6. 推進游標 + 水位 + run-log
    _advance(f"dry_run={dry_run} p0={len(p0_rows)} batch={cur_batch}")
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
    ap.add_argument("--freshness-grace", type=int, default=FRESHNESS_GRACE_PERIODS,
                    help=f"最新批次落後預期超過此半月期數判定斷糧（預設 {FRESHNESS_GRACE_PERIODS}）")
    args = ap.parse_args()

    res = run(args.weekly, args.state, dry_run=not args.push,
              push_cap=args.push_cap, master_csv=args.master,
              grace_periods=args.freshness_grace)
    print(json.dumps(res, ensure_ascii=False), file=sys.stderr)
    # capped 用非零退出碼讓 CI 標記降級（但不算 fetch 失敗）
    if res["status"] == "capped":
        sys.exit(2)


if __name__ == "__main__":
    main()

"""跑偏中止演練 — 可重複執行，驗證成本封頂降級 alert（brief §4 驗收）。

劇本（不碰真 Slack、不依賴外部 API）：
1. 用合成資料建立水位（模擬已穩定運行的 watcher）。
2. 故意把水位回退（rollback_watermark）→ 大量舊案重新被當「新出現」。
3. 跑 watcher.run → P0 新出現數爆量 > push_cap → 應 status='capped'、寫 alert、pushed=0。
4. 斷言：Slack 沒被轟（dry-run 下 pushed=0 且 status=capped）+ alert 檔存在。

成功 = 演練回傳 0 + 印「DRILL PASSED」。失敗 = 非零退出。
這支腳本本身就是「中止演練 1 次成功且可重複」的驗收載體（CI 可跑）。
"""
import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import watcher  # noqa: E402
from watcher_diff import (  # noqa: E402
    commit_watermark,
    load_state,
    rollback_watermark,
    save_state,
)

N = 30          # 合成軟體類 P0 標案數（> push_cap 才能觸發封頂）
PUSH_CAP = 20


def _p0_rows(n):
    return [{
        "unit_id": f"U{i}", "job_number": f"J{i}", "date": "20260613",
        "title": "圖書館資訊系統建置案", "unit_name": "國立臺灣圖書館",
        "type": "公開招標", "url": "http://example/x",
    } for i in range(n)]


def _write_csv(path, rows):
    cols = ["unit_id", "job_number", "date", "title", "unit_name", "type", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run_drill():
    tmp = tempfile.mkdtemp(prefix="watcher_drill_")
    csvp = os.path.join(tmp, "weekly.csv")
    statep = os.path.join(tmp, "state.json")
    # alert 落到演練暫存區，不污染 repo data/alerts
    orig_alert_dir = watcher.ALERT_DIR
    watcher.ALERT_DIR = os.path.join(tmp, "alerts")

    rows = _p0_rows(N)
    _write_csv(csvp, rows)

    try:
        # 1. 建穩定水位：先跑一輪把全部收進水位（dry-run）
        watcher.run(csvp, statep, dry_run=True, push_cap=PUSH_CAP)
        st = load_state(statep)
        baseline_run = watcher.run(csvp, statep, dry_run=True, push_cap=PUSH_CAP)
        assert baseline_run["new"] == 0, "穩定態應 0 新出現"

        # 2. 跑偏：回退水位（刪掉全部 seen → 舊案重新變新）
        st = load_state(statep)
        removed = rollback_watermark(st, len(st["seen_keys"]))
        save_state(st, statep)
        print(f"[drill] 水位回退 {removed} 筆（模擬跑偏/資料異常）", file=sys.stderr)

        # 3. 再跑一輪 → 應觸發封頂
        res = watcher.run(csvp, statep, dry_run=True, push_cap=PUSH_CAP)

        # 4. 斷言
        assert res["status"] == "capped", f"應觸發封頂，實得 {res['status']}"
        assert res["pushed"] == 0, f"Slack 不該被轟，pushed={res['pushed']}"
        assert res["alert"] and os.path.exists(res["alert"]), "應寫 alert 檔"
        alert = json.loads(open(res["alert"], encoding="utf-8").read())
        assert alert["kind"] == "push_cap_exceeded"
        print(f"[drill] 觸發封頂：p0={res['p0']} > cap={PUSH_CAP}，"
              f"pushed={res['pushed']}，alert={alert['kind']}", file=sys.stderr)
        print("DRILL PASSED ✅ — 跑偏 → 封頂 → alert，Slack 未被轟", file=sys.stderr)
        return 0
    finally:
        watcher.ALERT_DIR = orig_alert_dir


if __name__ == "__main__":
    sys.exit(run_drill())

"""0 漏報對照腳本（brief §4 驗收）— 可重複跑。

驗證「命中 P0 規則的標案是否全推了」：
- 對一份 ground-truth CSV（人工同期 query 的全集，或 weekly fetch 結果）套 is_p0，
  得「應推集合」（key set）。
- 對 watcher_state.json 的 run-log + 水位推導「實際處理/推播集合」。
- 漏報 = 應推但不在已見/已推水位裡。回傳漏報清單；空 = 0 漏報。

注意：watcher 水位記的是「已見 key」（commit_watermark 收全部 fetch），
推播與否另看 run-log。本腳本的 recall 定義 = 應推 P0 是否都被 watcher 見過
且在 dry-run 下會被推（capped 輪除外，capped 是主動降級非漏報）。

用法：
    python scripts/audit_recall.py --truth data/weekly.csv --state data/watcher_state.json
退出碼 0 = 0 漏報；1 = 有漏報（印清單）。
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p0_rules import is_p0  # noqa: E402
from watcher_diff import row_key  # noqa: E402


def load_truth_p0(truth_csv: str):
    with open(truth_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    p0 = [r for r in rows if is_p0(r)]
    return {row_key(r): r for r in p0}


def audit(truth_csv: str, state_path: str):
    truth = load_truth_p0(truth_csv)
    if not os.path.exists(state_path):
        # 水位不存在 = 還沒跑過 → 全部視為漏報（提示先跑 watcher）
        return list(truth.values()), len(truth)
    state = json.load(open(state_path, encoding="utf-8"))
    seen = set(state.get("seen_keys", []))
    missed = [r for k, r in truth.items() if k not in seen]
    return missed, len(truth)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", default="data/weekly.csv",
                    help="ground-truth 全集 CSV（人工同期 query 或 fetch 結果）")
    ap.add_argument("--state", default="data/watcher_state.json")
    args = ap.parse_args()

    missed, total = audit(args.truth, args.state)
    recall = (total - len(missed)) / total if total else 1.0
    print(f"P0 應推 {total} 筆 ｜ 漏報 {len(missed)} 筆 ｜ recall {recall:.1%}",
          file=sys.stderr)
    for r in missed:
        print(f"  ✗ 漏報 {row_key(r)} | {r.get('unit_name','')} | {r.get('title','')}",
              file=sys.stderr)
    sys.exit(0 if not missed else 1)


if __name__ == "__main__":
    main()

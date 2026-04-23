"""
把週度 CSV 合併到主檔 data/bids.csv。
用 (unit_id, job_number, date) 當主鍵去重，新資料覆蓋舊。
"""
import argparse
import os

import pandas as pd

PRIMARY_KEYS = ["unit_id", "job_number", "date"]


def merge(master_path: str, weekly_path: str):
    weekly = pd.read_csv(weekly_path, dtype=str)
    if os.path.exists(master_path):
        master = pd.read_csv(master_path, dtype=str)
        combined = pd.concat([master, weekly], ignore_index=True)
    else:
        combined = weekly
    # 去重，保留後者（週度資料可能有更新）
    combined = combined.drop_duplicates(subset=PRIMARY_KEYS, keep="last")
    combined = combined.sort_values("date", ascending=False)
    combined.to_csv(master_path, index=False)
    print(f"master rows: {len(combined)} (weekly added: {len(weekly)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="data/bids.csv")
    ap.add_argument("--weekly", required=True)
    args = ap.parse_args()
    merge(args.master, args.weekly)

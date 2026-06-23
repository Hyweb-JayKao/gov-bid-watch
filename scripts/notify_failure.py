"""watcher 失敗告警：寫一張 markdown alert，消滅「靜默失敗」。

兩件事：
1. **當日失敗告警**：watcher 任一日跑失敗 → 寫一張 agent-alert markdown，
   讓 Jay 在 FLUX Inbox（本機）或 repo data/alerts/（CI）一眼看到。
2. **心跳升級**：讀 watcher_state.json 的 last_run，算「距上次成功幾天」；
   超過 --stale-days（預設 3）→ 告警升級為「連續多日無成功」，標 severity=high。

落點設計（CI 寫不到 Jay 本機）：
- `--out-dir` 指定輸出目錄。CI 傳 repo 內 data/alerts/（隨 commit 留痕）；
  本機跑預設 ~/Documents/FLUX/Inbox/agent-alert/（沿用既有 agent-alert 機制）。
- 格式沿用 FLUX agent-alert markdown（H1 標題 + 條列脈絡），非 JSON，方便人讀。

用法（CI failure step）：
    python scripts/notify_failure.py \
        --reason "fetch 401" --run-url "$RUN_URL" \
        --state data/watcher_state.json --out-dir data/alerts

退出碼永遠 0（告警本身不該再讓 job 連鎖失敗）。
"""
import argparse
import os
import sys
from datetime import datetime

DEFAULT_FLUX_INBOX = os.path.expanduser("~/Documents/FLUX/Inbox/agent-alert")


def days_since_last_success(state_path: str):
    """回 (last_run_iso, days_int) ；讀不到 state 回 (None, None)。

    watcher_state.json 的 last_run 只在 watcher 成功跑完才更新，
    故它代表「最後一次成功」。距今天數 = 連續無成功天數的下界。
    """
    try:
        import json
        with open(state_path, encoding="utf-8") as f:
            d = json.load(f)
        last = d.get("last_run")
        if not last:
            return None, None
        delta = datetime.now() - datetime.fromisoformat(last)
        return last, delta.days
    except (OSError, ValueError, KeyError):
        return None, None


def build_alert(reason: str, run_url: str, last_run, stale_days_actual,
                stale_threshold: int):
    """組 agent-alert markdown 字串。回 (filename, content, is_high)。"""
    today = datetime.now().strftime("%Y-%m-%d")
    is_high = stale_days_actual is not None and stale_days_actual >= stale_threshold
    sev = "high（連續多日無成功）" if is_high else "中（單日失敗，可能間歇）"

    lines = [
        f"# gov-bid-watch watcher 失敗 | {today}",
        "",
        f"- 嚴重度：{sev}",
        f"- 失敗原因：{reason}",
    ]
    if run_url:
        lines.append(f"- 失敗 run：{run_url}")
    if last_run:
        lines.append(f"- 上次成功：{last_run}（距今 {stale_days_actual} 天）")
    else:
        lines.append("- 上次成功：無法判讀 watcher_state（state 缺失或損壞）")
    lines += [
        "",
        "## 怎麼處理",
    ]
    if is_high:
        lines += [
            f"- ⚠️ 已連續 ≥ {stale_threshold} 天無成功 run，**非間歇抖動**，需人工介入：",
            "  - 查 TwinkleAI key 是否仍有效 / 配額是否耗盡（裸 401 通常是閘道，JSON-RPC error 才是 key）。",
            "  - 必要時對外聯絡 TwinkleAI 或更換資料源。",
        ]
    else:
        lines += [
            "- 單日失敗。fetch 已內建 retry（401/5xx/timeout 指數 backoff 5 次），",
            "  仍失敗代表閘道持續抖動或 retry 用盡 → 觀察隔日是否自動恢復。",
            f"- 若連續 ≥ {stale_threshold} 天無成功，本告警會自動升級為 high。",
        ]
    content = "\n".join(lines) + "\n"
    fname = f"{today}-gov-bid-watch-watcher-fail.md"
    return fname, content, is_high


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True, help="失敗原因摘要")
    ap.add_argument("--run-url", default="", help="GitHub Actions run URL")
    ap.add_argument("--state", default="data/watcher_state.json")
    ap.add_argument("--out-dir", default=DEFAULT_FLUX_INBOX,
                    help="alert 輸出目錄（CI 傳 data/alerts；本機預設 FLUX Inbox）")
    ap.add_argument("--stale-days", type=int, default=3,
                    help="距上次成功 ≥ N 天 → 升級 high")
    args = ap.parse_args()

    last_run, stale = days_since_last_success(args.state)
    fname, content, is_high = build_alert(
        args.reason, args.run_url, last_run, stale, args.stale_days)

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    sev = "HIGH" if is_high else "MID"
    print(f"[notify_failure:{sev}] -> {path}", file=sys.stderr)
    print(f"::warning::watcher 失敗告警已寫入 {path}（{sev}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

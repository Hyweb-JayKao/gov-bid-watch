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
    """回 (last_run_iso, days_int, state_error)。

    watcher_state.json 的 last_run 只在 watcher 成功跑完才更新，
    故它代表「最後一次成功」。距今天數 = 連續無成功天數的下界。

    state_error 區分「為什麼算不出天數」：
    - None：正常讀到 last_run，回 (last, days, None)。
    - "missing"：state 檔不存在 / 讀不到（OSError）。
    - "corrupt"：state 檔在但 JSON 壞、結構錯（json/KeyError/型別錯）。
    - "unparseable"：有 last_run 但時間格式無法解析（ValueError）。
    - "no_last_run"：state 可讀但根本沒 last_run 欄位（從沒成功過 / 被清空）。

    ⚠️ 任何「算不出上次成功時間」（state_error 非 None）都不能保守降級——
    無法證明上次成功＝可能已壞很久，必須由 build_alert 升級為 high/critical。
    """
    import json
    try:
        with open(state_path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None, None, "missing"
    try:
        d = json.loads(raw)
    except ValueError:
        return None, None, "corrupt"
    if not isinstance(d, dict):
        return None, None, "corrupt"
    last = d.get("last_run")
    if not last:
        return None, None, "no_last_run"
    try:
        delta = datetime.now() - datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return None, None, "unparseable"
    return last, delta.days, None


_STATE_ERROR_LABEL = {
    "missing": "watcher_state 檔缺失（讀不到）",
    "corrupt": "watcher_state JSON 損壞 / 結構錯誤",
    "unparseable": "watcher_state.last_run 時間格式無法解析",
    "no_last_run": "watcher_state 可讀但無 last_run（從未成功 / 被清空）",
}


def build_alert(reason: str, run_url: str, last_run, stale_days_actual,
                stale_threshold: int, state_error=None):
    """組 agent-alert markdown 字串。回 (filename, content, severity)。

    severity ∈ {"mid", "high", "critical"}：
    - "critical"：state 本身不可讀（missing/corrupt/unparseable）→ 連「上次何時成功」
      都無從得知，盲區，最高優先（unknown_last_success）。
    - "high"：能讀到天數且 ≥ 閾值（確知連續多日無成功），或 no_last_run（確知從沒成功）。
    - "mid"：能讀到天數且 < 閾值（單日失敗，可能間歇）。

    ⚠️ 不可讀 state 永不可降級成 mid——無法證明上次成功＝不能假設它最近成功過。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if state_error in ("missing", "corrupt", "unparseable"):
        severity = "critical"
    elif state_error == "no_last_run":
        severity = "high"
    elif stale_days_actual is not None and stale_days_actual >= stale_threshold:
        severity = "high"
    else:
        severity = "mid"

    sev_label = {
        "critical": "critical（state 不可讀，上次成功未知 unknown_last_success）",
        "high": "high（連續多日無成功 / 從未成功）",
        "mid": "中（單日失敗，可能間歇）",
    }[severity]

    lines = [
        f"# gov-bid-watch watcher 失敗 | {today}",
        "",
        f"- 嚴重度：{sev_label}",
        f"- 失敗原因：{reason}",
    ]
    if run_url:
        lines.append(f"- 失敗 run：{run_url}")
    if last_run:
        lines.append(f"- 上次成功：{last_run}（距今 {stale_days_actual} 天）")
    elif state_error:
        lines.append(
            f"- 上次成功：**無法判讀**——{_STATE_ERROR_LABEL[state_error]}")
    else:
        lines.append("- 上次成功：無法判讀 watcher_state（state 缺失或損壞）")
    lines += [
        "",
        "## 怎麼處理",
    ]
    if severity == "critical":
        lines += [
            f"- ⚠️ **{_STATE_ERROR_LABEL.get(state_error, 'state 不可讀')}**——"
            "連上次成功時間都讀不到，無法判斷壞了多久，視為最高優先：",
            "  - 檢查 repo `data/watcher_state.json` 是否遺失 / 被覆寫 / 內容毀損；必要時從歷史 commit 還原。",
            "  - 同時查 TwinkleAI key/配額（裸 401 通常是閘道，JSON-RPC error 才是 key）。",
            "  - state 修復前，後續每次失敗都會維持 critical 不會自動降級。",
        ]
    elif severity == "high":
        lines += [
            f"- ⚠️ 已連續 ≥ {stale_threshold} 天無成功 run（或從未成功），**非間歇抖動**，需人工介入：",
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
    return fname, content, severity


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

    last_run, stale, state_error = days_since_last_success(args.state)
    fname, content, severity = build_alert(
        args.reason, args.run_url, last_run, stale, args.stale_days,
        state_error=state_error)

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    sev = severity.upper()
    print(f"[notify_failure:{sev}] -> {path}", file=sys.stderr)
    print(f"::warning::watcher 失敗告警已寫入 {path}（{sev}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

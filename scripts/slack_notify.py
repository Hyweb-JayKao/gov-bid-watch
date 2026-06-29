"""Slack 推播 — 讀 env SLACK_WEBHOOK_URL，預設 dry-run（不實際推）。

checkpoint（issue #14 §7）：實作到「讀 env + dry-run 驗證 payload」即停。
**不實際建 webhook、不推真頻道**。實際 webhook URL 由 Jay 設 repo secret，
確認推播格式後才接真 Slack。

啟用真推：呼叫端傳 dry_run=False 且 env 有 SLACK_WEBHOOK_URL。
"""
import json
import os
import sys

import requests


def build_payload(rows: list) -> dict:
    """P0 標案列 → Slack message payload（Block Kit）。"""
    n = len(rows)
    blocks = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"🎯 P0 標案 {n} 則"},
    }]
    for r in rows[:50]:  # Slack block 上限保護
        title = r.get("title") or "(無標題)"
        agency = r.get("unit_name") or r.get("agency") or ""
        date = r.get("date") or ""
        url = r.get("url") or ""
        atype = r.get("type") or ""
        line = f"*<{url}|{title}>*\n{agency} ｜ {atype} ｜ {date}" if url else \
               f"*{title}*\n{agency} ｜ {atype} ｜ {date}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    text = f"P0 標案 {n} 則：" + "；".join(
        (r.get("title") or "") for r in rows[:5]
    )
    return {"text": text, "blocks": blocks}


def _fmt_batch(bkey: str) -> str:
    """'20260302' → '2026-03 下半月'（半月期別人話化）；空 → '無'。"""
    if not bkey or len(bkey) != 8:
        return "無"
    half = "下半月" if bkey[6:8] == "02" else "上半月"
    return f"{bkey[:4]}-{bkey[4:6]} {half}"


def build_freshness_payload(latest_batch: str, expected_batch: str, lag_periods,
                            source: str = "pcc-tender") -> dict:
    """資料新鮮度告警 → Slack message payload（issue #22，批次節奏版）。"""
    if latest_batch:
        lag_txt = f"{lag_periods} 個半月期" if lag_periods is not None else "未知"
        detail = (f"資料源 *{source}* 最新批次為 *{_fmt_batch(latest_batch)}*"
                  f"（{latest_batch}），但依官方發布節奏應已有 "
                  f"*{_fmt_batch(expected_batch)}*（{expected_batch}）——"
                  f"落後 *{lag_txt}*，研判上游 mirror/ETL 沒跟上、非正常 2 月延遲。")
    else:
        detail = (f"資料源 *{source}* 找不到任何有效批次（資料集為空或 filename 全缺），"
                  f"請立即檢查。")
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": "⚠️ 標案資料源斷糧告警"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": "watcher 仍在運行，但上游批次沒如期更新——這不是正常的「今日無新標案」"
                 "也不是官方固有的 2 月延遲。請查 issue #22。"}]},
    ]
    return {"text": f"⚠️ 標案資料源斷糧告警：{source} {detail}", "blocks": blocks}


def notify_freshness(latest_batch: str, expected_batch: str, lag_periods,
                     source: str = "pcc-tender", dry_run: bool = True,
                     webhook: str = None) -> dict:
    """推播資料新鮮度告警（批次節奏版）。語意/降級行為對齊 notify()。

    dry_run=True（預設）→ 印 payload 不發送。
    dry_run=False 但無 webhook → 不發送、reason='no_webhook'（安全降級）。
    """
    payload = build_freshness_payload(latest_batch, expected_batch, lag_periods, source)
    # #7：只在 webhook 為 None 才 fallback 到 env；明確傳入的空字串＝呼叫端
    # 要求「不要 webhook」（測試在有 SLACK_WEBHOOK_URL 的環境也不會誤送真訊息）。
    if webhook is None:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")

    if dry_run:
        print("[slack dry-run] freshness payload:", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return {"sent": False, "dry_run": True, "reason": "dry_run"}

    if not webhook:
        print("[slack] 無 SLACK_WEBHOOK_URL → 不推送新鮮度告警（安全降級）",
              file=sys.stderr)
        return {"sent": False, "dry_run": False, "reason": "no_webhook"}

    resp = requests.post(webhook, json=payload, timeout=30)
    resp.raise_for_status()
    return {"sent": True, "dry_run": False, "reason": "ok"}


def notify(rows: list, dry_run: bool = True, webhook: str = None) -> dict:
    """推播 P0 列。回傳 {sent, dry_run, count, reason}。

    dry_run=True（預設）→ 印 payload 不發送。
    dry_run=False 但無 webhook → 不發送、reason='no_webhook'（不報錯，安全降級）。
    """
    payload = build_payload(rows)
    # #7：只在 webhook 為 None 才 fallback 到 env（空字串＝明確不送，見 notify_freshness）。
    if webhook is None:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")

    if dry_run:
        print("[slack dry-run] payload:", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return {"sent": False, "dry_run": True, "count": len(rows), "reason": "dry_run"}

    if not webhook:
        print("[slack] 無 SLACK_WEBHOOK_URL → 不推送（安全降級）", file=sys.stderr)
        return {"sent": False, "dry_run": False, "count": len(rows), "reason": "no_webhook"}

    resp = requests.post(webhook, json=payload, timeout=30)
    resp.raise_for_status()
    return {"sent": True, "dry_run": False, "count": len(rows), "reason": "ok"}

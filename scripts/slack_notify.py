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


def notify(rows: list, dry_run: bool = True, webhook: str = None) -> dict:
    """推播 P0 列。回傳 {sent, dry_run, count, reason}。

    dry_run=True（預設）→ 印 payload 不發送。
    dry_run=False 但無 webhook → 不發送、reason='no_webhook'（不報錯，安全降級）。
    """
    payload = build_payload(rows)
    webhook = webhook or os.environ.get("SLACK_WEBHOOK_URL", "")

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

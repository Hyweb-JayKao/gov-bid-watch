"""資料新鮮度告警 + 批次新案偵測 unit test（issue #22，方案 A 批次節奏版）。

根因翻轉後（見 ADR 0003）：官方天生 ~2 月延遲、半月批次發布（filename=YYYYMM0H）。
- 新案偵測：以批次 filename 為錨，只推「比已處理批次新」的批次（廢除公告日窗）。
- 新鮮度：以「最新批次有沒有如期出現」判，不用公告日距今。
- 保留 PR #23 健壯性：節流(只在 sent=True)/dry-run 無副作用/Asia-Taipei/webhook 邊界/
  壞 state 不 crash/master 失敗不中斷 P0。
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watcher  # noqa: E402
from freshness import (  # noqa: E402
    batch_key,
    batch_period,
    check_batch_freshness,
    expected_latest_batch_period,
    latest_batch,
    period_to_key,
    taipei_today,
)
from slack_notify import build_freshness_payload, notify_freshness  # noqa: E402

TODAY = date(2026, 6, 29)   # 預期最新批次 = 2026-04 下半月（20260402）

MASTER_COLS = ["unit_id", "job_number", "date", "title", "filename"]
WEEKLY_COLS = ["unit_id", "job_number", "date", "title", "unit_name", "type",
               "url", "category", "filename"]


def _master_rows(*batch_files):
    return [{"unit_id": f"U{i}", "job_number": f"J{i}", "date": "20260301",
             "title": f"案{i}", "filename": fn} for i, fn in enumerate(batch_files)]


def _write_master(path, *batch_files):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MASTER_COLS)
        w.writeheader()
        for r in _master_rows(*batch_files):
            w.writerow(r)


def _write_weekly(path, batch=None, n=0):
    """寫 n 筆 P0 候選（勞務類 + 軟體關鍵字 + 白名單機關），都屬批次 batch。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=WEEKLY_COLS)
        w.writeheader()
        for i in range(n):
            w.writerow({"unit_id": f"W{i}", "job_number": f"WJ{i}",
                        "date": "20260315", "title": "資訊系統開發",
                        "unit_name": "經濟部", "type": "公開招標",
                        "url": "", "category": "勞務類",
                        "filename": batch or "tender_20260402.xml"})


# ---------- 批次識別純函式 ----------
def test_batch_key_strips_prefix():
    assert batch_key("tender_20260402.xml") == "20260402"
    assert batch_key("award_20260402.xml") == "20260402"   # 跨前綴統一
    assert batch_key("") == "" and batch_key("nope.xml") == ""


def test_batch_period_and_roundtrip():
    p = batch_period("20260402")            # 4 月下半月
    assert p == 2026 * 24 + (4 - 1) * 2 + 1
    assert period_to_key(p) == "20260402"
    assert batch_period("20260401") == p - 1   # 相鄰半月差 1
    assert period_to_key(p - 1) == "20260401"


def test_batch_period_rejects_dirty():
    assert batch_period("20261302") is None   # 月 13 非法
    assert batch_period("20260403") is None   # half 03 非法（僅 01/02）
    assert batch_period("abc") is None and batch_period("") is None


def test_latest_batch_picks_max_across_prefix():
    rows = [{"filename": "tender_20260302.xml"}, {"filename": "award_20260402.xml"},
            {"filename": "tender_20260401.xml"}]
    assert latest_batch(rows) == "20260402"


def test_expected_latest_batch_cadence():
    # 6/29（>=5 號）→ 預期 4 月下半月（今天 -2 月）
    assert period_to_key(expected_latest_batch_period(date(2026, 6, 29))) == "20260402"
    # 6/3（<5 號，發布日前）→ 保守抓 3 月下半月（今天 -3 月）
    assert period_to_key(expected_latest_batch_period(date(2026, 6, 3))) == "20260302"


# ---------- check_batch_freshness ----------
def test_freshness_stale_when_behind_two_periods():
    # TwinkleAI 卡 20260302、預期 20260402 → 落後 2 期 → 斷糧（實證情境）
    fr = check_batch_freshness(_master_rows("tender_20260302.xml"), today=TODAY)
    assert fr["stale"] is True
    assert fr["latest_batch"] == "20260302" and fr["expected_batch"] == "20260402"
    assert fr["lag_periods"] == 2


def test_freshness_fresh_when_on_cadence():
    fr = check_batch_freshness(_master_rows("award_20260402.xml"), today=TODAY)
    assert fr["stale"] is False and fr["lag_periods"] == 0


def test_freshness_tolerates_one_period_lag():
    # 落後 1 期（剛好某半月還沒發）→ 不誤報
    fr = check_batch_freshness(_master_rows("tender_20260401.xml"), today=TODAY)
    assert fr["lag_periods"] == 1 and fr["stale"] is False


def test_freshness_empty_is_stale():
    fr = check_batch_freshness([], today=TODAY)
    assert fr["stale"] is True and fr["latest_batch"] == "" and fr["lag_periods"] is None


# ---------- Slack payload ----------
def test_freshness_payload_contains_batch_facts():
    p = build_freshness_payload("20260302", "20260402", 2)
    txt = json.dumps(p, ensure_ascii=False)
    assert "pcc-tender" in txt and "20260302" in txt and "20260402" in txt
    assert "2026-03" in txt and "2026-04" in txt     # 人話化批次
    assert p["blocks"][0]["type"] == "header"


def test_notify_freshness_dry_run_no_send():
    res = notify_freshness("20260302", "20260402", 2, dry_run=True)
    assert res["sent"] is False and res["reason"] == "dry_run"


def test_notify_freshness_no_webhook_safe_degrade():
    res = notify_freshness("20260302", "20260402", 2, dry_run=False, webhook="")
    assert res["sent"] is False and res["reason"] == "no_webhook"


# ---------- watcher 批次新案偵測 ----------
def test_cold_start_sets_baseline_no_push(tmp_path):
    """冷啟動：只設批次基線、不回補歷史 backlog、不推。"""
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, batch="tender_20260402.xml", n=3)
    res = watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)
    assert res["baseline"] is True and res["new"] == 0 and res["pushed"] == 0
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["last_batch"] == "20260402"   # 基線已記


def test_new_batch_detected_and_pushed(tmp_path):
    """已處理到 0401，出現 0402 新批次 → 該批 P0 被推。"""
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, batch="tender_20260401.xml", n=1)
    watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)   # baseline 0401
    _write_weekly(weekly, batch="tender_20260402.xml", n=2)
    res = watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)
    assert res["baseline"] is False and res["new"] == 2 and res["p0"] == 2
    assert res["pushed"] == 2 and res["batch"] == "20260402"
    assert json.loads(state.read_text(encoding="utf-8"))["last_batch"] == "20260402"


def test_same_batch_not_repushed(tmp_path):
    """同一批次再跑 → 不重複當新案。"""
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, batch="tender_20260401.xml", n=1)
    watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)   # baseline 0401
    _write_weekly(weekly, batch="tender_20260402.xml", n=1)
    watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)   # 推 0402
    r3 = watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)  # 再跑同批
    assert r3["new"] == 0 and r3["pushed"] == 0


# ---------- watcher 新鮮度整合 ----------
def test_run_stale_master_fires_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")   # 卡 3 月下半月 → 落後 2 期
    res = watcher.run(str(weekly), str(state), dry_run=False,
                      master_csv=str(master), today=TODAY)
    assert res["freshness"]["stale"] is True and res["freshness"]["alerted"] is True
    alerts = list((tmp_path / "alerts").glob("*data_freshness*.json"))
    assert len(alerts) == 1
    payload = json.loads(alerts[0].read_text(encoding="utf-8"))
    assert payload["latest_batch"] == "20260302" and payload["lag_periods"] == 2


def test_run_fresh_master_no_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "award_20260402.xml")     # 如期 → 不報
    res = watcher.run(str(weekly), str(state), dry_run=True,
                      master_csv=str(master), today=TODAY)
    assert res["freshness"]["stale"] is False and res["freshness"]["alerted"] is False
    assert not list((tmp_path / "alerts").glob("*data_freshness*.json"))


def test_run_no_master_skips_freshness(tmp_path):
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, n=0)
    res = watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)
    assert res["freshness"] is None


def test_freshness_realert_throttled(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")
    r1 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 30))   # 隔 1 天 < 3
    assert r1["freshness"]["alerted"] is True
    assert r2["freshness"]["alerted"] is False
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 1


def test_freshness_realert_after_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 7, 3))    # 隔 4 天 >= 3
    assert r2["freshness"]["alerted"] is True
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 2


def test_freshness_recovery_clears_throttle(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")            # 斷糧
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    _write_master(master, "award_20260402.xml")             # 恢復如期
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    _write_master(master, "tender_20260302.xml")            # 再斷糧（同批次）
    r = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                    realert_days=3, today=date(2026, 6, 30))
    assert r["freshness"]["alerted"] is True   # 恢復清了節流 → 立即重提


# ---------- PR #23 健壯性回歸（沿用，改批次語意）----------
def test_dry_run_does_not_consume_throttle_or_write(tmp_path, monkeypatch):
    """#1：dry-run 只回報 would_alert，不寫 alert 檔、不更新節流 state。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")
    dr = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                     realert_days=3, today=TODAY)
    assert dr["freshness"]["would_alert"] is True and dr["freshness"]["alerted"] is False
    assert not list((tmp_path / "alerts").glob("*data_freshness*.json"))
    saved = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    assert "freshness_alert" not in saved
    real = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                       realert_days=3, today=TODAY)
    assert real["freshness"]["alerted"] is True   # 真推不被 dry-run 壓掉


def test_broken_throttle_state_does_not_crash(tmp_path, monkeypatch):
    """#2：壞掉的節流紀錄（last_alert_date 非法）不丟例外、視為無節流續推。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")
    state.write_text(json.dumps({"freshness_alert": {
        "latest_batch": "20260302", "last_alert_date": "not-a-date"}}),
        encoding="utf-8")
    r = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                    realert_days=3, today=TODAY)
    assert r["freshness"]["alerted"] is True


def test_failed_send_does_not_start_throttle(tmp_path, monkeypatch):
    """codex 複審：沒推到 Slack（sent=False）→ 不啟動節流，下輪仍會重試。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness",
                        lambda *a, **k: {"sent": False, "reason": "no_webhook"})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "tender_20260302.xml")
    r1 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 29))
    assert r1["freshness"]["alerted"] is False
    saved = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    assert "freshness_alert" not in saved
    assert list((tmp_path / "alerts").glob("*data_freshness*.json"))   # 仍留痕
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 30))
    assert r2["freshness"]["alerted"] is True   # 未被節流，重試成功


def test_master_read_failure_does_not_break_p0(tmp_path, monkeypatch):
    """#5：master 不存在 → 新鮮度降級 warning，P0 流程仍跑完。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, batch="tender_20260402.xml", n=1)
    res = watcher.run(str(weekly), str(state), dry_run=True,
                      master_csv=str(tmp_path / "nope.csv"), today=TODAY)
    assert res["status"] == "ok" and res["freshness"].get("error")
    assert res["fetched"] == 1 and isinstance(res["p0"], int)


def test_taipei_today_used_by_default():
    """#6：taipei_today 用 Asia/Taipei，不是 UTC date.today。"""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        assert taipei_today() == _dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
    except Exception:
        assert taipei_today() == _dt.date.today()


def test_notify_freshness_empty_webhook_no_send_even_with_env(monkeypatch):
    """#7：明確傳 webhook='' → 不 fallback env、不送。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/should-not-be-used")
    res = notify_freshness("20260302", "20260402", 2, dry_run=False, webhook="")
    assert res["sent"] is False and res["reason"] == "no_webhook"

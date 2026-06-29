"""資料新鮮度告警 unit test（issue #22）。

驗收（brief）：
- master 最新日期 > N 天前 → 推一則 Slack 新鮮度告警（含資料源/最新日期/距今天數）
- 正常供料時不誤報
- 有可自動驗證的測試
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watcher  # noqa: E402
from freshness import check_freshness, latest_data_date  # noqa: E402
from slack_notify import build_freshness_payload, notify_freshness  # noqa: E402

TODAY = date(2026, 6, 29)


def _rows(*dates):
    return [{"date": d, "title": "x", "unit_id": "U", "job_number": "J"} for d in dates]


def _write_master(path, *dates):
    cols = ["unit_id", "job_number", "date", "title"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, d in enumerate(dates):
            w.writerow({"unit_id": f"U{i}", "job_number": f"J{i}", "date": d,
                        "title": f"案{i}"})


def _write_weekly(path, n=0):
    cols = ["unit_id", "job_number", "date", "title", "unit_name", "type",
            "url", "category"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i in range(n):
            w.writerow({"unit_id": f"W{i}", "job_number": f"WJ{i}",
                        "date": "20260629", "title": "新案", "unit_name": "機關",
                        "type": "公開招標", "url": "", "category": "勞務類"})


# ---------- freshness 純函式 ----------
def test_latest_data_date_picks_max():
    assert latest_data_date(_rows("20260101", "20260504", "20260315")) == "20260504"


def test_latest_data_date_ignores_dirty():
    assert latest_data_date(_rows("20260504", "99999999", "", "abc")) == "20260504"


def test_check_freshness_stale():
    fr = check_freshness(_rows("20260504"), 14, today=TODAY)
    assert fr["stale"] is True and fr["latest_date"] == "20260504"
    assert fr["age_days"] == 56


def test_check_freshness_fresh_within_threshold():
    # 距今 10 天 < 14 → 不誤報（模擬假期空窗的正常供料）
    fr = check_freshness(_rows("20260619"), 14, today=TODAY)
    assert fr["stale"] is False and fr["age_days"] == 10


def test_check_freshness_empty_is_stale():
    fr = check_freshness([], 14, today=TODAY)
    assert fr["stale"] is True and fr["latest_date"] == "" and fr["age_days"] is None


# ---------- Slack payload ----------
def test_freshness_payload_contains_required_facts():
    p = build_freshness_payload("20260504", 56, 14, source="pcc-tender")
    txt = json.dumps(p, ensure_ascii=False)
    assert "pcc-tender" in txt          # 資料源
    assert "2026-05-04" in txt          # 最新日期
    assert "56" in txt                  # 距今天數
    assert p["blocks"][0]["type"] == "header"


def test_notify_freshness_dry_run_no_send():
    res = notify_freshness("20260504", 56, 14, dry_run=True)
    assert res["sent"] is False and res["reason"] == "dry_run"


def test_notify_freshness_no_webhook_safe_degrade():
    res = notify_freshness("20260504", 56, 14, dry_run=False, webhook="")
    assert res["sent"] is False and res["reason"] == "no_webhook"


# ---------- watcher 整合 ----------
def test_run_stale_master_fires_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)               # 斷糧：本輪 0 筆
    _write_master(master, "20260504")        # master 卡在 56 天前
    res = watcher.run(str(weekly), str(state), dry_run=True,
                      master_csv=str(master), today=TODAY)
    assert res["freshness"]["stale"] is True
    assert res["freshness"]["alerted"] is True
    # 寫了 data_freshness alert 檔
    alerts = list((tmp_path / "alerts").glob("*data_freshness*.json"))
    assert len(alerts) == 1
    payload = json.loads(alerts[0].read_text(encoding="utf-8"))
    assert payload["latest_date"] == "20260504" and payload["age_days"] == 56


def test_run_fresh_master_no_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260628")        # 1 天前 → 正常
    res = watcher.run(str(weekly), str(state), dry_run=True,
                      master_csv=str(master), today=TODAY)
    assert res["freshness"]["stale"] is False
    assert res["freshness"]["alerted"] is False
    assert not list((tmp_path / "alerts").glob("*data_freshness*.json"))


def test_run_no_master_skips_freshness(tmp_path):
    # 不給 master → 完全不做新鮮度檢查（保護既有流程/舊測試）
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    _write_weekly(weekly, n=0)
    res = watcher.run(str(weekly), str(state), dry_run=True, today=TODAY)
    assert res["freshness"] is None


def test_freshness_realert_throttled(tmp_path, monkeypatch):
    """同一停滯狀態隔天再跑 → 節流不重複轟炸（< realert_days）。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    r1 = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 30))  # 隔 1 天 < 3
    assert r1["freshness"]["alerted"] is True
    assert r2["freshness"]["alerted"] is False
    # 只寫了 1 個 alert 檔
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 1


def test_freshness_realert_after_interval(tmp_path, monkeypatch):
    """超過 realert_days 仍斷糧 → 重提一次。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                     realert_days=3, today=date(2026, 7, 3))  # 隔 4 天 >= 3
    assert r2["freshness"]["alerted"] is True
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 2


def test_freshness_recovery_clears_throttle(tmp_path, monkeypatch):
    """斷糧→恢復供料→再斷糧：恢復時清節流，再斷糧能立即重提。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    # 斷糧
    _write_master(master, "20260504")
    watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    # 恢復供料
    _write_master(master, "20260629")
    watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    # 再次斷糧（同一最新日期但已恢復過）→ 立即重提
    _write_master(master, "20260504")
    r = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                    realert_days=3, today=date(2026, 6, 30))
    assert r["freshness"]["alerted"] is True

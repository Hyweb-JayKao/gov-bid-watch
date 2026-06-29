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
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)               # 斷糧：本輪 0 筆
    _write_master(master, "20260504")        # master 卡在 56 天前
    res = watcher.run(str(weekly), str(state), dry_run=False,
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
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    r1 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 30))  # 隔 1 天 < 3
    assert r1["freshness"]["alerted"] is True
    assert r2["freshness"]["alerted"] is False
    # 只寫了 1 個 alert 檔
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 1


def test_freshness_realert_after_interval(tmp_path, monkeypatch):
    """超過 realert_days 仍斷糧 → 重提一次。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 7, 3))  # 隔 4 天 >= 3
    assert r2["freshness"]["alerted"] is True
    assert len(list((tmp_path / "alerts").glob("*data_freshness*.json"))) == 2


def test_freshness_recovery_clears_throttle(tmp_path, monkeypatch):
    """斷糧→恢復供料→再斷糧：恢復時清節流，再斷糧能立即重提。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly = tmp_path / "w.csv"
    state = tmp_path / "s.json"
    master = tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    # 斷糧
    _write_master(master, "20260504")
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    # 恢復供料
    _write_master(master, "20260629")
    watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                realert_days=3, today=date(2026, 6, 29))
    # 再次斷糧（同一最新日期但已恢復過）→ 立即重提
    _write_master(master, "20260504")
    r = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                    realert_days=3, today=date(2026, 6, 30))
    assert r["freshness"]["alerted"] is True


# ---------- codex 跨模型審查 7 點修正回歸（issue #22）----------
def test_dry_run_does_not_consume_throttle_or_write(tmp_path, monkeypatch):
    """#1：dry-run 只回報 would_alert，不寫 alert 檔、不更新節流 state。

    回歸 codex High#1：dry-run 若更新節流，隨後真推會被 realert_days 壓掉。
    """
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    dr = watcher.run(str(weekly), str(state), dry_run=True, master_csv=str(master),
                     realert_days=3, today=TODAY)
    assert dr["freshness"]["would_alert"] is True   # 會 alert（若真推）
    assert dr["freshness"]["alerted"] is False       # 但 dry-run 沒真推
    assert not list((tmp_path / "alerts").glob("*data_freshness*.json"))  # 沒寫檔
    assert not state.exists() or "freshness_alert" not in json.loads(
        state.read_text(encoding="utf-8"))            # 沒污染節流 state
    # 隨後真推不被 dry-run 壓掉 → 仍 alert
    real = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                       realert_days=3, today=TODAY)
    assert real["freshness"]["alerted"] is True


def test_broken_throttle_state_does_not_crash(tmp_path, monkeypatch):
    """#2：壞掉的 watcher_state.json（last_alert_date 非法）不丟例外，視為無節流續推。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    state.write_text(json.dumps({"freshness_alert": {
        "latest_date": "20260504", "last_alert_date": "not-a-date"}}),
        encoding="utf-8")
    r = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                    realert_days=3, today=TODAY)
    assert r["freshness"]["alerted"] is True   # 壞 state → 當無節流、續推


def test_failed_send_does_not_start_throttle(tmp_path, monkeypatch):
    """codex 複審：實際沒推到 Slack（送失敗/no_webhook）→ 不啟動 3 天節流。

    否則沒送達也消耗 realert 窗 → 告警被靜默壓掉、回到「靜默斷糧」。
    驗：第一輪沒送達 → 不標 alerted、不寫節流 state；下一輪仍會嘗試推。
    """
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    # 模擬「沒送達」：no_webhook / 送失敗都回 sent=False
    monkeypatch.setattr(watcher, "notify_freshness",
                        lambda *a, **k: {"sent": False, "reason": "no_webhook"})
    weekly, state, master = tmp_path / "w.csv", tmp_path / "s.json", tmp_path / "m.csv"
    _write_weekly(weekly, n=0)
    _write_master(master, "20260504")
    r1 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 29))
    assert r1["freshness"]["alerted"] is False                # 沒送達 → 未標已通知
    saved = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    assert "freshness_alert" not in saved                     # 節流 state 未被設
    # alert 檔仍留痕（可追）
    assert list((tmp_path / "alerts").glob("*data_freshness*.json"))
    # 下一輪（隔 1 天 < realert）仍會嘗試推（沒被節流壓掉）→ 換成送達成功就 alert
    monkeypatch.setattr(watcher, "notify_freshness", lambda *a, **k: {"sent": True})
    r2 = watcher.run(str(weekly), str(state), dry_run=False, master_csv=str(master),
                     realert_days=3, today=date(2026, 6, 30))
    assert r2["freshness"]["alerted"] is True                 # 未被節流，重試成功


def test_master_read_failure_does_not_break_p0(tmp_path, monkeypatch):
    """#5：master 不存在 → 新鮮度降級成 warning，P0 流程仍正常跑完。"""
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    weekly, state = tmp_path / "w.csv", tmp_path / "s.json"
    _write_weekly(weekly, n=1)                       # 有 1 筆 P0
    res = watcher.run(str(weekly), str(state), dry_run=True,
                      master_csv=str(tmp_path / "does_not_exist.csv"), today=TODAY)
    assert res["status"] == "ok"                     # P0 流程沒被中斷
    assert res["freshness"].get("error")             # 新鮮度只記 error
    assert res["fetched"] == 1                        # weekly 1 筆有讀進來、流程跑完
    assert isinstance(res["p0"], int)                # P0 仍正常算出（未崩）


def test_future_date_does_not_mask_staleness(tmp_path):
    """#4：未來日期髒行（20991231）不得成為最大日期遮蔽真斷糧。"""
    fr = check_freshness(_rows("20260504", "20991231"), 14, today=TODAY)
    assert fr["latest_date"] == "20260504"           # 忽略未來日期
    assert fr["stale"] is True and fr["age_days"] == 56


def test_latest_data_date_filters_future_when_today_given():
    assert latest_data_date(_rows("20260504", "20991231"), today=TODAY) == "20260504"
    # 不給 today → 維持舊行為（不過濾，向後相容）
    assert latest_data_date(_rows("20260504", "20991231")) == "20991231"


def test_taipei_today_used_by_default():
    """#6：taipei_today 用 Asia/Taipei，不是 UTC date.today。"""
    from freshness import taipei_today
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        assert taipei_today() == _dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
    except Exception:
        assert taipei_today() == _dt.date.today()


def test_notify_freshness_empty_webhook_no_send_even_with_env(monkeypatch):
    """#7：明確傳 webhook='' → 不 fallback env、不送（測試環境有 env 也不誤送）。"""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/should-not-be-used")
    res = notify_freshness("20260504", 56, 14, dry_run=False, webhook="")
    assert res["sent"] is False and res["reason"] == "no_webhook"

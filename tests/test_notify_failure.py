"""notify_failure：失敗告警 markdown 寫入 + 心跳升級邏輯。"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from notify_failure import build_alert, days_since_last_success  # noqa: E402


def _write_state(tmp_path, last_run):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_run": last_run, "runs": []}), encoding="utf-8")
    return str(p)


def test_days_since_last_success_recent(tmp_path):
    last = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    last_run, days = days_since_last_success(_write_state(tmp_path, last))
    assert days == 1
    assert last_run == last


def test_days_since_last_success_missing_file(tmp_path):
    last_run, days = days_since_last_success(str(tmp_path / "nope.json"))
    assert last_run is None and days is None


def test_days_since_last_success_no_last_run(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"runs": []}), encoding="utf-8")
    last_run, days = days_since_last_success(str(p))
    assert last_run is None and days is None


def test_alert_mid_when_fresh():
    """距上次成功 1 天 → 中度，不升級。"""
    fname, content, is_high = build_alert(
        "fetch 401", "http://run/1", "2026-06-22T05:00:00", 1, stale_threshold=3)
    assert is_high is False
    assert "中（單日失敗" in content
    assert fname.endswith("-gov-bid-watch-watcher-fail.md")
    assert "fetch 401" in content


def test_alert_high_when_stale():
    """距上次成功 4 天（≥ 閾值 3）→ 升級 high + 人工介入文案。"""
    fname, content, is_high = build_alert(
        "fetch 401", "http://run/1", "2026-06-19T05:00:00", 4, stale_threshold=3)
    assert is_high is True
    assert "high" in content
    assert "人工介入" in content


def test_alert_high_when_state_unreadable():
    """state 讀不到（days=None）→ 不誤判成 high（保守不升級）。"""
    _, content, is_high = build_alert(
        "boom", "", None, None, stale_threshold=3)
    assert is_high is False
    assert "無法判讀" in content


def test_main_writes_file(tmp_path, monkeypatch):
    """end-to-end：跑 main 把 alert md 寫進 out-dir。"""
    import notify_failure
    last = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    state = _write_state(tmp_path, last)
    out = tmp_path / "alerts"
    monkeypatch.setattr(sys, "argv", [
        "notify_failure.py", "--reason", "fetch 401",
        "--run-url", "http://run/9", "--state", state, "--out-dir", str(out),
    ])
    rc = notify_failure.main()
    assert rc == 0
    files = list(out.glob("*-gov-bid-watch-watcher-fail.md"))
    assert len(files) == 1
    assert "fetch 401" in files[0].read_text(encoding="utf-8")

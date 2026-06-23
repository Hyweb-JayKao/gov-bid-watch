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
    last_run, days, err = days_since_last_success(_write_state(tmp_path, last))
    assert days == 1
    assert last_run == last
    assert err is None


def test_days_since_last_success_missing_file(tmp_path):
    last_run, days, err = days_since_last_success(str(tmp_path / "nope.json"))
    assert last_run is None and days is None
    assert err == "missing"


def test_days_since_last_success_no_last_run(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"runs": []}), encoding="utf-8")
    last_run, days, err = days_since_last_success(str(p))
    assert last_run is None and days is None
    assert err == "no_last_run"


def test_days_since_last_success_corrupt_json(tmp_path):
    """state JSON 壞掉 → 標 corrupt（不可讀，不能假裝沒事）。"""
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    last_run, days, err = days_since_last_success(str(p))
    assert last_run is None and days is None
    assert err == "corrupt"


def test_days_since_last_success_unparseable_timestamp(tmp_path):
    """有 last_run 但時間格式壞 → 標 unparseable。"""
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"last_run": "not-a-timestamp"}), encoding="utf-8")
    last_run, days, err = days_since_last_success(str(p))
    assert last_run is None and days is None
    assert err == "unparseable"


def test_alert_mid_when_fresh():
    """距上次成功 1 天 → 中度，不升級。"""
    fname, content, severity = build_alert(
        "fetch 401", "http://run/1", "2026-06-22T05:00:00", 1, stale_threshold=3)
    assert severity == "mid"
    assert "中（單日失敗" in content
    assert fname.endswith("-gov-bid-watch-watcher-fail.md")
    assert "fetch 401" in content


def test_alert_high_when_stale():
    """距上次成功 4 天（≥ 閾值 3）→ 升級 high + 人工介入文案。"""
    fname, content, severity = build_alert(
        "fetch 401", "http://run/1", "2026-06-19T05:00:00", 4, stale_threshold=3)
    assert severity == "high"
    assert "high" in content
    assert "人工介入" in content


# ── regression（codex medium）：不可讀 state 必須升級，不准保守停 mid ──
# 舊行為（已修）：state 壞/缺 → days=None → 只標 mid，state 壞掉後永遠停 medium。
# 新行為：missing/corrupt/unparseable → critical（unknown_last_success）、
#        no_last_run → high。任一情況都不得是 mid。

def test_alert_critical_when_state_missing():
    """state 檔缺失 → critical，不准降級成 mid。"""
    _, content, severity = build_alert(
        "boom", "", None, None, stale_threshold=3, state_error="missing")
    assert severity == "critical"
    assert "unknown_last_success" in content
    assert "無法判讀" in content


def test_alert_critical_when_state_corrupt():
    """state JSON 損壞 → critical。"""
    _, content, severity = build_alert(
        "boom", "", None, None, stale_threshold=3, state_error="corrupt")
    assert severity == "critical"
    assert "損壞" in content


def test_alert_critical_when_timestamp_unparseable():
    """last_run 時間格式壞 → critical。"""
    _, _, severity = build_alert(
        "boom", "", None, None, stale_threshold=3, state_error="unparseable")
    assert severity == "critical"


def test_alert_high_when_never_succeeded():
    """state 可讀但從沒成功（no_last_run）→ high，不是 mid。"""
    _, _, severity = build_alert(
        "boom", "", None, None, stale_threshold=3, state_error="no_last_run")
    assert severity == "high"


def test_unreadable_state_never_mid():
    """守門 regression：任何不可讀 state 都不會是 mid（防回歸到舊保守行為）。"""
    for err in ("missing", "corrupt", "unparseable", "no_last_run"):
        _, _, severity = build_alert(
            "x", "", None, None, stale_threshold=3, state_error=err)
        assert severity != "mid", f"state_error={err} 不該停在 mid"


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

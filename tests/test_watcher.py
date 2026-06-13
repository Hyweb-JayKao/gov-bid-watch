"""watcher 主流程 + Slack 推播 + 成本封頂 unit test。"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watcher  # noqa: E402
import watcher_diff  # noqa: E402
from slack_notify import build_payload, notify  # noqa: E402


def _write_csv(path, rows):
    cols = ["unit_id", "job_number", "date", "title", "unit_name", "type", "url",
            "category"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _p0_row(i, agency="國立臺灣圖書館", title="圖書館資訊系統建置", category="勞務類"):
    # category 預設勞務類：issue #14 收緊後 P0 須為勞務類採購（軟體開發服務）
    return {"unit_id": f"U{i}", "job_number": f"J{i}", "date": "20260613",
            "title": title, "unit_name": agency, "type": "公開招標", "url": "http://x",
            "category": category}


# ---------- Slack ----------
def test_build_payload_structure():
    p = build_payload([_p0_row(1)])
    assert "blocks" in p and p["blocks"][0]["type"] == "header"
    assert "1 則" in p["blocks"][0]["text"]["text"]


def test_notify_dry_run_does_not_send():
    res = notify([_p0_row(1)], dry_run=True)
    assert res["sent"] is False and res["reason"] == "dry_run"


def test_notify_no_webhook_safe_degrade():
    # dry_run=False 但無 webhook → 不報錯、安全降級
    res = notify([_p0_row(1)], dry_run=False, webhook="")
    assert res["sent"] is False and res["reason"] == "no_webhook"


# ---------- watcher 主流程 ----------
def test_run_first_pass_all_new_p0(tmp_path):
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    _write_csv(csvp, [_p0_row(i) for i in range(3)])
    res = watcher.run(str(csvp), str(statep), dry_run=True)
    assert res["fetched"] == 3 and res["new"] == 3
    assert res["p0"] == 3 and res["pushed"] == 3 and res["status"] == "ok"


def test_run_filters_non_p0(tmp_path):
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    rows = [_p0_row(1)] + [
        {"unit_id": "X", "job_number": "JX", "date": "20260613",
         "title": "辦公室清潔勞務", "unit_name": "某公司", "type": "公開招標", "url": ""}
    ]
    _write_csv(csvp, rows)
    res = watcher.run(str(csvp), str(statep), dry_run=True)
    assert res["new"] == 2 and res["p0"] == 1   # 清潔被排除


def test_run_second_pass_no_new(tmp_path):
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    _write_csv(csvp, [_p0_row(i) for i in range(3)])
    watcher.run(str(csvp), str(statep), dry_run=True)   # 第一輪
    res = watcher.run(str(csvp), str(statep), dry_run=True)  # 第二輪同檔
    assert res["new"] == 0 and res["pushed"] == 0


def test_cost_cap_triggers_alert_no_push(tmp_path, monkeypatch):
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    _write_csv(csvp, [_p0_row(i) for i in range(25)])  # 25 > cap 20
    res = watcher.run(str(csvp), str(statep), dry_run=True, push_cap=20)
    assert res["status"] == "capped"
    assert res["pushed"] == 0
    assert res["alert"] is not None
    # alert 檔有寫
    assert Path(res["alert"]).exists()
    payload = json.loads(Path(res["alert"]).read_text(encoding="utf-8"))
    assert payload["kind"] == "push_cap_exceeded" and payload["p0_count"] == 25


def test_cost_cap_alert_includes_blocked_list(tmp_path, monkeypatch):
    """0 漏報鐵則：capped 時水位前進，alert 必須含被擋 P0 完整清單供人工補救。"""
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    monkeypatch.setattr(watcher, "ALERT_DIR", str(tmp_path / "alerts"))
    rows = [_p0_row(i, title=f"圖書館資訊系統建置-{i}") for i in range(25)]
    _write_csv(csvp, rows)
    res = watcher.run(str(csvp), str(statep), dry_run=True, push_cap=20)
    payload = json.loads(Path(res["alert"]).read_text(encoding="utf-8"))
    blocked = payload["blocked_p0"]
    # 全部 25 筆被擋的 P0 都要在清單裡，且帶可辨識欄位
    assert len(blocked) == 25
    sample = blocked[0]
    assert {"title", "unit_name", "job_number"} <= set(sample)
    # 內容不是空殼：title/job_number 對得回原始列
    titles = {b["title"] for b in blocked}
    assert titles == {f"圖書館資訊系統建置-{i}" for i in range(25)}
    jobs = {b["job_number"] for b in blocked}
    assert jobs == {f"J{i}" for i in range(25)}


# ---------- watcher_diff 空 key 去重 ----------
def test_empty_key_rows_not_deduped(tmp_path):
    """三主鍵全空的不同標案不可被去重成一筆（否則漏報；issue #14 §4）。"""
    rows = [
        {"unit_id": "", "agency_id": "", "job_number": "", "date": "",
         "title": "甲案：系統建置", "unit_name": "A 機關"},
        {"unit_id": "", "agency_id": "", "job_number": "", "date": "",
         "title": "乙案：系統建置", "unit_name": "B 機關"},
    ]
    # 兩筆內容不同 → key 必須不同
    assert watcher_diff.row_key(rows[0]) != watcher_diff.row_key(rows[1])
    # find_new 不去重，兩筆都算新出現
    new = watcher_diff.find_new(rows, {"seen_keys": []})
    assert len(new) == 2


def test_empty_key_same_content_still_deduped(tmp_path):
    """主鍵全空但內容完全相同 → 仍視為同一筆去重（fallback 用 title+unit_name）。"""
    r = {"unit_id": "", "job_number": "", "date": "",
         "title": "同案", "unit_name": "同機關"}
    new = watcher_diff.find_new([dict(r), dict(r)], {"seen_keys": []})
    assert len(new) == 1


def test_runlog_written(tmp_path):
    csvp = tmp_path / "w.csv"
    statep = tmp_path / "s.json"
    _write_csv(csvp, [_p0_row(i) for i in range(2)])
    watcher.run(str(csvp), str(statep), dry_run=True)
    st = json.loads(statep.read_text(encoding="utf-8"))
    assert len(st["runs"]) == 1
    run = st["runs"][0]
    assert run["fetched"] == 2 and run["new"] == 2 and run["pushed"] == 2
    assert "watermark" in run

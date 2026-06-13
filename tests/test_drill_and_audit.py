"""中止演練 + 0漏報對照 的回歸測試（brief §4 兩條 binary 驗收的可重複保證）。"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import drill_abort  # noqa: E402
from audit_recall import audit  # noqa: E402


def test_drill_abort_passes():
    # 跑偏中止演練應回傳 0（封頂觸發、Slack 未被轟）
    assert drill_abort.run_drill() == 0


def _write_csv(path, rows):
    cols = ["unit_id", "job_number", "date", "title", "unit_name", "type", "url",
            "category"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def test_audit_zero_miss_when_all_seen(tmp_path):
    truth = tmp_path / "truth.csv"
    statep = tmp_path / "s.json"
    rows = [{"unit_id": f"U{i}", "job_number": f"J{i}", "date": "20260613",
             "title": "圖書館資訊系統", "unit_name": "國立臺灣圖書館",
             "category": "勞務類"} for i in range(3)]
    _write_csv(truth, rows)
    seen = [f"U{i}|J{i}|20260613" for i in range(3)]
    statep.write_text(json.dumps({"seen_keys": seen}), encoding="utf-8")
    missed, total = audit(str(truth), str(statep))
    assert total == 3 and missed == []


def test_audit_detects_miss(tmp_path):
    truth = tmp_path / "truth.csv"
    statep = tmp_path / "s.json"
    rows = [{"unit_id": f"U{i}", "job_number": f"J{i}", "date": "20260613",
             "title": "圖書館資訊系統", "unit_name": "國立臺灣圖書館",
             "category": "勞務類"} for i in range(3)]
    _write_csv(truth, rows)
    # 只見過 2 筆 → 第 3 筆漏報
    seen = ["U0|J0|20260613", "U1|J1|20260613"]
    statep.write_text(json.dumps({"seen_keys": seen}), encoding="utf-8")
    missed, total = audit(str(truth), str(statep))
    assert total == 3 and len(missed) == 1 and missed[0]["unit_id"] == "U2"


def test_audit_ignores_non_p0(tmp_path):
    truth = tmp_path / "truth.csv"
    statep = tmp_path / "s.json"
    rows = [
        {"unit_id": "U0", "job_number": "J0", "date": "20260613",
         "title": "圖書館資訊系統", "unit_name": "國立臺灣圖書館",
         "category": "勞務類"},
        {"unit_id": "U1", "job_number": "J1", "date": "20260613",
         "title": "辦公室清潔勞務", "unit_name": "某公司"},   # 非 P0
    ]
    _write_csv(truth, rows)
    statep.write_text(json.dumps({"seen_keys": []}), encoding="utf-8")
    missed, total = audit(str(truth), str(statep))
    assert total == 1   # 只算 P0；清潔不計

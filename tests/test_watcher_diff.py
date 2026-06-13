"""watcher diff / 水位 unit test。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from watcher_diff import (  # noqa: E402
    append_runlog,
    commit_watermark,
    find_new,
    load_state,
    rollback_watermark,
    row_key,
    save_state,
)


def _row(uid, job, date, title="案", agency="機關"):
    return {"unit_id": uid, "job_number": job, "date": date,
            "title": title, "unit_name": agency}


def test_row_key_matches_merge_primary():
    assert row_key(_row("A", "J1", "20260613")) == "A|J1|20260613"


def test_row_key_falls_back_to_agency_id():
    assert row_key({"agency_id": "X", "job_number": "J", "date": "20260613"}) == "X|J|20260613"


def test_find_new_all_new_on_empty_state():
    st = {"seen_keys": []}
    rows = [_row("A", "J1", "20260613"), _row("B", "J2", "20260613")]
    assert len(find_new(rows, st)) == 2


def test_find_new_filters_seen():
    st = {"seen_keys": ["A|J1|20260613"]}
    rows = [_row("A", "J1", "20260613"), _row("B", "J2", "20260613")]
    new = find_new(rows, st)
    assert len(new) == 1
    assert new[0]["unit_id"] == "B"


def test_find_new_dedups_within_batch():
    st = {"seen_keys": []}
    rows = [_row("A", "J1", "20260613"), _row("A", "J1", "20260613")]
    assert len(find_new(rows, st)) == 1


def test_commit_watermark_grows_seen():
    st = {"seen_keys": []}
    commit_watermark([_row("A", "J1", "20260613"), _row("B", "J2", "20260613")], st)
    assert set(st["seen_keys"]) == {"A|J1|20260613", "B|J2|20260613"}


def test_rollback_makes_old_rows_new_again():
    # 中止演練核心：回退水位 → 舊案重新被當新出現
    st = {"seen_keys": []}
    rows = [_row(str(i), "J", "20260613") for i in range(10)]
    commit_watermark(rows, st)
    assert len(find_new(rows, st)) == 0          # 都見過
    removed = rollback_watermark(st, 8)
    assert removed == 8
    assert len(find_new(rows, st)) == 8          # 8 個又變新出現


def test_rollback_caps_at_available():
    st = {"seen_keys": ["A|J|D"]}
    assert rollback_watermark(st, 99) == 1
    assert st["seen_keys"] == []


def test_runlog_append_and_trim(tmp_path):
    st = {"seen_keys": [], "runs": []}
    for i in range(70):
        append_runlog(st, fetched=i, new=0, pushed=0)
    p = tmp_path / "state.json"
    save_state(st, str(p))
    reloaded = load_state(str(p))
    assert len(reloaded["runs"]) == 60          # RUNLOG_KEEP


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    st = {"seen_keys": ["A|J|D"], "last_run": None, "runs": []}
    save_state(st, str(p))
    assert load_state(str(p))["seen_keys"] == ["A|J|D"]

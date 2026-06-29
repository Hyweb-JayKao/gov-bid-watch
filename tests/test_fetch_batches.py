"""fetch_pcc 批次抓取純函式 test（issue #22 方案 A）。

只測無網路的純邏輯（pick_latest_batch_keys）：跨 tender_/award_ 前綴統一成
批次日期段、去重、取最新 n 個。實際對 TwinkleAI 的抓取需 CI（有 token）驗。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_pcc import pick_latest_batch_keys  # noqa: E402


def test_pick_latest_unifies_prefix_and_dedups():
    files = ["tender_20260402.xml", "award_20260402.xml",
             "tender_20260302.xml", "award_20260301.xml"]
    assert pick_latest_batch_keys(files, 2) == ["20260402", "20260302"]


def test_pick_latest_ignores_non_batch_filenames():
    files = ["junk.xml", "", "tender_20260401.xml", None]
    assert pick_latest_batch_keys(files, 5) == ["20260401"]


def test_pick_latest_limits_n():
    files = [f"tender_2026{m:02d}02.xml" for m in range(1, 5)]
    assert pick_latest_batch_keys(files, 2) == ["20260402", "20260302"]

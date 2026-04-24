"""helper 純函式 smoke test。"""
import pandas as pd

from helpers import classify_unit, count_themes, is_own


def test_classify_unit_school():
    assert classify_unit("國立臺灣大學") == "學校"


def test_classify_unit_hospital():
    assert classify_unit("臺大醫院") == "醫療"
    assert classify_unit("國軍桃園總醫院") == "醫療"


def test_classify_unit_central():
    assert classify_unit("衛生福利部") == "中央部會"


def test_classify_unit_unknown():
    assert classify_unit("某某協會") == "其他"


def test_classify_unit_nan():
    assert classify_unit(pd.NA) == "其他"
    assert classify_unit(None) == "其他"
    assert classify_unit("") == "其他"


def test_is_own_positive():
    assert is_own("凌網資訊股份有限公司") is True
    assert is_own("網擎資訊") is True


def test_is_own_negative():
    assert is_own("關貿網路股份有限公司") is False
    assert is_own(None) is False
    assert is_own(pd.NA) is False


def test_count_themes():
    titles = [
        "某某系統維運案",
        "AI 智慧應用",
        "資料庫升級",
        "無關主題",
    ]
    result = count_themes(titles)
    assert "系統維運" in result
    assert "AI/數據" in result
    assert "資料庫" in result

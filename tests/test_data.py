"""資料檔 smoke test：確保 bids.csv schema 不變、日期可解析。"""
import pandas as pd
import pytest

DATA_PATH = "data/bids.csv"

EXPECTED_COLS = {
    "date", "unit_name", "unit_id", "type", "title",
    "category", "budget", "award_amount", "awarded_at",
    "companies", "job_number", "url",
}


@pytest.fixture(scope="module")
def df():
    return pd.read_csv(DATA_PATH, dtype=str)


def test_columns_present(df):
    assert EXPECTED_COLS.issubset(set(df.columns)), \
        f"缺欄位：{EXPECTED_COLS - set(df.columns)}"


def test_has_data(df):
    assert len(df) > 0, "bids.csv 沒資料"


def test_dates_parseable(df):
    parsed = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    bad = parsed.isna().sum()
    assert bad == 0, f"{bad} 筆 date 無法解析為 YYYYMMDD"


def test_amounts_numeric(df):
    for col in ("budget", "award_amount"):
        pd.to_numeric(df[col], errors="coerce")


def test_award_has_companies(df):
    # 決標案至少半數以上要有 companies（部分來源未提供是正常的）
    award = df[df["type"].str.contains("決標", na=False)]
    has = award["companies"].notna().sum()
    ratio = has / len(award) if len(award) else 0
    assert ratio > 0.5, f"決標案有 companies 比例過低：{ratio:.1%}"

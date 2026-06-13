"""P0 規則 unit test — 機關白名單 / 關鍵字 / 排除詞 各有案例（brief §4 驗收）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from p0_rules import hit_agency, hit_exclude, hit_keyword, is_p0  # noqa: E402


# ---------- 機關白名單 ----------
def test_agency_core_hit():
    assert hit_agency("國立臺灣圖書館")
    assert hit_agency("臺北市立圖書館")        # 「圖書館」子字串
    assert hit_agency("內政部移民署")
    assert hit_agency("數位發展部")


def test_agency_strategic_hit():
    assert hit_agency("行政院公共工程委員會")
    assert hit_agency("法務部廉政署")
    assert hit_agency("某部會政風室")


def test_agency_miss():
    assert not hit_agency("國防部")            # 不在白名單
    assert not hit_agency("某私人公司")
    assert not hit_agency("")


# ---------- 關鍵字 ----------
def test_keyword_existing_dict_reused():
    # 複用既有 KEYWORDS（不另立平行字典）
    assert hit_keyword("某機關資訊系統建置案")
    assert hit_keyword("官方網站改版")
    assert hit_keyword("AI 應用程式開發")


def test_keyword_p0_extra():
    # P0 加強層補的詞
    assert hit_keyword("圖書館借閱系統")        # 借閱（既有也有系統，但測 P0 詞獨立可命中）
    assert hit_keyword("無障礙網頁 WCAG 改善")
    assert hit_keyword("政府開放資料平台委外維護")


def test_keyword_miss():
    assert not hit_keyword("辦公室清潔勞務")
    assert not hit_keyword("")


# ---------- 排除詞 ----------
def test_exclude_existing_blacklist():
    assert hit_exclude("道路橋樑工程")          # 既有 BLACKLIST「工程」「橋樑」
    assert hit_exclude("空調機電維護")


def test_exclude_p0_extra():
    assert hit_exclude("校園監視系統建置")      # P0 排除補充
    assert hit_exclude("門禁系統")
    assert hit_exclude("文件翻譯服務")


def test_exclude_miss():
    assert not hit_exclude("資訊系統開發")
    assert not hit_exclude("")


# ---------- is_p0 整合 ----------
def test_is_p0_agency_path():
    # 機關命中 → P0（即使 title 關鍵字弱）
    assert is_p0({"unit_name": "國立臺灣圖書館", "title": "圖書借閱服務系統"})


def test_is_p0_keyword_path():
    # 機關不在白名單但關鍵字強 → P0
    assert is_p0({"unit_name": "某市政府", "title": "市民服務 App 開發建置"})


def test_is_p0_exclude_overrides():
    # 排除詞優先級最高：即使機關命中也否決
    assert not is_p0({"unit_name": "國立臺灣圖書館", "title": "圖書館門禁監視系統工程"})


def test_is_p0_neither():
    assert not is_p0({"unit_name": "某私人公司", "title": "辦公室清潔勞務採購"})


def test_is_p0_handles_agency_key_alias():
    # 餵原始 pcc row（agency 欄）也能判
    assert is_p0({"agency": "數位發展部", "title": "資料治理平台"})

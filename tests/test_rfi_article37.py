"""§37「不得不當限制競爭」測試集。

模擬實務上常見的「廠商資格過度限縮」寫法，驗證 rfi_check.run() 是否能抓到，
並作為未來新增規則時的回歸基準。

§37 核心：機關訂定廠商資格，不得不當限制競爭，並以確認廠商具備履行契約
所必須之能力者為限。

實務上違規態樣（每個 fixture 對應一種）：
  A. 資本額門檻過高（與標的金額不相稱）
  B. 實績件數門檻過高
  C. 實績限定特定機關／特定系統
  D. 認證門檻過嚴（ISO 27001 / CMMI Level 3 / TAF 等用於小案）
  E. 公司成立年限過長
  F. 地理位置限定（公司登記縣市）
  G. 人員學經歷／證照條件過嚴
  H. 限定特定品牌經銷／代理身份
  I. 多重門檻疊加（個別合理但加起來只有 N 家符合）
  J. 對照組：合理寫法，不應觸發

目前 rfi_check 對 A/B 有具體規則；C/D/E/F/G/H/I 多數尚無對應規則 ——
這些 case 標記為 xfail，正好作為「待補規則」的清單。
"""
from __future__ import annotations

import pytest

import rfi_check


def _has_rule(text: str, rule_id_prefix: str) -> bool:
    return any(f.rule_id.startswith(rule_id_prefix) for f in rfi_check.run(text))


# ---------- A. 資本額過高 ----------

RFI_A_CAP_HIGH = """
案名：某機關公文系統小型維護案
預算：新臺幣 80 萬元
廠商資格：實收資本額需達新臺幣壹億元以上。
"""


def test_A_資本額壹億用於80萬案():
    """80 萬小案要求 1 億資本額，明顯逾越業務需要（§37）。"""
    assert _has_rule(RFI_A_CAP_HIGH, "D-036-資本額門檻")


# ---------- B. 實績件數過高 ----------

RFI_B_RECORDS_MANY = """
案名：人事差勤系統建置
廠商資格：投標廠商近三年同類型系統實績應達 25 件以上。
"""


def test_B_近三年實績25件():
    assert _has_rule(RFI_B_RECORDS_MANY, "D-036-實績門檻")


# ---------- C. 實績限定特定機關 / 特定系統 ----------

RFI_C_RECORDS_NARROW = """
廠商資格：投標廠商近三年內，應有承做「中央○○部會」之「電子公文系統」實績 1 件以上。
"""


@pytest.mark.xfail(reason="尚未實作：限定特定機關/系統名稱之實績條款偵測")
def test_C_實績限定特定機關():
    assert _has_rule(RFI_C_RECORDS_NARROW, "D-037-實績限定")


# ---------- D. 認證門檻過嚴 ----------

RFI_D_CERT_OVERKILL = """
案名：機關內部小工具改版案，預算 50 萬元
廠商資格：
  1. 應通過 ISO/IEC 27001 資訊安全管理系統驗證。
  2. 應通過 CMMI Maturity Level 3 以上認證。
  3. 應具備 TAF 實驗室認證。
"""


@pytest.mark.xfail(reason="尚未實作：小額案件套大規格認證之偵測（需金額/認證對照）")
def test_D_小案要求CMMI_ISO():
    assert _has_rule(RFI_D_CERT_OVERKILL, "D-037-認證過嚴")


# ---------- E. 成立年限過長 ----------

RFI_E_FOUND_YEARS = """
廠商資格：投標廠商之公司設立登記年限應達 15 年以上。
"""


def test_E_成立15年():
    assert _has_rule(RFI_E_FOUND_YEARS, "D-037-成立年限")


RFI_E_LOW = "本公司成立 3 年。"


def test_E_3年不應觸發():
    assert not _has_rule(RFI_E_LOW, "D-037-成立年限")


RFI_E_MID = "投標廠商之公司設立登記應滿 6 年以上。"


def test_E_6年mid():
    findings = [f for f in rfi_check.run(RFI_E_MID) if f.rule_id == "D-037-成立年限"]
    assert findings and findings[0].severity == "mid"


RFI_E_NEGATION = "依採購法第 37 條，不得要求公司成立 10 年以上。"


def test_E_引文不應觸發():
    assert not _has_rule(RFI_E_NEGATION, "D-037-成立年限")


# ---------- F. 地理位置限定 ----------

RFI_F_LOCATION = """
廠商資格：投標廠商公司登記地址須位於臺北市或新北市。
"""


def test_F_限定登記縣市():
    assert _has_rule(RFI_F_LOCATION, "D-037-地理限定")


RFI_F_WORK_LOCATION = "履約地點：臺北市信義區。"


def test_F_履約地點不應觸發():
    """履約地點是工作地，不是廠商登記地，不該被當成地理限定。"""
    assert not _has_rule(RFI_F_WORK_LOCATION, "D-037-地理限定")


RFI_F_TWO_CITY = "投標廠商公司所在地須位於高雄市或臺南市。"


def test_F_兩縣市():
    assert _has_rule(RFI_F_TWO_CITY, "D-037-地理限定")


RFI_F_NEGATION = "依採購法第 37 條，不得限定公司登記須位於臺北市。"


def test_F_引文不應觸發():
    assert not _has_rule(RFI_F_NEGATION, "D-037-地理限定")


# ---------- G. 人員條件過嚴 ----------

RFI_G_STAFF = """
專案經理資格：
  1. 應具備碩士以上學位。
  2. 應擁有 PMP 證照且年資滿 10 年。
  3. 應同時擁有 CISSP 與 CCIE 證照。
"""


@pytest.mark.xfail(reason="尚未實作：人員學經歷/多重證照疊加偵測")
def test_G_PMP10年_CISSP_CCIE():
    assert _has_rule(RFI_G_STAFF, "D-037-人員過嚴")


# ---------- H. 限定品牌代理／經銷 ----------

RFI_H_DEALER = """
廠商資格：投標廠商須為 Cisco 原廠認證金牌代理商（Gold Partner）。
"""


@pytest.mark.xfail(reason="尚未實作：限定特定品牌代理／經銷身份偵測（§26+§37 交界）")
def test_H_限定Cisco金牌代理():
    assert _has_rule(RFI_H_DEALER, "D-037-限定代理")


# ---------- I. 多重門檻疊加 ----------

RFI_I_STACKED = """
案名：地方政府網站改版（預算 60 萬）
廠商資格：
  1. 實收資本額 3,000 萬元以上。
  2. 近三年同類型實績 10 件以上。
  3. 通過 ISO 27001 驗證。
  4. 專案經理具 PMP 證照。
  5. 公司成立滿 8 年。
"""


def test_I_疊加門檻_至少資本額實績應觸發():
    """個別門檻看似合理，疊加後恐限縮競爭。目前至少資本額(mid)＋實績(mid) 該抓到。"""
    findings = rfi_check.run(RFI_I_STACKED)
    rules = {f.rule_id for f in findings}
    assert "D-036-資本額門檻" in rules
    assert "D-036-實績門檻" in rules


@pytest.mark.xfail(reason="尚未實作：多重門檻疊加聚合提示（meta-rule）")
def test_I_疊加門檻_整體聚合():
    assert _has_rule(RFI_I_STACKED, "D-037-多重疊加")


# ---------- J. 對照組：合理寫法 ----------

RFI_J_REASONABLE = """
案名：機關內網小工具改版（預算 80 萬）
廠商資格：
  1. 依法設立登記之公司或商業（無資本額下限）。
  2. 近一年內有資訊系統開發或維護實績 1 件以上。
  3. 投標時應提出公司基本資料及實績說明。
"""


def test_J_合理寫法不該觸發37系列():
    findings = rfi_check.run(RFI_J_REASONABLE)
    # 不應出現 §36/§37 / §26 / §22 / §28 / §31 / §56 / §70 任何旗標
    bad = [f for f in findings if f.article_no in {"36", "37", "26", "22", "28", "31", "56", "70"}]
    assert bad == [], f"合理寫法不應觸發，但抓到：{[(f.rule_id, f.snippet[:50]) for f in bad]}"


# ---------- 引文／否定／中小企業定義：保險絲 ----------

RFI_K_SME_QUOTE = """
依中小企業認定標準第 2 條，所稱中小企業，指實收資本額在新臺幣一億元以下之事業。
"""


def test_K_中小企業定義引文不應觸發():
    assert not _has_rule(RFI_K_SME_QUOTE, "D-036")


RFI_L_NEGATION = """
依採購法第 37 條規定，機關訂定資格不得不當限制競爭，
不得要求實收資本額逾新臺幣壹億元、亦不得限定特定機關實績。
"""


def test_L_引述法條不應觸發():
    assert not _has_rule(RFI_L_NEGATION, "D-036")

# Story 006：政府採購法合規查核

## User Story
**As a** 業務 / 投標策略人員
**I want to** 在看某機關標案時，知道有沒有違反政府採購法條文
**So that** 判斷該案是否值得投、或留意可能的異議/申訴空間

## 成功指標
標案明細頁能顯示「疑似違反第 XX 條」，並可點開原文。

## 涵蓋 features
- [x] **law-sync**（政府採購法條文同步）— `scripts/fetch_law.py` → `data/law/procurement_act.json`
- [x] **law-browser**（條文檢索 UI）— app.py tab10「法規」（關鍵字 / 章節 / 條號三軸過濾）
- [x] **rfi-check**（RFI 文件檢核）— `rfi_check.py` + tab10 子頁「RFI 文件檢核」
  - 支援 PDF / DOCX / TXT 上傳，或直接貼上文字
  - 八條啟發式規則：§26 指定品牌（含全文同等品聲明豁免）、§26 排他文字、§28 等標期、§36 資格門檻（真做數值比對）、§22 限制性依據、§31 押標金沒收依據、§56 評選籠統、§70 履約期限過短
  - 命中項目可展開看條文原文
- [x] **compliance-rules**（規則引擎 PoC）— `compliance.py` + tab10 子頁「合規查核 PoC」
  - R-058 低價偏離（§58）：< 80% low、< 60% high（觀察區 + 偏低區）
  - R-087 集中度（§87）：近 12 月同機關同廠商 ≥ 5 件且 ≥ 70%
  - R-049 小額未公開（§49）：預算 15~150 萬走限制性卻未公開取得
  - R-033 流標重招（§33）：同案先無法決標後又決標
  - R-022 純限制性招標（§22）：標示需查驗依據款項

## 資料來源
- 全國法規資料庫 A0030057：https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0030057
- 同步方式：`python scripts/fetch_law.py`（無 API，HTML 解析）
- 版本識別：`amended_date`（目前 108-05-22，共 123 條）

## 相關 issue
#10

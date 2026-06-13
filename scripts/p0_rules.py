"""P0 標案判定規則 — 純布林、零 LLM（pilot 鐵則）。

evaluator 錨在非 LLM 客觀信號：字串比對（機關白名單 OR 關鍵字）+ 既有軟體類粗篩。
P0(row) 為真 = 軟體類候選（既有 pre_filter 通過）
                AND (機關命中白名單 OR title 命中 P0 強/中關鍵字)
                AND title 不命中 P0 排除詞。

字典分層（單一事實源紀律）：
- 既有 KEYWORDS/BLACKLIST（fetch_bids.py）負責「是不是軟體類候選」的粗篩，**複用不重抄**。
- 本檔只定義「P0 加強層」：既有字典之上新增的機關白名單 + P0 專屬關鍵字/排除詞。
  與既有字典重疊的詞不在此重複列出（重疊由 pre_filter 已涵蓋）。
"""
from fetch_bids import BLACKLIST, KEYWORDS, pre_filter  # noqa: F401  複用既有字典（單一事實源）

# --- P0 機關白名單（§brief，pilot 期寬鬆，agency 子字串命中即算）---
P0_AGENCIES = [
    # 核心（做過/在做）
    "圖書館", "國立臺灣圖書館", "移民署", "法務部", "立法院",
    "數位發展部", "關務署", "中央銀行", "台灣中油", "臺灣中油",
    # 戰略目標
    "公共工程委員會", "審計部", "廉政署", "國家發展委員會", "政風",
    # 廣撒觀察
    "經濟部", "內政部", "教育部", "文化部", "交通部",
    "勞動部", "衛生福利部", "衛福部", "農業部",
]

# --- P0 加強關鍵字（既有 KEYWORDS 之外的補充；title 子字串命中）---
# 重疊既有 KEYWORDS 的詞（系統/軟體/資訊/網站/App/平台/數位/資料庫/雲端/AI/
# 人工智慧/網路…）不重列，由 pre_filter 已涵蓋。此處只補既有沒有的。
P0_KEYWORDS_EXTRA = [
    # 強信號補充
    "圖書館", "借閱", "無障礙", "WCAG", "開放資料", "行動", "入口網",
    "系統開發", "系統建置",
    # 中信號補充
    "API", "資料視覺化", "整合", "委外", "維護",
]

# --- P0 排除詞（避免誤中非軟體勞務；既有 BLACKLIST 已含工程類，此處補勞務雜項）---
P0_EXCLUDE_EXTRA = [
    "監視系統", "門禁", "清潔", "保全", "印刷", "翻譯",
]


def hit_agency(agency: str) -> bool:
    """機關白名單命中（子字串）。"""
    if not agency:
        return False
    return any(a in agency for a in P0_AGENCIES)


def hit_keyword(title: str) -> bool:
    """P0 關鍵字命中：既有 KEYWORDS 任一 OR P0 加強關鍵字任一。"""
    if not title:
        return False
    if any(k in title for k in KEYWORDS):
        return True
    return any(k in title for k in P0_KEYWORDS_EXTRA)


def hit_exclude(title: str) -> bool:
    """P0 排除詞命中（既有 BLACKLIST OR P0 排除補充）。命中即否決。"""
    if not title:
        return False
    if any(b in title for b in BLACKLIST):
        return True
    return any(e in title for e in P0_EXCLUDE_EXTRA)


def is_p0(row: dict) -> bool:
    """純布林 P0 判定。row 需含 'title' 與 'unit_name'（agency）。

    規則：
      1. 排除詞命中 → 否決（優先級最高）
      2. (機關白名單命中 OR P0 關鍵字命中) → P0
    注意：不在此重跑 pre_filter — 上游 fetch_pcc 已做軟體類粗篩，
    本 evaluator 只在候選集合上加 P0 升級判定。但若直接餵原始 row，
    呼叫端應自行確保已過軟體類粗篩；本函數仍以排除詞守最後一道。
    """
    title = (row.get("title") or "").strip()
    agency = (row.get("unit_name") or row.get("agency") or "").strip()
    if hit_exclude(title):
        return False
    return hit_agency(agency) or hit_keyword(title)

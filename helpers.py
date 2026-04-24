"""純函式 helpers — 獨立模組方便測試與重用。"""
import re

import pandas as pd

# IT 白名單（符合才算軟體開發類）
IT_CATEGORY_RE = re.compile(r"^(勞務類(84\d|75)|財物類(452|47))")

# 凌網系列：任一匹配即標示為自家
OWN_COMPANIES = ["凌網資訊", "凌網全球", "HYWEB", "網擎"]

# 攻略 Watch List（鎖定機關）
WATCH_UNITS = [
    "衛生福利部", "食品藥物管理署", "疾病管制署",
    "考試院", "考選部",
    "國立臺灣師範大學", "國立臺灣大學", "國立政治大學",
    "中央警察大學", "法務部調查局", "法務部",
    "衛生福利部嘉南療養院",
]

# O + R 強項關鍵字
STRENGTH_KEYWORDS = {
    "圖書館/閱讀": ["圖書館", "圖書", "借閱", "館藏", "閱讀"],
    "政府 App": ["App", "APP", "應用程式", "行動"],
    "開放資料": ["開放資料", "Open Data", "資料集", "資料開放", "資料平台", "資料平臺"],
    "AI/LLM": ["AI", "人工智慧", "機器學習", "LLM", "TAIDE", "語料", "生成式", "OCR", "NLP"],
    "無障礙": ["無障礙", "WCAG"],
    "網站/入口": ["網站", "入口網", "官網"],
}

# 需求主題關鍵字
DEMAND_THEMES = {
    "系統建置": ["系統建置", "建置案", "開發案", "新建", "導入"],
    "系統維運": ["維運", "維護", "保養", "年度維護", "委外維護"],
    "網站平台": ["網站", "平台", "平臺", "入口網"],
    "App 應用": ["App", "APP", "應用程式", "行動", "Mobile"],
    "資訊服務": ["資訊服務", "資料處理", "委託服務"],
    "資安": ["資安", "資訊安全", "防火牆", "資通安全"],
    "雲端": ["雲端", "Cloud", "虛擬化", "容器"],
    "AI/數據": ["AI", "人工智慧", "大數據", "數據分析", "機器學習"],
    "資料庫": ["資料庫", "Database", "DB"],
    "GIS/地圖": ["GIS", "地理資訊", "地圖", "圖資"],
    "資訊設備": ["資訊設備", "電腦", "伺服器", "筆電", "平板"],
    "網路": ["網路", "交換器", "路由器", "WIFI", "Wi-Fi"],
    "教育訓練": ["訓練", "課程", "教育", "研習"],
    "監控/監視": ["監視", "監控", "攝影機", "CCTV"],
    "身分識別": ["身分", "認證", "簽章", "FIDO"],
}

# 機關類型分類
UNIT_TYPE_RULES = [
    ("國營事業", re.compile(r"台灣電力|中油|台灣自來水|中華郵政|台灣鐵路|台灣糖業|台灣肥料|桃園國際機場|漢翔|中華電信|台灣港務|中央印製|台灣菸酒|台船|臺灣銀行|土地銀行|合作金庫|第一銀行|華南銀行|彰化銀行|兆豐|陽信|臺北自來水")),
    ("醫療", re.compile(r"醫院|醫療|衛生所|健保|疾病管制")),
    ("學校", re.compile(r"大學|學院|高中|高商|國中|國小|幼兒園|學校|國民中學|國民小學|職校|技術學院|科技大學")),
    ("地方政府", re.compile(r"縣政府|市政府|鄉公所|鎮公所|區公所|縣|市立|鄉立|鎮立|村里")),
    ("中央部會", re.compile(r"行政院|立法院|司法院|考試院|監察院|總統府|部$|署$|委員會|國家|中央|銓敘|審計|法務部|教育部|國防部|外交部|財政部|經濟部|交通部|農業部|衛生福利|文化部|內政部|勞動部|數位發展|環境|國科會|通傳")),
]

HIGHLIGHT_COLOR = "#E74C3C"


def count_themes(titles):
    result = {}
    for theme, kws in DEMAND_THEMES.items():
        n = sum(any(k in str(t) for k in kws) for t in titles)
        if n:
            result[theme] = n
    return result


def classify_unit(name):
    if name is None or pd.isna(name) or name == "":
        return "其他"
    for label, rx in UNIT_TYPE_RULES:
        if rx.search(str(name)):
            return label
    return "其他"


def is_own(company):
    if company is None or pd.isna(company) or company == "":
        return False
    return any(k in str(company) for k in OWN_COMPANIES)

# User Stories

以 user story 為單位組織需求與 spec。每個 story 底下可有多個 feature。

## 現有 stories

| # | Story | 狀態 | 說明 |
|---|---|---|---|
| [001](001-pre-bid-intel/) | 投標前對手情報 | 🟢 演進中 | 業務查對手、機關、擅長領域 |
| [002](002-opportunity-radar/) | 機會雷達（可投標案篩選） | 🟢 已上線 | tab5 雷達 |
| [003](003-market-watch/) | 市場觀測（大盤趨勢） | 🟢 已上線 | tab1/2/4 市場/趨勢/機關 |
| [004](004-watch-list/) | Watch List（追蹤關注標案） | 🟢 已上線 | Watch List |

## 目錄結構
```
stories/
└── NNN-slug/
    ├── STORY.md                      # user story 主文件
    ├── decisions.md (optional)       # 跨 feature 決策紀錄
    └── features/
        └── feature-slug/
            ├── SPEC.md
            ├── plan.md
            └── todo.md
```

## 流程
新功能需求 → 確認屬於哪個 story → 在該 story 下的 `features/` 建 feature 資料夾 → 走 `/spec` → `/plan` → `/build`。

# Story 002：機會雷達

## User Story
**As a** 業務
**I want to** 從全部標案中自動篩出「值得投」的案件
**So that** 不用每天手動翻標案網，時間花在真正的機會上

## 成功指標
每日打開即看到當日新增的候選標案清單，無需自行過濾噪音。

## 涵蓋 features
- [x] **opportunity-radar**（雷達頁）— 已上線
  - 位置：app.py tab5「雷達」
  - 詳細：[SPEC.md](features/opportunity-radar/SPEC.md)
  - 依賴 Story 004 的 Watch List（機關清單）與 `STRENGTH_KEYWORDS`（強項關鍵字）

## 相關 commits
27624b0

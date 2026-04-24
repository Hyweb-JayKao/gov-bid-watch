# Story 004：Watch List（鎖定關鍵客戶機關）

## User Story
**As a** 業務
**I want to** 定義一份重點經營的機關清單，在機會雷達時一鍵只看這些機關
**So that** 不錯過 O+R 關鍵客戶的任何新案

## 成功指標
打開機會雷達勾「只看 Watch List」即可聚焦重點機關，清單維護成本極低。

## 涵蓋 features
- [x] **watch-list**（鎖定機關清單）— 已上線
  - 清單：`helpers.py:WATCH_UNITS`
  - 使用處：`app.py` tab5 雷達 expander + checkbox 篩選
  - 詳細：[SPEC.md](features/watch-list/SPEC.md)

## 相關 commits
d90c0a9, 27624b0

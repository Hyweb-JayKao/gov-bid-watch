# Story 001：投標前對手情報

## User Story
**As a** 業務（投標決策者）
**I want to** 快速查對手近期得標狀況、擅長領域、合作機關
**So that** 決定要不要投這個案、怎麼開價、如何避開硬對手

## 成功指標
投標前 5 分鐘內能完成一輪對手情報收集。

## 涵蓋 features
- [x] **company-lookup**（公司查詢）— 2026-04-24 上線（commit c4b6ed1）
  - 輸入公司名 → 12 個月得標案 + 金額摘要 + Top 5 機關
- [ ] **competitor-timeline**（時間軸圖）— issue #1
- [ ] **theme-distribution**（擅長領域雷達）— issue #1
- 📎 相關既有功能（未寫 SPEC，code 為準）：tab3 競爭、tab6 對手查詢

## 相關 commits
c4b6ed1, a75d0b1, c5e4df7

# SPEC: Watch List（鎖定機關清單）

> 反向工程文件（2026-04-24 補）。位置：`helpers.py:WATCH_UNITS` + `app.py` tab5 雷達 L420-422, L428, L435-436。

## 1. Objective
把「O+R 重點經營的機關」定義成一份清單，在機會雷達時可一鍵過濾只看這些機關的案。

**User**：業務，鎖定關鍵客戶機關不讓機會流失。

## 2. 實作位置
- **清單定義**：`helpers.py:WATCH_UNITS`（目前 12 個機關）
- **展示**：`app.py` tab5「雷達」expander「📋 Watch List 鎖定機關」
- **使用**：tab5 篩選 checkbox「只看 Watch List 機關」

## 3. 比對邏輯
`unit_name` **包含**清單中任一字串即命中（子字串比對）。例：
- `WATCH_UNITS` 有「衛生福利部」→ 會命中「衛生福利部」、「衛生福利部嘉南療養院」、「衛生福利部中央健保署」

## 4. 維護方式
改清單需編輯 `helpers.py:WATCH_UNITS`（list of str），無 UI 編輯介面。

## 5. Boundaries
- 清單 hardcoded，不支援 runtime 修改
- 無持久化（無 DB / 無 user-level watch list）
- 目前只在 tab5 使用；其他 tab 未接入

## 6. 已知限制
- 子字串比對會誤命中（例「法務部」會命中「法務部調查局」，這多半是預期行為但要留意）
- 無「排除」語法，只能正向包含

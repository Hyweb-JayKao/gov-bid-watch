# gov-bid-watch watcher 失敗 | 2026-06-23

- 嚴重度：中（單日失敗，可能間歇）
- 失敗原因：daily watcher run 失敗（fetch/merge/watcher 任一 step）
- 失敗 run：https://github.com/Hyweb-JayKao/gov-bid-watch/actions/runs/28005843554
- 上次成功：2026-06-22T05:06:27（距今 1 天）

## 怎麼處理
- 單日失敗。fetch 已內建 retry（401/5xx/timeout 指數 backoff 5 次），
  仍失敗代表閘道持續抖動或 retry 用盡 → 觀察隔日是否自動恢復。
- 若連續 ≥ 3 天無成功，本告警會自動升級為 high。

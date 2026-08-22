<!-- ORG-SHARED START：勿手改，SoT＝jooca-tw/.github/claude-shared.md，改規則走該檔＋sync-claude-shared.sh -->
## 全組織共用規則（ORG-SHARED；勿在各 repo 手改，SoT＝jooca-tw/.github/claude-shared.md）

> 這段由 `jooca-tw/.github` 的 `scripts/sync-claude-shared.sh` 蓋章同步到各 repo CLAUDE.md。要改規則：改 SoT 檔後重跑腳本。repo 專屬規則寫在本區塊外，可覆蓋本區塊（更具體的指示優先）。

### 留人紅線（任何 agent、任何 repo 都成立）

- **merge PR / 部署 / 對外交付（送件、發佈、寄出）/ 花錢 / 簽約**一律留給人類，AI 只到初稿或 PR 開好為止。
- 憑證 / service account 金鑰 / token **不入版控**。

### 語言與風格

- 繁體中文、簡潔直接、先答案後解釋；禁 AI 黑話——工具/技術名詞先講它做什麼＋當下例子。

### 工具現況（全組織事實，過期改 SoT 不改本地）

- PDF → `pdftotext -layout <f>.pdf -`（禁用 markitdown 讀 PDF：欄位會併格漂移）。
- pptx / docx / xlsx / .msg / epub / zip → `markitdown <f> -o <f>.md`。
- 跨模型交叉驗證用 **codex**（`codex exec -o <檔> "<prompt>"`）；額度滿的症狀是靜默 timeout 不報錯。
- gemini CLI 個人版 2026-07-27 起已被 Google 停用，任何流程不得再叫它。

### Git

- commit message 一句話寫「解決了什麼問題」（`<prefix>: 動詞+具體問題`）。
- **必用 pathspec 限定**（`git commit <檔> -m ...`，禁裸 commit）——並行 session 會互掃 staging。
- 中文檔名 grep git 輸出前加 `-c core.quotePath=false`，否則引號錨定全漏。

### 事實紀律

- PR / issue / 分支狀態斷言，動工前必用 `gh` / `git` 現查，不信 brief、快照或記憶。
- 日期不推算，跑 `TZ='Asia/Taipei' date '+%Y-%m-%d %A %H:%M:%S %Z'`。
- 數字、法規編號、金額、日期、人名職稱，給不出來源就標「待查證」，不直接寫進交付物——政府案有數字就有查核。

### Repo 結構

- 助理 repo 頂層槽位契約（README 憲章/CLAUDE.md/MEMORY.md/docs/adr/docs/specs/docs/kn/sop/workspace/.claude）＝`jooca-tw/.github/governance/repo-structure.md`；新增或搬移頂層目錄前先讀，skill 唯一位置＝`.claude/skills/`。

### 協作紀律

- 看不出受眾、目的或完成標準時，**先問再做**，不猜一個做下去。
- 回報完成時逐條對照驗收條件**附證據**（檔案真的在、指令真的跑過、輸出實貼），不說「應該可以了」。
- 同一處修 3 次都失敗就**停下回報**：重述問題、換路，不再試第四次——三種修法卡同一處＝對問題的理解錯了。
<!-- ORG-SHARED END -->

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->

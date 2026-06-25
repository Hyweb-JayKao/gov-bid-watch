# VERIFY — gov-bid-watch 驗證指令

> harness 與人類自驗的單一指令來源。CI（`.github/workflows/ci.yml`）、
> pre-commit-gate 閘3（`PRECOMMIT_TEST_CMD`）、獨立 verifier 全部對齊此檔。

## 測試（全套）

```bash
python3 -m pytest -q
```

- 期望：全 passed（xfail 不算失敗）。目前 baseline：92 passed / 5 xfailed。
- 此指令同時是：
  - CI 在 `pull_request → main` 跑的內容（loop 達標的客觀信號）
  - `PRECOMMIT_TEST_CMD` 應設成的值（commit 前閘3 本機快檢）
  - 獨立 verifier 重跑「確認 CI 綠非環境僥倖」的內容

## 安裝依賴

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

## pre-commit-gate 環境變數（harness loop 內 export）

```bash
export PRECOMMIT_TEST_CMD="python3 -m pytest -q"
# 預設門檻沿用 hook 內建：PRECOMMIT_MAX_DIFF=150
```

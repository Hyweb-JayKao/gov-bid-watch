"""harness ①Ship-PR-Until-Green loop 的退出語義回歸測試。

驗 runner 的三層終止 / 不可逆邊界守門 / 客觀 CI 信號 exit code 契約（spec §2.2/§2.3）：
  exit 0 = PASS（本機綠 + 遠端 CI success，且 CI run 的 SHA==本輪 HEAD）
  exit 1 = FAIL（本機紅 / push 失敗 / 遠端 CI 紅，回去改）
  exit 2 = 拒絕（不可逆邊界：在受保護 / 非 feature 分支）
  exit 3 = STOP（保險絲 / 無進展停 / 缺客觀 CI 信號，回報人）

本檔含 codex 對抗審查指出原測試刻意避開的「最危險路徑」：
  - CI 不可用 / 找不到本輪 SHA 的 run → 必須 STOP(3)，不可當綠 exit 0（#1）
  - push 失敗 → 必須 FAIL(1)，不可吞 exit code（#2）
  - 等的 CI run 的 SHA 必須 == 本輪 HEAD，舊 run 不算（#2）
  - 受保護分支守門用白名單，env 不可繞過放行（#3）
  - MAX_ITER off-by-one：「最多 8 輪」第 8 輪後即停（#7）
測試以子行程跑 runner、用 PATH 前置 stub 攔截 git/gh，斷言 exit code。
"""
import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / ".claude" / "harness" / "ship-pr-loop.sh"
STATE_DIR = ROOT / ".claude" / "harness" / ".state"

# 白名單內、會成功（綠）/失敗（紅）的本機測試命令。
# 經 runner 的 `read -ra` 空白分詞 → argv，故參數內不可含空白。
GREEN_CMD = "python3 --version"        # exit 0
RED_CMD = "python3 -c raise"           # exit 1（raise 觸發 SyntaxError 仍非 0；穩定為紅）


def _write_stub(bindir: Path, name: str, body: str):
    p = bindir / name
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(env_extra, iter0=0, scores=None, stub_git=None, stub_gh=None):
    """跑一輪 runner，回 (returncode, stderr)。

    scores=預灌分數歷史；stub_git/stub_gh=注入假 git/gh 的 bash body（攔截危險路徑）。
    """
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    STATE_DIR.mkdir(parents=True)
    (STATE_DIR / "loop.json").write_text(
        json.dumps({"iter": iter0, "start_ts": int(time.time())})
    )
    if scores:
        (STATE_DIR / "scores.log").write_text("\n".join(scores) + "\n")

    env = {**os.environ, **env_extra}

    # 若要注入 stub，建一個臨時 bin 目錄前置到 PATH。
    if stub_git or stub_gh:
        import tempfile
        bindir = Path(tempfile.mkdtemp(prefix="harness-stub-"))
        real_git = shutil.which("git")
        # git stub：未被攔截的子命令一律 delegate 真 git（runner 內部要用 rev-parse 等）
        if stub_git is None:
            stub_git = f'exec "{real_git}" "$@"'
        _write_stub(bindir, "git", f'REAL_GIT="{real_git}"\n{stub_git}')
        real_gh = shutil.which("gh") or "/usr/bin/false"
        if stub_gh is None:
            stub_gh = f'exec "{real_gh}" "$@"'
        _write_stub(bindir, "gh", stub_gh)
        env["PATH"] = f"{bindir}:{env.get('PATH','')}"

    p = subprocess.run(
        ["bash", str(RUNNER)], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=90,
    )
    return p.returncode, p.stderr


# ───────── 基本契約 ─────────

def test_runner_exists_and_executable():
    assert RUNNER.exists(), "ship-pr-loop.sh 必須存在"
    assert os.access(RUNNER, os.X_OK), "runner 須可執行"


def test_local_red_fails():
    # 本機紅（白名單內命令 exit 1）、史不足 → FAIL(1)
    rc, err = _run({"TEST_CMD": RED_CMD}, iter0=0)
    assert rc == 1, f"本機紅應 exit 1，得 {rc}: {err}"
    assert "FAIL" in err


def test_test_cmd_whitelist_rejects_non_python():
    # codex 建議：TEST_CMD 白名單。非 python/pytest 首字 → 拒絕(2)
    rc, err = _run({"TEST_CMD": "rm -rf /tmp/should-not-run"}, iter0=0)
    assert rc == 2, f"非白名單 TEST_CMD 應拒絕 exit 2，得 {rc}: {err}"
    assert "白名單" in err


# ───────── 保險絲：迭代上限（#7 off-by-one）─────────

def test_fuse_max_iter_off_by_one():
    # 「最多 MAX_ITER 輪」：已完成 MAX_ITER 輪後再呼叫即停，不可多跑一輪。
    # iter0=2, MAX_ITER=2 → 已完成 2 輪 → 本次 STOP(3)，不該起第 3 輪。
    rc, err = _run({"MAX_ITER": "2", "TEST_CMD": RED_CMD}, iter0=2)
    assert rc == 3, f"達 MAX_ITER 應 exit 3（不多跑一輪），得 {rc}: {err}"
    assert "保險絲" in err


def test_max_iter_allows_exactly_n_rounds():
    # 邊界：已完成 MAX_ITER-1 輪 → 本次應正常起最後一輪（不被保險絲擋），落本機紅 FAIL(1)。
    rc, err = _run({"MAX_ITER": "8", "TEST_CMD": RED_CMD}, iter0=7)
    assert rc == 1, f"第 8 輪應正常執行（非保險絲），得 {rc}: {err}"


# ───────── 無進展停 ─────────

def test_no_progress_stops():
    rc, err = _run(
        {"NO_PROGRESS_N": "3", "MAX_ITER": "8", "TEST_CMD": RED_CMD},
        iter0=0, scores=["1", "1"],
    )
    assert rc == 3, f"連續無進展應 exit 3，得 {rc}: {err}"
    assert "無進展" in err


def test_progress_does_not_false_stop():
    rc, _ = _run(
        {"NO_PROGRESS_N": "3", "TEST_CMD": RED_CMD},
        iter0=0, scores=["2", "2"],
    )
    assert rc == 1, "分數有降應走 FAIL(1) 非 STOP"


# ───────── 不可逆邊界守門（#3 白名單）─────────

def _cur_branch():
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()


def _run_on_branch(branch, env_extra, **kw):
    """模擬「當前分支＝branch」跑 runner（驗受保護分支判定），不真的切 branch。

    不能在 worktree 切到 main（main 被另一 worktree 佔用，checkout 會失敗並污染後續
    測試）。改注入 git stub：攔 `rev-parse --abbrev-ref HEAD` 回假 branch 名，其餘
    git 子命令 delegate 真 git。guard 只看 cur_branch 的輸出，這樣即可精準驗分支判定。
    """
    git_stub = (
        'args="$*"\n'
        'case "$args" in\n'
        f'  *"rev-parse --abbrev-ref HEAD"*) echo "{branch}"; exit 0 ;;\n'
        'esac\n'
        'exec "$REAL_GIT" "$@"\n'
    )
    return _run(env_extra, stub_git=git_stub, **kw)


def test_protected_branch_hard_block():
    # 在內建受保護分支 main 上 → 第一層內建硬擋(2)，不靠任何 env。
    rc, err = _run_on_branch("main", {}, iter0=0)
    assert rc == 2, f"受保護分支應拒絕 exit 2，得 {rc}: {err}"
    assert "受保護分支" in err


def test_non_feature_branch_blocked_by_whitelist():
    # 白名單只允 feat/fix/... 開頭。把白名單收窄成不匹配當前分支 → 第二層擋(2)。
    rc, err = _run({"ALLOWED_FEATURE_RE": "^nonexistent-prefix/.+"}, iter0=0)
    assert rc == 2, f"非 feature 分支應拒絕 exit 2，得 {rc}: {err}"
    assert "白名單" in err or "feature" in err


def test_protected_block_not_bypassable_by_env_clearing_and_widening():
    # ★ codex#3 第 2 輪假綠根因：上輪可用 PROTECTED_RE='^$' ALLOWED_FEATURE_RE='.*'
    #   同時清空硬擋 + 放寬白名單，讓 main 兩層全繞過。
    #   現在受保護判定錨在內建常數（env 動不了），這組 env 在 main/master 仍須拒絕(2)。
    for b in ("main", "master"):
        rc, err = _run_on_branch(
            b,
            {"PROTECTED_RE": "^$", "ALLOWED_FEATURE_RE": ".*",
             "PROTECTED_EXTRA_RE": "^$"},
            iter0=0,
        )
        assert rc == 2, (
            f"env 清空+放寬不該繞過內建保護（branch={b}），得 {rc}: {err}")
        assert "受保護分支" in err


def test_protected_extra_re_can_only_tighten():
    # env 只能「收緊」：PROTECTED_EXTRA_RE 可把額外分支（如 staging/x）也列為受保護。
    rc, err = _run_on_branch(
        "staging/x", {"PROTECTED_EXTRA_RE": "^staging/.*$"}, iter0=0)
    assert rc == 2, f"PROTECTED_EXTRA_RE 追加保護應拒絕 exit 2，得 {rc}: {err}"
    assert "受保護分支" in err


# ───────── push 失敗（#2）─────────

def test_push_failure_fails():
    # 本機綠 → 進到 push；stub git 讓 push 失敗 → 必須 FAIL(1)，不可吞掉。
    git_stub = '''
case "$1" in
  *) ;;
esac
# 攔截 push 子命令（可能帶 -C <root> 前綴）
for a in "$@"; do
  if [ "$a" = "push" ]; then echo "fatal: push rejected (stub)" >&2; exit 1; fi
done
exec "$REAL_GIT" "$@"
'''
    rc, err = _run({"TEST_CMD": GREEN_CMD}, iter0=0, stub_git=git_stub)
    assert rc == 1, f"push 失敗應 exit 1，得 {rc}: {err}"
    assert "push" in err


# ───────── 缺客觀 CI 信號（#1）─────────

def test_ci_unavailable_stops_not_pass():
    # 本機綠 + push 成功(stub no-op) + gh 不可用 → 不可當綠 exit 0，必須 STOP(3)。
    git_stub = '''
for a in "$@"; do
  if [ "$a" = "push" ]; then echo "stub push ok" >&2; exit 0; fi
done
exec "$REAL_GIT" "$@"
'''
    gh_stub = 'echo "gh stub: command not found path simulated" >&2; exit 127'
    # 用「找不到 gh」的方式：把 gh stub 直接 exit 127 模擬不可用
    rc, err = _run(
        {"TEST_CMD": GREEN_CMD, "CI_POLL_TRIES": "2", "CI_POLL_SLEEP": "0"},
        iter0=0, stub_git=git_stub, stub_gh=gh_stub,
    )
    # gh 存在但 run list 拿不到 run → return 2 → STOP(3)，不可當綠 exit 0
    assert rc == 3, f"缺客觀 CI 信號應 STOP exit 3，不可當綠，得 {rc}: {err}"
    assert "CI" in err


def test_ci_run_sha_must_match_head():
    # 本機綠 + push ok + gh run list 只回「舊 commit」的 run（headSha != HEAD）
    #   → 找不到本輪 SHA 對應 run → return 2 → STOP(3)，不可拿舊綠當本輪成功。
    git_stub = '''
for a in "$@"; do
  if [ "$a" = "push" ]; then echo "stub push ok" >&2; exit 0; fi
done
exec "$REAL_GIT" "$@"
'''
    # runner 用 `gh run list ... -q 'select(.headSha==$expect)'` 由 gh 自己過濾。
    # 模擬：branch 上只有舊 commit 的 run，過濾後無匹配 → 回空。代表「找不到本輪 SHA 的 run」。
    gh_stub = '''
if [ "$1" = "run" ] && [ "$2" = "list" ]; then
  echo ""   # select(headSha==本輪SHA) 過濾後無匹配（只有舊 run）
  exit 0
fi
exit 0
'''
    rc, err = _run(
        {"TEST_CMD": GREEN_CMD, "CI_POLL_TRIES": "2", "CI_POLL_SLEEP": "0"},
        iter0=0, stub_git=git_stub, stub_gh=gh_stub,
    )
    assert rc == 3, f"CI run SHA 不符本輪 HEAD 應 STOP exit 3，得 {rc}: {err}"

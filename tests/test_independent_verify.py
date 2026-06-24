"""harness ④Independent Verifier 的機械驗收 exit code 契約回歸測試。

驗 independent-verify.sh 的達標判定（spec §3.3）：本機綠 AND 遠端 CI success。
  exit 0 = 機械驗收過（本機綠 + CI 至少一個真 pass 且無 fail/pending）
  exit 1 = 不過（本機紅 / CI 紅）
  exit 2 = 未定論（CI pending / 全 skipping / 無 check / 未帶 PR / gh 不可用）

本檔含 codex 第 2 輪 #4 指出的假綠根因：
  「全是 skipping/neutral」原本被當 pass → 必須改判 UNKNOWN/FAIL，不可 exit 0。
測試以子行程跑腳本、PATH 前置 stub 攔截 gh pr checks 的輸出，斷言 exit code。
"""
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".claude" / "harness" / "independent-verify.sh"
GREEN_CMD = "python3 --version"   # 本機綠
RED_CMD = "python3 -c raise"      # 本機紅


def _write_stub(bindir: Path, name: str, body: str):
    p = bindir / name
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(pr_arg, test_cmd=GREEN_CMD, gh_checks_output=None):
    """跑 independent-verify.sh，回 (returncode, stderr)。

    gh_checks_output: 模擬 `gh pr checks` 的多行輸出（第二欄＝狀態），None＝不 stub gh。
    """
    env = {**os.environ, "TEST_CMD": test_cmd}
    bindir = Path(tempfile.mkdtemp(prefix="iv-stub-"))
    if gh_checks_output is not None:
        # gh stub：只攔 `gh pr checks <PR>`，印出模擬的 checks 表（tab 分欄）。
        # 其它 gh 子命令（如 command -v 探測）走 exit 0。
        lines = "\n".join(gh_checks_output)
        body = (
            'if [ "$1" = "pr" ] && [ "$2" = "checks" ]; then\n'
            f'  printf "%s\\n" "{lines}"\n'
            '  exit 0\n'
            'fi\n'
            'exit 0\n'
        )
        _write_stub(bindir, "gh", body)
        env["PATH"] = f"{bindir}:{env.get('PATH','')}"
    args = ["bash", str(SCRIPT)]
    if pr_arg is not None:
        args.append(pr_arg)
    p = subprocess.run(args, cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=90)
    return p.returncode, p.stderr


def test_script_exists_executable():
    assert SCRIPT.exists() and os.access(SCRIPT, os.X_OK)


def test_local_red_fails():
    # 本機紅 → 機械驗收不過(1)，連 CI 都不用看。
    rc, err = _run(None, test_cmd=RED_CMD)
    assert rc == 1, f"本機紅應 exit 1，得 {rc}: {err}"


def test_no_pr_is_half_check_not_pass():
    # 本機綠但未帶 PR 號＝只做本機半套，無遠端 CI 信號 → 非 0(2)，不可當完整驗收過。
    rc, err = _run(None, test_cmd=GREEN_CMD)
    assert rc == 2, f"未帶 PR 應半套 exit 2，得 {rc}: {err}"


def test_real_pass_passes():
    # 本機綠 + CI 至少一個真 pass、無 fail/pending → 機械驗收過(0)。
    rc, err = _run("20", gh_checks_output=["pytest\tpass\t10s\thttp://x"])
    assert rc == 0, f"真 pass 應 exit 0，得 {rc}: {err}"


def test_ci_fail_fails():
    rc, err = _run("20", gh_checks_output=["pytest\tfail\t10s\thttp://x"])
    assert rc == 1, f"CI 紅應 exit 1，得 {rc}: {err}"


def test_ci_pending_not_pass():
    rc, err = _run("20", gh_checks_output=[
        "pytest\tpass\t10s\thttp://x", "lint\tpending\t-\thttp://y"])
    assert rc == 2, f"尚有 pending 應未定論 exit 2，得 {rc}: {err}"


def test_all_skipping_is_not_pass():
    # ★ codex#4 假綠根因：全 skipping（什麼都沒真跑）原被當 pass。必須改判未定論(2)。
    rc, err = _run("20", gh_checks_output=[
        "pytest\tskipping\t-\thttp://x", "lint\tskipping\t-\thttp://y"])
    assert rc == 2, f"全 skipping 不可當綠，應 exit 2，得 {rc}: {err}"
    assert "skipping" in err or "未定論" in err or "UNKNOWN" in err


def test_all_neutral_is_not_pass():
    # neutral 同 skipping：沒有任何一個真 pass → 不可放行。
    rc, err = _run("20", gh_checks_output=["x\tneutral\t-\thttp://x"])
    assert rc == 2, f"全 neutral 不可當綠，應 exit 2，得 {rc}: {err}"


def test_no_check_is_not_pass():
    # 有 PR 但完全沒 check（CI 未觸發）→ 未定論(2)。
    rc, err = _run("20", gh_checks_output=[])
    assert rc == 2, f"無 check 應 exit 2，得 {rc}: {err}"


def test_pass_plus_skipping_still_passes():
    # 至少一個真 pass + 其餘 skipping（無 fail/pending）→ 仍算 success(0)。
    # （skipping 的 job 是矩陣裡沒命中的條件，不代表沒驗東西）
    rc, err = _run("20", gh_checks_output=[
        "pytest\tpass\t10s\thttp://x", "optional\tskipping\t-\thttp://y"])
    assert rc == 0, f"有真 pass + skipping 應 exit 0，得 {rc}: {err}"

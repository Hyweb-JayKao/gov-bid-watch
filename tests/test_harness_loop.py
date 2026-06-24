"""harness ①Ship-PR-Until-Green loop 的退出語義回歸測試。

驗 runner 的三層終止 / 不可逆邊界守門 exit code 契約穩定（spec §2.2/§2.3）：
  exit 1 = FAIL（本機紅，回去改）
  exit 2 = 拒絕（不可逆邊界：在受保護分支）
  exit 3 = STOP（保險絲 / 無進展停，回報人）
測試以子行程跑 runner，餵狀態檔模擬各情境，斷言 exit code。
不觸發 push（所有情境停在 push 之前），故不依賴網路 / gh / remote。
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / ".claude" / "harness" / "ship-pr-loop.sh"
STATE_DIR = ROOT / ".claude" / "harness" / ".state"


def _run(env_extra, iter0=0, scores=None):
    """跑一輪 runner，回 (returncode, stderr)。scores=預灌分數歷史。"""
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    STATE_DIR.mkdir(parents=True)
    (STATE_DIR / "loop.json").write_text(
        json.dumps({"iter": iter0, "start_ts": int(time.time())})
    )
    if scores:
        (STATE_DIR / "scores.log").write_text("\n".join(scores) + "\n")
    env = {**os.environ, **env_extra}
    p = subprocess.run(
        ["bash", str(RUNNER)], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=60,
    )
    return p.returncode, p.stderr


def test_runner_exists_and_executable():
    assert RUNNER.exists(), "ship-pr-loop.sh 必須存在"
    assert os.access(RUNNER, os.X_OK), "runner 須可執行"


def test_fuse_max_iter_stops():
    # iter 已達上限，再跑一輪應 STOP(3)
    rc, err = _run({"MAX_ITER": "2", "TEST_CMD": "false"}, iter0=2)
    assert rc == 3, f"超過 MAX_ITER 應 exit 3，得 {rc}: {err}"
    assert "保險絲" in err


def test_no_progress_stops():
    # 三輪同分(1,1,1)、本輪仍紅 → 無進展停(3)
    rc, err = _run(
        {"NO_PROGRESS_N": "3", "MAX_ITER": "8", "TEST_CMD": "false"},
        iter0=0, scores=["1", "1"],
    )
    assert rc == 3, f"連續無進展應 exit 3，得 {rc}: {err}"
    assert "無進展" in err


def test_progress_does_not_false_stop():
    # 分數在降(2,2,→1) 不應誤判無進展，落到本機紅 FAIL(1)
    rc, _ = _run(
        {"NO_PROGRESS_N": "3", "TEST_CMD": "false"},
        iter0=0, scores=["2", "2"],
    )
    assert rc == 1, f"分數有降應走 FAIL(1) 非 STOP，得 {rc}"


def test_local_red_fails():
    # 首輪本機紅、史不足 → FAIL(1)
    rc, err = _run({"TEST_CMD": "false"}, iter0=0)
    assert rc == 1
    assert "FAIL" in err


def test_irreversible_branch_guard():
    # 把當前分支設為受保護 → 拒絕(2)
    cur = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    rc, err = _run({"BRANCH_PREFIX_MAIN": cur}, iter0=0)
    assert rc == 2, f"受保護分支應拒絕 exit 2，得 {rc}: {err}"
    assert "受保護分支" in err

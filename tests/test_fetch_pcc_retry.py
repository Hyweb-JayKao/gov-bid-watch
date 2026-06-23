"""fetch_pcc retry 行為測試：401/5xx/timeout 重試、永久錯不重試、用盡上限放棄。

不打真 TwinkleAI；mock MCP.s.post 控制回應序列。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_pcc  # noqa: E402
from fetch_pcc import MCP, RETRY_STATUS, TransientHTTPError  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """把 tenacity 的 wait 改 0，避免測試真的 sleep 指數秒數。

    @retry 包好後 MCP._post.retry 是 Retrying 物件，直接改它的 wait 即可，
    不需重包 decorator。"""
    from tenacity import wait_none
    monkeypatch.setattr(MCP._post.retry, "wait", wait_none())


def _resp(status, text="", headers=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = headers or {}
    return r


def _mcp_no_init():
    """建一個略過 __init__（不發 initialize）的 MCP，方便單測 _post。"""
    m = MCP.__new__(MCP)
    m.s = MagicMock()
    m.h = {}
    m._id = 0
    return m


def _data_resp():
    return _resp(200, text='data: {"jsonrpc":"2.0","id":1,"result":{}}\n')


def test_retry_recovers_after_intermittent_401():
    """前兩次 401（裸 nginx 閘道抖動），第三次成功 → 不該 raise。"""
    m = _mcp_no_init()
    nginx401 = _resp(401, "<html><head><title>401 Authorization Required</title></head></html>")
    m.s.post.side_effect = [nginx401, nginx401, _data_resp()]
    out = m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert m.s.post.call_count == 3
    assert isinstance(out, list)


def test_retry_recovers_after_503():
    m = _mcp_no_init()
    m.s.post.side_effect = [_resp(503, "bad gateway"), _data_resp()]
    m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert m.s.post.call_count == 2


def test_retry_recovers_after_timeout():
    m = _mcp_no_init()
    m.s.post.side_effect = [requests.Timeout("slow"), _data_resp()]
    m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert m.s.post.call_count == 2


def test_retry_exhausts_then_raises_transient():
    """持續 401 → retry 用盡（5 次嘗試）→ 最終 raise TransientHTTPError（reraise）。"""
    m = _mcp_no_init()
    m.s.post.side_effect = [_resp(401, "nginx")] * 10
    with pytest.raises(TransientHTTPError):
        m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert m.s.post.call_count == 5  # stop_after_attempt(5)


def test_permanent_error_not_retried():
    """400（session 錯，非暫時性）→ 不重試，第一次就 raise RuntimeError。"""
    m = _mcp_no_init()
    m.s.post.side_effect = [_resp(400, "Missing session ID")]
    with pytest.raises(RuntimeError) as e:
        m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert not isinstance(e.value, TransientHTTPError)
    assert m.s.post.call_count == 1


def test_403_permanent_not_retried():
    m = _mcp_no_init()
    m.s.post.side_effect = [_resp(403, "forbidden")]
    with pytest.raises(RuntimeError):
        m._post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert m.s.post.call_count == 1


def test_retry_status_set_covers_gateway_codes():
    assert {401, 429, 500, 502, 503, 504} <= RETRY_STATUS
    assert 400 not in RETRY_STATUS
    assert 403 not in RETRY_STATUS

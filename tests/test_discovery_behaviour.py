"""Behaviour of Home Assistant discovery: env handling, caching, REST and websocket failures.

No real network is touched: aiohttp sessions and websockets.connect are stubbed.
"""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from aiohttp.client_exceptions import ClientConnectionError
from websockets.exceptions import InvalidHandshake

from central_core_mqtt_shared.ha import discovery
from central_core_mqtt_shared.ha.discovery import (
    HAConnection,
    HADiscoveryError,
    HADiscoveryResult,
    RESTDiscoveryResult,
    WebsocketDiscoveryResult,
)


# --------------------------------------------------------------------------- fakes


class _Response:
    def __init__(self, status=200, data=None, text="", json_exc=None):
        self.status = status
        self._data = data
        self._text = text
        self._json_exc = json_exc

    async def text(self):
        return self._text

    async def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._data


class _GetCtx:
    def __init__(self, resp=None, enter_exc=None):
        self._resp = resp
        self._enter_exc = enter_exc

    async def __aenter__(self):
        if self._enter_exc is not None:
            raise self._enter_exc
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _Session:
    """Session whose get() returns whatever ctx is registered for the path suffix."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []
        self.kwargs = None

    def __call__(self, **kwargs):  # acts as the aiohttp.ClientSession factory
        self.kwargs = kwargs
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url):
        self.requested.append(url)
        for suffix, ctx in self.routes.items():
            if url.endswith(suffix):
                return ctx
        raise AssertionError(f"unexpected url {url}")


class _WebSocket:
    def __init__(self, incoming, recv_exc=None):
        self._incoming = list(incoming)
        self._recv_exc = recv_exc
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def recv(self):
        if self._recv_exc is not None:
            raise self._recv_exc
        return self._incoming.pop(0)

    async def send(self, msg):
        self.sent.append(json.loads(msg))


def _fixed_uuid(monkeypatch, hex_value="req1"):
    monkeypatch.setattr(discovery.uuid, "uuid4", lambda: type("_U", (), {"hex": hex_value})())


def _patch_ws(monkeypatch, ws):
    seen = {}

    def fake_connect(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return ws

    monkeypatch.setattr(discovery.websockets, "connect", fake_connect)
    return seen


def _config_reply(request_id="req1", **overrides):
    msg = {"id": request_id, "type": "result", "success": True, "result": {"location_name": "Home"}}
    msg.update(overrides)
    return json.dumps(msg)


# --------------------------------------------------------------------------- environment


def test_discover_all_from_environment_requires_rest_url(monkeypatch):
    monkeypatch.delenv("HA_REST_URL", raising=False)
    with pytest.raises(HADiscoveryError, match="HA_REST_URL is required"):
        asyncio.run(discovery.discover_all_from_environment())


def test_discover_all_from_environment_treats_empty_url_as_missing(monkeypatch):
    monkeypatch.setenv("HA_REST_URL", "")
    with pytest.raises(HADiscoveryError, match="HA_REST_URL"):
        asyncio.run(discovery.discover_all_from_environment())


async def test_discover_all_from_environment_uses_env_credentials(monkeypatch):
    monkeypatch.setenv("HA_REST_URL", "https://ha.local:8123/")
    monkeypatch.setenv("HA_TOKEN", "envtok")
    captured = {}

    async def fake_discover_all(self, *, force_refresh=False):
        captured["base"] = self.rest_base_url
        captured["token"] = self._token
        captured["force"] = force_refresh
        return "sentinel"

    monkeypatch.setattr(HAConnection, "discover_all", fake_discover_all)
    result = await discovery.discover_all_from_environment(force_refresh=True)
    assert result == "sentinel"
    assert captured == {"base": "https://ha.local:8123", "token": "envtok", "force": True}


async def test_run_cli_prints_rest_and_websocket_json(monkeypatch, capsys):
    result = HADiscoveryResult(
        rest=RESTDiscoveryResult(base_url="https://h", services=[{"domain": "light"}], states=[]),
        websocket=WebsocketDiscoveryResult(websocket_url="wss://h/api/websocket", config={"v": 1}),
    )

    async def fake_env(*, force_refresh=False):
        return result

    monkeypatch.setattr(discovery, "discover_all_from_environment", fake_env)
    await discovery._run_cli()
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "rest": {"base_url": "https://h", "services": [{"domain": "light"}], "states": []},
        "websocket": {"websocket_url": "wss://h/api/websocket", "config": {"v": 1}},
    }


def test_module_run_as_script_reports_missing_env_not_nameerror():
    """Regression: the __main__ block ran before the classes were defined (NameError)."""
    env = {k: v for k, v in os.environ.items() if k not in {"HA_REST_URL", "HA_TOKEN"}}
    proc = subprocess.run(
        [sys.executable, "-m", "central_core_mqtt_shared.ha.discovery"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "NameError" not in proc.stderr
    assert "HADiscoveryError" in proc.stderr
    assert "HA_REST_URL is required" in proc.stderr


# --------------------------------------------------------------------------- construction


def test_empty_base_url_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        HAConnection("   ")


def test_ws_path_defaults_when_blank_and_strips_leading_slash():
    assert HAConnection("http://h:8123", ws_path="/").websocket_url == "ws://h:8123/api/websocket"
    assert HAConnection("https://h", ws_path="/custom/ws").websocket_url == "wss://h/custom/ws"


def test_rest_headers_without_token_have_no_authorization():
    assert HAConnection("https://h")._build_rest_headers() == {"Accept": "application/json"}


# --------------------------------------------------------------------------- REST


async def test_discover_rest_sends_auth_header_and_timeout(monkeypatch):
    session = _Session(
        {
            "api/services": _GetCtx(_Response(data=[{"domain": "light"}])),
            "api/states": _GetCtx(_Response(data=[{"entity_id": "binary_sensor.door"}])),
        }
    )
    monkeypatch.setattr(discovery.aiohttp, "ClientSession", session)
    conn = HAConnection("https://h/", token="tok", timeout=7)
    result = await conn.discover_rest()
    assert result == RESTDiscoveryResult(
        base_url="https://h",
        services=[{"domain": "light"}],
        states=[{"entity_id": "binary_sensor.door"}],
    )
    assert session.requested == ["https://h/api/services", "https://h/api/states"]
    assert session.kwargs["headers"]["Authorization"] == "Bearer tok"
    assert session.kwargs["timeout"].total == 7


async def test_fetch_json_non_200_includes_status_and_body():
    conn = HAConnection("https://h")
    session = _Session({"api/states": _GetCtx(_Response(status=401, text="401: Unauthorized"))})
    with pytest.raises(HADiscoveryError, match=r"https://h/api/states returned 401: 401: Unauthorized"):
        await conn._fetch_json(session, "/api/states")


@pytest.mark.parametrize(
    ("ctx", "message"),
    [
        (_GetCtx(enter_exc=asyncio.TimeoutError()), "Timed out while reading https://h/api/x"),
        (_GetCtx(enter_exc=ClientConnectionError("refused")), "REST request failed for https://h/api/x"),
        (
            _GetCtx(_Response(json_exc=json.JSONDecodeError("bad", "doc", 0))),
            "Unable to decode JSON from https://h/api/x",
        ),
    ],
)
async def test_fetch_json_maps_transport_errors(ctx, message):
    conn = HAConnection("https://h")
    with pytest.raises(HADiscoveryError, match=message) as info:
        await conn._fetch_json(_Session({"api/x": ctx}), "api/x")
    assert info.value.__cause__ is not None


# --------------------------------------------------------------------------- websocket


async def test_discover_websocket_without_token_refuses_before_connecting(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not connect without a token")

    monkeypatch.setattr(discovery.websockets, "connect", boom)
    with pytest.raises(HADiscoveryError, match="long-lived access token"):
        await HAConnection("https://h").discover_websocket()


async def test_discover_websocket_sends_token_and_get_config(monkeypatch):
    _fixed_uuid(monkeypatch)
    ws = _WebSocket([json.dumps({"type": "auth_required"}), json.dumps({"type": "auth_ok"}), _config_reply()])
    seen = _patch_ws(monkeypatch, ws)
    result = await HAConnection("https://h", token="tok").discover_websocket()
    assert result == WebsocketDiscoveryResult(websocket_url="wss://h/api/websocket", config={"location_name": "Home"})
    assert seen["url"] == "wss://h/api/websocket"
    assert seen["kwargs"] == {"ping_interval": None}
    assert ws.sent == [{"type": "auth", "access_token": "tok"}, {"id": "req1", "type": "get_config"}]


async def test_handshake_accepts_immediate_auth_ok_without_resending_token(monkeypatch):
    _fixed_uuid(monkeypatch)
    ws = _WebSocket([json.dumps({"type": "auth_ok"}), _config_reply()])
    _patch_ws(monkeypatch, ws)
    result = await HAConnection("https://h", token="tok").discover_websocket()
    assert result.config == {"location_name": "Home"}
    assert ws.sent == [{"id": "req1", "type": "get_config"}]


async def test_handshake_rejects_unexpected_first_message(monkeypatch):
    _patch_ws(monkeypatch, _WebSocket([json.dumps({"type": "hello"})]))
    with pytest.raises(HADiscoveryError, match="Unexpected websocket handshake response"):
        await HAConnection("https://h", token="tok").discover_websocket()


async def test_recv_json_decodes_bytes_frames(monkeypatch):
    _fixed_uuid(monkeypatch)
    ws = _WebSocket([json.dumps({"type": "auth_ok"}).encode(), _config_reply().encode()])
    _patch_ws(monkeypatch, ws)
    result = await HAConnection("https://h", token="tok").discover_websocket()
    assert result.config == {"location_name": "Home"}


async def test_recv_json_rejects_non_json(monkeypatch):
    _patch_ws(monkeypatch, _WebSocket(["not json"]))
    with pytest.raises(HADiscoveryError, match="Failed to decode websocket message"):
        await HAConnection("https://h", token="tok").discover_websocket()


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (_config_reply(request_id="other"), "response id mismatch"),
        (_config_reply(type="event"), "get_config failed"),
        (_config_reply(success=False), "get_config failed"),
        (_config_reply(result=["not", "a", "dict"]), "unexpected payload"),
    ],
)
async def test_get_config_reply_validation(monkeypatch, reply, message):
    _fixed_uuid(monkeypatch)
    _patch_ws(monkeypatch, _WebSocket([json.dumps({"type": "auth_ok"}), reply]))
    with pytest.raises(HADiscoveryError, match=message):
        await HAConnection("https://h", token="tok").discover_websocket()


@pytest.mark.parametrize(
    "exc",
    [OSError("unreachable"), InvalidHandshake("bad"), ClientConnectionError("x"), asyncio.TimeoutError()],
)
async def test_websocket_transport_errors_become_discovery_errors(monkeypatch, exc):
    _patch_ws(monkeypatch, _WebSocket([], recv_exc=exc))
    with pytest.raises(HADiscoveryError, match="WebSocket discovery failed") as info:
        await HAConnection("https://h", token="tok").discover_websocket()
    assert info.value.__cause__ is exc


async def test_recv_timeout_uses_configured_timeout(monkeypatch):
    class _Silent(_WebSocket):
        async def recv(self):
            await asyncio.sleep(10)

    _patch_ws(monkeypatch, _Silent([]))
    with pytest.raises(HADiscoveryError, match="WebSocket discovery failed") as info:
        await HAConnection("https://h", token="tok", timeout=0.01).discover_websocket()
    assert isinstance(info.value.__cause__, asyncio.TimeoutError)


# --------------------------------------------------------------------------- discover_all caching


def _counting_discovery(monkeypatch):
    calls = {"rest": 0, "ws": 0}

    # Each fake yields to the event loop so concurrent callers genuinely overlap.
    async def fake_rest(self):
        calls["rest"] += 1
        await asyncio.sleep(0)
        return RESTDiscoveryResult(base_url=self.rest_base_url, services=[], states=[{"n": calls["rest"]}])

    async def fake_ws(self):
        calls["ws"] += 1
        await asyncio.sleep(0)
        return WebsocketDiscoveryResult(websocket_url=self.websocket_url, config={"n": calls["ws"]})

    monkeypatch.setattr(HAConnection, "discover_rest", fake_rest)
    monkeypatch.setattr(HAConnection, "discover_websocket", fake_ws)
    return calls


async def test_discover_all_caches_until_forced(monkeypatch):
    calls = _counting_discovery(monkeypatch)
    conn = HAConnection("https://h", token="tok")

    first = await conn.discover_all()
    second = await conn.discover_all()
    assert second is first
    assert calls == {"rest": 1, "ws": 1}

    refreshed = await conn.discover_all(force_refresh=True)
    assert refreshed is not first
    assert refreshed.rest.states == [{"n": 2}]
    assert refreshed.websocket.config == {"n": 2}
    assert await conn.discover_all() is refreshed


async def test_discover_all_concurrent_callers_share_one_discovery(monkeypatch):
    calls = _counting_discovery(monkeypatch)
    conn = HAConnection("https://h", token="tok")
    results = await asyncio.gather(*(conn.discover_all() for _ in range(5)))
    assert calls == {"rest": 1, "ws": 1}
    assert all(r is results[0] for r in results)


async def test_discover_all_does_not_cache_failures(monkeypatch):
    calls = _counting_discovery(monkeypatch)
    conn = HAConnection("https://h", token="tok")

    async def failing_ws(self):
        raise HADiscoveryError("down")

    with monkeypatch.context() as m:
        m.setattr(HAConnection, "discover_websocket", failing_ws)
        with pytest.raises(HADiscoveryError):
            await conn.discover_all()

    result = await conn.discover_all()
    assert result.websocket.config == {"n": 1}
    assert calls["rest"] == 2

import asyncio
import json
import pytest

from unittest.mock import AsyncMock

from central_core_mqtt_shared.ha.discovery import HAConnection, HADiscoveryError


class _DummyResponse:
    def __init__(self, status=200, data=None):
        self.status = status
        self._data = data

    async def text(self):
        return json.dumps(self._data)

    async def json(self):
        return self._data


class _DummyGetCtx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummySession:
    def __init__(self, services, states):
        self._services = services
        self._states = states

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        if url.endswith("api/services"):
            return _DummyGetCtx(_DummyResponse(200, self._services))
        if url.endswith("api/states"):
            return _DummyGetCtx(_DummyResponse(200, self._states))
        return _DummyGetCtx(_DummyResponse(404, {"error": "not found"}))


class _DummyWebSocket:
    def __init__(self, incoming):
        # incoming: list of dict messages
        self._incoming = [json.dumps(m) for m in incoming]
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def recv(self):
        if not self._incoming:
            await asyncio.sleep(0)
            return json.dumps({})
        return self._incoming.pop(0)

    async def send(self, msg):
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_discover_rest(monkeypatch):
    services = [{"domain": "light", "services": {}}]
    states = [{"entity_id": "light.kitchen", "state": "on"}]

    # Provide a factory that returns a session object (not a coroutine)
    def fake_session_ctx(*args, **kwargs):
        return _DummySession(services, states)

    monkeypatch.setattr("aiohttp.ClientSession", fake_session_ctx)

    conn = HAConnection("https://example.com")
    result = await conn.discover_rest()
    assert result.services == services
    assert result.states == states


@pytest.mark.asyncio
async def test_discover_websocket_auth_and_config(monkeypatch):
    # Simulate websocket handshake: first auth_required, then auth_ok, then get_config result
    incoming = [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": "abc123", "type": "result", "success": True, "result": {"name": "HA"}},
    ]

    # monkeypatch websockets.connect to return our dummy websocket
    def fake_connect(url, **kwargs):
        # provide a websocket where the get_config response uses id 'abc123'
        return _DummyWebSocket(incoming.copy())

    monkeypatch.setattr("websockets.connect", fake_connect)

    # Provide a token so handshake proceeds
    conn = HAConnection("https://example.com", token="tok")
    # Monkeypatch uuid generation to return matching id used in incoming
    monkeypatch.setattr("uuid.uuid4", lambda: type("_u", (), {"hex": "abc123"})())

    result = await conn.discover_websocket()
    assert result.config.get("name") == "HA"


@pytest.mark.asyncio
async def test_discover_websocket_rejects_bad_token(monkeypatch):
    # Simulate websocket handshake rejecting auth
    incoming = [{"type": "auth_required"}, {"type": "auth_invalid"}]

    def fake_connect(url, **kwargs):
        return _DummyWebSocket(incoming.copy())

    monkeypatch.setattr("websockets.connect", fake_connect)

    conn = HAConnection("https://example.com", token="badtok")
    with pytest.raises(HADiscoveryError):
        await conn.discover_websocket()

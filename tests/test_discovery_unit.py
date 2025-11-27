import pytest

from central_core_mqtt_shared.ha.discovery import HAConnection, HADiscoveryError


def test_init_invalid_base_url():
    with pytest.raises(ValueError):
        HAConnection("not-a-url")


def test_normalize_and_rest_base_websocket_url_https():
    conn = HAConnection("https://example.com/")
    assert conn.rest_base_url == "https://example.com"
    assert conn.websocket_url.startswith("wss://")


def test_build_websocket_ws_scheme():
    conn = HAConnection("http://example.com")
    assert conn.websocket_url.startswith("ws://")


def test_build_rest_headers_with_token():
    conn = HAConnection("https://example.com", token="tok")
    headers = conn._build_rest_headers()
    assert headers["Authorization"] == "Bearer tok"


def test_make_url():
    conn = HAConnection("https://example.com")
    assert conn._make_url("/api/test") == "https://example.com/api/test"


def test_ensure_token_raises():
    conn = HAConnection("https://example.com")
    with pytest.raises(HADiscoveryError):
        conn._ensure_token()

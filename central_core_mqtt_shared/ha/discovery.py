from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp
import websockets
from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientError
from websockets import WebSocketException
from websockets.legacy.client import WebSocketClientProtocol


__all__ = [
    "HAConnection",
    "HADiscoveryError",
    "HADiscoveryResult",
    "RESTDiscoveryResult",
    "WebsocketDiscoveryResult",
    "discover_all_from_environment",
]


async def discover_all_from_environment(*, force_refresh: bool = False) -> HADiscoveryResult:
    """Discover REST + websocket metadata using environment credentials."""

    base_url = _require_env_var("HA_REST_URL")
    token = os.environ.get("HA_TOKEN")
    connection = HAConnection(base_url=base_url, token=token)
    return await connection.discover_all(force_refresh=force_refresh)


def _require_env_var(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HADiscoveryError(f"Environment variable {name} is required for discovery.")
    return value


async def _run_cli() -> None:
    result = await discover_all_from_environment()
    print(json.dumps({"rest": result.rest.__dict__, "websocket": result.websocket.__dict__}, indent=2))


if __name__ == "__main__":
    asyncio.run(_run_cli())


class HADiscoveryError(Exception):
    """Raised when Home Assistant discovery fails."""


@dataclass(frozen=True)
class RESTDiscoveryResult:
    """Data returned after fetching REST metadata."""

    base_url: str
    services: list[dict[str, Any]]
    states: list[dict[str, Any]]


@dataclass(frozen=True)
class WebsocketDiscoveryResult:
    """Data returned after validating the websocket API."""

    websocket_url: str
    config: dict[str, Any]


@dataclass(frozen=True)
class HADiscoveryResult:
    """Combined discovery payload covering REST and websocket data."""

    rest: RESTDiscoveryResult
    websocket: WebsocketDiscoveryResult


class HAConnection:
    """Async Home Assistant discovery helper."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        ws_path: str = "api/websocket",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = self._normalize_url(base_url)
        self._token = token
        self._ws_path = ws_path.lstrip("/") or "api/websocket"
        self._timeout = timeout
        self._ws_url = self._build_websocket_url()
        self._discovery_cache: HADiscoveryResult | None = None
        self._discovery_lock = asyncio.Lock()

    @property
    def rest_base_url(self) -> str:
        """Normalized REST base URL."""
        return self._base_url

    @property
    def websocket_url(self) -> str:
        """Fully authorized websocket URL."""
        return self._ws_url

    async def discover_rest(self) -> RESTDiscoveryResult:
        """Fetch services and states via the REST API."""
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        headers = self._build_rest_headers()
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            services = await self._fetch_json(session, "api/services")
            states = await self._fetch_json(session, "api/states")
        return RESTDiscoveryResult(base_url=self.rest_base_url, services=services, states=states)

    async def discover_websocket(self) -> WebsocketDiscoveryResult:
        """Validate websocket handshake and capture HA config."""
        self._ensure_token()
        try:
            async with websockets.connect(self.websocket_url, ping_interval=None) as websocket:
                await self._perform_handshake(websocket)
                config = await self._fetch_ws_config(websocket)
                return WebsocketDiscoveryResult(websocket_url=self.websocket_url, config=config)
        except (ClientError, WebSocketException, asyncio.TimeoutError, OSError) as exc:
            raise HADiscoveryError("WebSocket discovery failed") from exc

    async def discover_all(self, *, force_refresh: bool = False) -> HADiscoveryResult:
        """Run REST and websocket discovery in sequence, caching results for reuse."""
        async with self._discovery_lock:
            if self._discovery_cache and not force_refresh:
                return self._discovery_cache
            rest = await self.discover_rest()
            websocket = await self.discover_websocket()
            self._discovery_cache = HADiscoveryResult(rest=rest, websocket=websocket)
            return self._discovery_cache

    def _normalize_url(self, url: str) -> str:
        stripped = url.strip()
        if not stripped:
            raise ValueError("base_url must not be empty")
        parsed = urlparse(stripped)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("base_url must include a scheme and network location")
        return stripped.rstrip("/")

    def _build_websocket_url(self) -> str:
        normalized = urljoin(f"{self._base_url}/", self._ws_path)
        parsed = urlparse(normalized)
        scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
        return urlunparse(parsed._replace(scheme=scheme))

    def _build_rest_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _make_url(self, path: str) -> str:
        sanitized = path.lstrip("/")
        return urljoin(f"{self._base_url}/", sanitized)

    async def _fetch_json(self, session: ClientSession, path: str) -> list[dict[str, Any]]:
        url = self._make_url(path)
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    content = await response.text()
                    raise HADiscoveryError(
                        f"REST endpoint {url} returned {response.status}: {content}"
                    )
                return await response.json()
        except asyncio.TimeoutError as exc:
            raise HADiscoveryError(f"Timed out while reading {url}") from exc
        except ClientError as exc:
            raise HADiscoveryError(f"REST request failed for {url}") from exc
        except json.JSONDecodeError as exc:
            raise HADiscoveryError(f"Unable to decode JSON from {url}") from exc

    async def _perform_handshake(self, websocket: WebSocketClientProtocol) -> None:
        first = await self._recv_json(websocket)
        msg_type = first.get("type")
        if msg_type == "auth_required":
            token = self._ensure_token()
            await websocket.send(json.dumps({"type": "auth", "access_token": token}))
            auth_result = await self._recv_json(websocket)
            if auth_result.get("type") != "auth_ok":
                raise HADiscoveryError(
                    f"Home Assistant rejected the websocket token: {auth_result}"
                )
        elif msg_type != "auth_ok":
            raise HADiscoveryError(f"Unexpected websocket handshake response: {first}")

    async def _fetch_ws_config(self, websocket: WebSocketClientProtocol) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        await websocket.send(json.dumps({"id": request_id, "type": "get_config"}))
        response = await self._recv_json(websocket)
        if response.get("id") != request_id:
            raise HADiscoveryError("WebSocket get_config response id mismatch")
        if response.get("type") != "result" or not response.get("success"):
            raise HADiscoveryError(f"get_config failed: {response}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise HADiscoveryError("get_config returned unexpected payload")
        return result

    async def _recv_json(self, websocket: WebSocketClientProtocol) -> dict[str, Any]:
        raw = await asyncio.wait_for(websocket.recv(), timeout=self._timeout)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HADiscoveryError("Failed to decode websocket message") from exc

    def _ensure_token(self) -> str:
        if not self._token:
            raise HADiscoveryError("WebSocket discovery requires a long-lived access token")
        return self._token

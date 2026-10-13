"""Moving a hub onto its own broker login, protocol 1.5.

The vault sends a hub a new MQTT username and password without the password
ever crossing the broker in clear text. The flow (see docs/LOGIN_CHANGE.md):

1. Vault -> hub: ``login_key_request``. The hub makes a one-use X25519 key pair
   and answers with ``login_key``: its public key and a ``request_id``.
2. Vault -> hub: ``login_change``. The vault encrypts ``{username, password}``
   to that key (`encrypt_login_change`) and sends the request id, its own
   one-use public key, a nonce and the ciphertext.
3. The hub decrypts (`decrypt_login_change`), tests the login on a second
   connection, saves it only if the test passes, and reports
   ``login_change_result`` (never the password).

Crypto: X25519 key agreement, HKDF-SHA256, AES-256-GCM. The hub id and the
request id are the GCM associated data, so a message made for another hub or
another request does not decrypt. Both sides use `cryptography`.

Everything here is a plain function over bytes and strings: no MQTT, no I/O.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from typing import Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .topics import validate_hub_id

# ------------------------------------------------------------
# Parameters the vault and the hub must agree on
# ------------------------------------------------------------

ALGORITHM = "x25519-hkdf-sha256-aes256gcm"
"""Value of the `algorithm` field of `login_key`."""

LABEL = b"central-core/login-change/v1"
"""Domain separation: part of the HKDF info and of the associated data."""

KEY_TTL_SECONDS = 600
"""A hub's one-use key expires this long after it was made (about 10 minutes)."""

LOGIN_TEST_TIMEOUT_SECONDS = 30
"""The hub gives the second-connection test of the new login this long."""

ROLLBACK_WINDOW_SECONDS = 120
"""After switching, the hub goes back to the old login if its main connection
is not up within this long (about 2 minutes)."""

KEY_BYTES = 32  # X25519 public key
NONCE_BYTES = 12  # AES-GCM nonce
TAG_BYTES = 16  # AES-GCM tag

MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 1024
MAX_CIPHERTEXT_BYTES = 4096

REQUEST_ID_PATTERN = r"[A-Za-z0-9_-]{16,64}"
_REQUEST_ID_RE = re.compile(REQUEST_ID_PATTERN)


class LoginChangeCryptoError(ValueError):
    """A key, request id or message is malformed, or does not decrypt.

    The message never says which part failed to authenticate, and never
    contains the plaintext.
    """


# ------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------

def is_valid_request_id(request_id: object) -> bool:
    return isinstance(request_id, str) and _REQUEST_ID_RE.fullmatch(request_id) is not None


def new_request_id() -> str:
    """A fresh, unguessable request id (22 url-safe characters)."""
    return base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object, name: str, length: Optional[int] = None, max_length: Optional[int] = None) -> bytes:
    if not isinstance(value, str) or len(value) > 8192:
        raise LoginChangeCryptoError(f"{name} is not valid base64")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise LoginChangeCryptoError(f"{name} is not valid base64") from None
    if length is not None and len(raw) != length:
        raise LoginChangeCryptoError(f"{name} has the wrong length")
    if max_length is not None and len(raw) > max_length:
        raise LoginChangeCryptoError(f"{name} is too long")
    return raw


def associated_data(hub_id: str, request_id: str) -> bytes:
    """The GCM associated data: label, hub id and request id, NUL-separated.

    Neither the hub id nor the request id can contain a NUL, so the parts
    cannot be shifted into one another.
    """
    try:
        hub = validate_hub_id(hub_id)
    except (ValueError, TypeError):
        raise LoginChangeCryptoError("hub id is not valid") from None
    if not is_valid_request_id(request_id):
        raise LoginChangeCryptoError("request id is not valid")
    return LABEL + b"\x00" + hub.encode("ascii") + b"\x00" + request_id.encode("ascii")


def _public_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _load_public(value: object, name: str) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(_unb64(value, name, length=KEY_BYTES))


def _derive_key(shared: bytes, ephemeral_pub: bytes, hub_pub: bytes, aad: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=ephemeral_pub + hub_pub,
        info=LABEL + b"\x00" + aad,
    ).derive(shared)


def public_key_b64(private_key: X25519PrivateKey) -> str:
    """The base64 form of a hub private key's public half (the `login_key` field)."""
    return _b64(_public_bytes(private_key.public_key()))


def key_fingerprint(public_key: str) -> str:
    """A short, human-comparable fingerprint of a base64 public key.

    Five groups of four hex digits, for example ``a1b2-c3d4-e5f6-0718-293a``.
    The hub writes it to its log and puts it in `login_key`; the vault shows
    it, so the owner can check that the key belongs to the hub.
    """
    digest = hashlib.sha256(_unb64(public_key, "public key", length=KEY_BYTES)).hexdigest()[:20]
    return "-".join(digest[i:i + 4] for i in range(0, 20, 4))


def generate_hub_private_key() -> X25519PrivateKey:
    """The hub's one-use key pair. Keep it in memory only; use it once."""
    return X25519PrivateKey.generate()


# ------------------------------------------------------------
# Vault side
# ------------------------------------------------------------

def encrypt_login_change(
    hub_public_key: str,
    hub_id: str,
    request_id: str,
    username: str,
    password: str,
    *,
    ephemeral_private_key: Optional[X25519PrivateKey] = None,
    nonce: Optional[bytes] = None,
) -> dict:
    """Encrypt a login for one hub and one request.

    Returns the three message fields: ``ephemeral_public_key``, ``nonce`` and
    ``ciphertext`` (all base64). ``ephemeral_private_key`` and ``nonce`` are
    for test vectors only; leave them out in real use.
    """
    if not isinstance(username, str) or not 1 <= len(username) <= MAX_USERNAME_LENGTH:
        raise LoginChangeCryptoError("username must be 1 to %d characters" % MAX_USERNAME_LENGTH)
    if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_LENGTH:
        raise LoginChangeCryptoError("password must be 1 to %d characters" % MAX_PASSWORD_LENGTH)
    aad = associated_data(hub_id, request_id)
    hub_pub = _load_public(hub_public_key, "hub public key")
    ephemeral = ephemeral_private_key or X25519PrivateKey.generate()
    nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if len(nonce) != NONCE_BYTES:
        raise LoginChangeCryptoError("nonce has the wrong length")
    try:
        shared = ephemeral.exchange(hub_pub)
    except ValueError:
        raise LoginChangeCryptoError("hub public key is not usable") from None
    ephemeral_pub = _public_bytes(ephemeral.public_key())
    key = _derive_key(shared, ephemeral_pub, _public_bytes(hub_pub), aad)
    plaintext = json.dumps({"username": username, "password": password}, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {
        "ephemeral_public_key": _b64(ephemeral_pub),
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


# ------------------------------------------------------------
# Hub side
# ------------------------------------------------------------

def decrypt_login_change(
    hub_private_key: X25519PrivateKey,
    hub_id: str,
    request_id: str,
    ephemeral_public_key: str,
    nonce: str,
    ciphertext: str,
) -> Tuple[str, str]:
    """Decrypt a login change; returns ``(username, password)``.

    Raises `LoginChangeCryptoError` for anything wrong: malformed fields, a
    different hub id or request id than the one it was made for, a changed
    byte, or a plaintext that is not a username and password.
    """
    aad = associated_data(hub_id, request_id)
    ephemeral_pub = _unb64(ephemeral_public_key, "ephemeral public key", length=KEY_BYTES)
    nonce_raw = _unb64(nonce, "nonce", length=NONCE_BYTES)
    data = _unb64(ciphertext, "ciphertext", max_length=MAX_CIPHERTEXT_BYTES)
    if len(data) <= TAG_BYTES:
        raise LoginChangeCryptoError("ciphertext is too short")
    try:
        shared = hub_private_key.exchange(X25519PublicKey.from_public_bytes(ephemeral_pub))
    except ValueError:
        raise LoginChangeCryptoError("could not decrypt") from None
    hub_pub = _public_bytes(hub_private_key.public_key())
    key = _derive_key(shared, ephemeral_pub, hub_pub, aad)
    try:
        plaintext = AESGCM(key).decrypt(nonce_raw, data, aad)
    except InvalidTag:
        raise LoginChangeCryptoError("could not decrypt") from None
    try:
        obj = json.loads(plaintext.decode("utf-8"))
        username, password = obj["username"], obj["password"]
        keys = set(obj)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise LoginChangeCryptoError("decrypted message is not a login") from None
    if (
        keys != {"username", "password"}
        or not isinstance(username, str)
        or not isinstance(password, str)
        or not 1 <= len(username) <= MAX_USERNAME_LENGTH
        or not 1 <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        raise LoginChangeCryptoError("decrypted message is not a login")
    return username, password


__all__ = [
    "ALGORITHM",
    "KEY_TTL_SECONDS",
    "LOGIN_TEST_TIMEOUT_SECONDS",
    "ROLLBACK_WINDOW_SECONDS",
    "REQUEST_ID_PATTERN",
    "LoginChangeCryptoError",
    "associated_data",
    "decrypt_login_change",
    "encrypt_login_change",
    "generate_hub_private_key",
    "is_valid_request_id",
    "key_fingerprint",
    "new_request_id",
    "public_key_b64",
]

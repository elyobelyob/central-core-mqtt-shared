# Moving a hub onto its own broker login (protocol 1.5)

All messages are new and optional. A hub older than the add-on release that supports this (2.4.5) ignores `cmd/login/*` without answering, so the vault learns that only by timeout; a vault that parses every message on an ack topic as `CommandAck` must route by topic first.

## Messages

| Step | Direction | Topic | Payload |
|---|---|---|---|
| 1 | vault to hub | `hubs/<hub>/v1/cmd/login/key_request` | `command_id`, `timestamp` (the usual command fields) |
| 2 | hub to vault | `hubs/<hub>/v1/ack/login.key_request/<command_id>` (`LOGIN_KEY`) | `LoginKey`: `command_id`, `request_id`, `algorithm`, `public_key` (base64, 32 bytes), `fingerprint`, `expires_at`, `timestamp` |
| 3 | vault to hub | `hubs/<hub>/v1/cmd/login/change` | `LoginChangeCommand`: `command_id`, `timestamp` (usual command fields), `request_id`, `ephemeral_public_key`, `nonce`, `ciphertext` (all base64) |
| 4 | hub to vault | `hubs/<hub>/v1/ack/login.change/<command_id>` (`LOGIN_CHANGE_RESULT`) | `LoginChangeResult`: `command_id`, `request_id`, `status` (`ok` or `failed`), `reason`, `username`, `confirmation`, `timestamp` |

The `command_id` in steps 2 and 4 is the id of the command being answered. Commands follow the usual rules (fresh `command_id`, `timestamp` not older than 10 minutes, never retained). The result is never retained and carries the username, never the password.

The hub's ordinary acknowledgement topic also carries the hub's generic replies, which do not have the shapes above: `{"status": "failed", "result": {"reason": "stale_command" | "bad_timestamp"}}` when the command was too old or had no readable time. The vault treats those as the command having failed. The hub sends no "acknowledged" for these two commands.

## Crypto (`central_core_mqtt_shared.login_change`)

- Hub: one-use X25519 key pair in memory. Vault: one-use X25519 key pair per message.
- Shared secret: X25519. Keys: one HKDF-SHA256 run of 64 bytes; the first 32 are the AES key, the last 32 the confirmation key, `salt = ephemeral_pub || hub_pub` (raw 32-byte keys), `info = LABEL || 0x00 || AAD`.
- Cipher: AES-256-GCM, 12-byte random `nonce`, plaintext `{"username": ..., "password": ...}` as compact UTF-8 JSON (not ASCII-escaped), tag appended to the ciphertext. The username matches `USERNAME_PATTERN` (letters, digits and `. _ @ : -`, at most 256); the password is 1 to 512 printable characters.
- `confirmation` (in the result): base64 HMAC-SHA256, keyed with the confirmation key, over `LABEL || 0x00 || "result" || 0x00 || AAD || 0x00 || status || 0x00 || reason || 0x00 || username` (empty string when absent). Both sides get the key from the same exchange, so only the real hub (and the vault) can make it. `encrypt_login_change` returns it to the vault; `decrypt_login_change` returns it to the hub; `result_confirmation` and `verify_result_confirmation` make and check it.
- `LABEL = b"central-core/login-change/v1"`. `AAD = LABEL || 0x00 || hub_id || 0x00 || request_id`, so a message for another hub or request does not decrypt.
- `request_id`: 16 to 64 characters of `A-Za-z0-9_-`, made by the hub.
- `fingerprint`: first 20 hex digits of SHA-256 of the raw hub key, in groups of four. The hub logs it too.
- Use `encrypt_login_change` (vault) and `decrypt_login_change` (hub). `tests/test_login_change.py` holds a fixed test vector, checked against a second write-up of the steps above that does not call the module, plus the RFC 7748 X25519 vector. The hub id is case-sensitive: the vault must use the hub id exactly as the hub reports it.

## Timing (constants in the module)

- The hub's key expires after `KEY_TTL_SECONDS` (600).
- The hub tests the new login on a second connection for up to `LOGIN_TEST_TIMEOUT_SECONDS` (30).
- After switching, the hub goes back to the old login if its main connection is not up within `ROLLBACK_WINDOW_SECONDS` (120).

## Result reasons (`LoginChangeReason`)

Failure reasons: `bad_request`, `unknown_request`, `expired`, `used`, `bad_ciphertext`, `bad_login`, `busy`, `connect_failed`, `access_failed`, `save_failed`, `rolled_back`. `ok` may carry `unchanged` (the hub already used that login). In every failure except `rolled_back` nothing was saved and the hub is still on its old login; `rolled_back` means the new login was tried and the old one restored.

## Trust

Messages carry no signature, so the vault cannot tell that a `login_key` really came from the hub: whoever can publish on the hub's topics can answer first, and the password would be encrypted to them. The vault must therefore, before it encrypts anything:

1. work out `key_fingerprint(public_key)` itself (not use the received `fingerprint` field);
2. show it to the owner and get it confirmed against the fingerprint the hub writes to its own log;
3. give up if two different keys arrive for the same `command_id`, and check `algorithm` equals `ALGORITHM` and the key has not expired by its own clock.

After sending, the vault treats an `ok` result as real, and removes any old login, only if `verify_result_confirmation` accepts it. A forged `ok` has no valid `confirmation`.

A long-term hub identity key, pinned in the vault, would remove the manual step. It is not in this version.

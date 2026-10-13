# Moving a hub onto its own broker login (protocol 1.5)

All fields and messages are new and optional: hubs and vaults that do not know them ignore them.

## Messages

| Step | Direction | Topic | Payload |
|---|---|---|---|
| 1 | vault to hub | `hubs/<hub>/v1/cmd/login/key_request` | `command_id`, `timestamp` |
| 2 | hub to vault | `hubs/<hub>/v1/ack/login.key_request/<command_id>` (`LOGIN_KEY`) | `LoginKey`: `command_id`, `request_id`, `algorithm`, `public_key` (base64, 32 bytes), `fingerprint`, `expires_at`, `timestamp` |
| 3 | vault to hub | `hubs/<hub>/v1/cmd/login/change` | `LoginChangeCommand`: `command_id`, `timestamp`, `request_id`, `ephemeral_public_key`, `nonce`, `ciphertext` (all base64) |
| 4 | hub to vault | `hubs/<hub>/v1/ack/login.change/<command_id>` (`LOGIN_CHANGE_RESULT`) | `LoginChangeResult`: `command_id`, `request_id`, `status` (`ok` or `failed`), `reason`, `username`, `timestamp` |

The `command_id` in steps 2 and 4 is the id of the command being answered. Commands follow the usual rules (fresh `command_id`, `timestamp` not older than 10 minutes, never retained). The result is never retained and carries the username, never the password.

## Crypto (`central_core_mqtt_shared.login_change`)

- Hub: one-use X25519 key pair in memory. Vault: one-use X25519 key pair per message.
- Shared secret: X25519. Key: HKDF-SHA256, 32 bytes, `salt = ephemeral_pub || hub_pub` (raw 32-byte keys), `info = LABEL || 0x00 || AAD`.
- Cipher: AES-256-GCM, 12-byte random `nonce`, plaintext `{"username": ..., "password": ...}` as compact JSON, tag appended to the ciphertext.
- `LABEL = b"central-core/login-change/v1"`. `AAD = LABEL || 0x00 || hub_id || 0x00 || request_id`, so a message for another hub or request does not decrypt.
- `request_id`: 16 to 64 characters of `A-Za-z0-9_-`, made by the hub.
- `fingerprint`: first 20 hex digits of SHA-256 of the raw hub key, in groups of four. The hub logs it too.
- Use `encrypt_login_change` (vault) and `decrypt_login_change` (hub); `tests/test_login_change.py` holds a fixed test vector checked against an independent write-up of the steps above.

## Timing (constants in the module)

- The hub's key expires after `KEY_TTL_SECONDS` (600).
- The hub tests the new login on a second connection for up to `LOGIN_TEST_TIMEOUT_SECONDS` (30).
- After switching, the hub goes back to the old login if its main connection is not up within `ROLLBACK_WINDOW_SECONDS` (120).

## Result reasons (`LoginChangeReason`)

Failure reasons: `bad_request`, `unknown_request`, `expired`, `used`, `bad_ciphertext`, `bad_login`, `busy`, `connect_failed`, `access_failed`, `save_failed`, `rolled_back`. `ok` may carry `unchanged` (the hub already used that login). In every failure except `rolled_back` nothing was saved and the hub is still on its old login; `rolled_back` means the new login was tried and the old one restored.

## Trust

The vault cannot tell that a `login_key` really came from the hub: whoever can publish on the hub's topics can answer first. Compare the fingerprint with the one in the hub's log before sending the password, and send only while the shared login can still be trusted.

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

Failure reasons: `bad_request`, `unknown_request`, `expired`, `used`, `bad_ciphertext`, `bad_login`, `tls_required`, `busy`, `connect_failed`, `access_failed`, `save_failed`, `rolled_back`. `ok` may carry `unchanged` (the hub already used that login). In every failure except `rolled_back` nothing was saved and the hub is still on its old login; `rolled_back` means the new login was tried and the old one restored.

## Rules for the vault

The hub cannot tell the vault from anyone else who can publish on its topics, and the vault cannot tell the hub's messages from forgeries, so each side keeps a few rules.

Before it encrypts anything:

1. Work out `key_fingerprint(public_key)` itself (not use the received `fingerprint` field).
2. Show it to the owner and get it confirmed against the fingerprint the hub writes to its own log.
3. Give up if two different keys arrive for the same `command_id`; check `algorithm` equals `ALGORITHM` and the key has not expired by the vault's own clock.
4. Use only a username the hub accepts: `hub-<hub id>`, `hub-<hub id>-a` or `hub-<hub id>-b`. The hub refuses anything else with `bad_login`, so a forged message cannot move it back to the shared login.

After sending:

5. Wait for the result for as long as the hub's budget: up to about 30 s for the login test, 120 s for the main connection, then up to two more 120 s windows if it has to go back, so give it 10 minutes.
6. Act on `ok` (for example by retiring the old login) only if `verify_result_confirmation` accepts it AND `username` is the username the vault sent. A result without a valid `confirmation` is advice only: never delete or change a login because of a failure, a timeout or a missing result, because the hub may already be using the new login.
7. Before retiring the old login, send the hub a command (for example another `login/key_request`) and see it answered on the new login. The hub's login test proves it can connect, subscribe and publish, but a broker can grant a subscription without delivering to it.

The hub refuses a move (`tls_required`) when its MQTT connection is not encrypted, because the login would cross the network in the clear.

## Trust

Messages carry no signature. Whoever can publish on the hub's topics can answer a key request first and receive the password (rule 1 to 3 are the defence), can send the hub a well-formed `login_change` (limited by rule 4 and by the hub only using up its key once a login has passed the test), and can publish a failure that looks like the hub's (rule 6). A long-term identity key for the hub, and a signing key for the vault pinned in the hub, would remove these manual steps. They are not in this version.

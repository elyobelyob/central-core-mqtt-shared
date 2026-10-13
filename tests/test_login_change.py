import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError

from central_core_mqtt_shared import login_change as lc
from central_core_mqtt_shared.schemas import (
    CommandName,
    LoginChangeCommand,
    LoginChangeReason,
    LoginChangeResult,
    LoginKey,
    LoginKeyRequestCommand,
)
from central_core_mqtt_shared.topics import (
    CMD_LOGIN_CHANGE,
    CMD_LOGIN_KEY_REQUEST,
    LOGIN_CHANGE_RESULT,
    LOGIN_KEY,
    build_topic,
)

HUB = "demo-home-001"
REQ = "req_0123456789abcdef"
USER = "hub-demo-home-001"
PW = "correct horse battery staple"  # made-up test value

# Fixed inputs for the published test vector (made-up keys, never used anywhere).
HUB_SECRET = bytes(range(1, 33))
VAULT_SECRET = bytes(range(101, 133))
NONCE = bytes(range(12))

# The vector: what encrypt_login_change must produce for the fixed inputs above.
VECTOR = {
    "hub_public_key": "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw=",
    "ephemeral_public_key": "VxR2nRFr92Q2rnS8eT0sMK0ZA8WaxSc4BcfiaYtBDDY=",
    "nonce": "AAECAwQFBgcICQoL",
}


def _priv(raw):
    return X25519PrivateKey.from_private_bytes(raw)


def _raw_pub(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _reference_encrypt(hub_secret, vault_secret, nonce, hub_id, request_id, user, pw):
    """The spec written out again, independently of the module under test."""
    hub_pub = _raw_pub(_priv(hub_secret))
    eph = _priv(vault_secret)
    eph_pub = _raw_pub(eph)
    shared = eph.exchange(_priv(hub_secret).public_key())
    label = b"central-core/login-change/v1"
    aad = label + b"\x00" + hub_id.encode() + b"\x00" + request_id.encode()
    okm = HKDF(hashes.SHA256(), 64, salt=eph_pub + hub_pub, info=label + b"\x00" + aad).derive(shared)
    pt = json.dumps({"username": user, "password": pw}, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.b64encode(AESGCM(okm[:32]).encrypt(nonce, pt, aad)).decode(), okm[32:]


def _make(hub_key=None, hub_id=HUB, request_id=REQ):
    hub_key = hub_key or lc.generate_hub_private_key()
    msg, _ = lc.encrypt_login_change(lc.public_key_b64(hub_key), hub_id, request_id, USER, PW)
    return hub_key, msg


class TestVector:
    def test_matches_independent_reference(self):
        out, confirm_key = lc.encrypt_login_change(
            lc.public_key_b64(_priv(HUB_SECRET)), HUB, REQ, USER, PW,
            ephemeral_private_key=_priv(VAULT_SECRET), nonce=NONCE,
        )
        ref_ct, ref_confirm = _reference_encrypt(HUB_SECRET, VAULT_SECRET, NONCE, HUB, REQ, USER, PW)
        assert confirm_key == ref_confirm
        assert confirm_key.hex() == VECTOR_CONFIRM_KEY
        assert out["nonce"] == VECTOR["nonce"]
        assert out["ephemeral_public_key"] == VECTOR["ephemeral_public_key"]
        assert lc.public_key_b64(_priv(HUB_SECRET)) == VECTOR["hub_public_key"]
        assert out["ciphertext"] == ref_ct
        assert out["ciphertext"] == VECTOR_CIPHERTEXT

    def test_vector_decrypts(self):
        got = lc.decrypt_login_change(
            _priv(HUB_SECRET), HUB, REQ, VECTOR["ephemeral_public_key"], VECTOR["nonce"], VECTOR_CIPHERTEXT
        )
        assert (got.username, got.password) == (USER, PW)


VECTOR_CONFIRM_KEY = "7eb6ffba290c4310862c768ee273b1b1793cf5b38724e19a206955f8cc526364"
VECTOR_CIPHERTEXT = (
    "igTVMhyG0u4cJq530O5DCG12S5mti/xZeLaqdUnelyrr46LdNX9JCErxtfhc8oi9"
    "LT4oMk/6Tkno1ybXRbxGj0PD8Dl+8Ivm19GU6nb0jJAN+anXgI6jC8fv"
)


class TestRoundTrip:
    def test_round_trip(self):
        key, msg = _make()
        got = lc.decrypt_login_change(key, HUB, REQ, **msg)
        assert (got.username, got.password) == (USER, PW)

    def test_fresh_nonce_and_ephemeral_key_each_time(self):
        key = lc.generate_hub_private_key()
        a, ka = lc.encrypt_login_change(lc.public_key_b64(key), HUB, REQ, USER, PW)
        b, kb = lc.encrypt_login_change(lc.public_key_b64(key), HUB, REQ, USER, PW)
        assert ka != kb
        assert a["nonce"] != b["nonce"]
        assert a["ephemeral_public_key"] != b["ephemeral_public_key"]
        assert a["ciphertext"] != b["ciphertext"]

    def test_non_ascii_password(self):
        key = lc.generate_hub_private_key()
        msg, _ = lc.encrypt_login_change(lc.public_key_b64(key), HUB, REQ, USER, "p\u00e4ss\u2603")
        assert lc.decrypt_login_change(key, HUB, REQ, **msg).password == "p\u00e4ss\u2603"

    def test_longest_password_of_four_byte_characters_fits(self):
        key = lc.generate_hub_private_key()
        pw = "\U0001F600" * lc.MAX_PASSWORD_LENGTH
        msg, _ = lc.encrypt_login_change(lc.public_key_b64(key), HUB, REQ, "u" * lc.MAX_USERNAME_LENGTH, pw)
        assert lc.decrypt_login_change(key, HUB, REQ, **msg).password == pw
        LoginChangeCommand(command_id="c", request_id=REQ, **msg)

    def test_repr_hides_secrets(self):
        key, msg = _make()
        got = lc.decrypt_login_change(key, HUB, REQ, **msg)
        assert PW not in repr(got) and USER in repr(got) and "confirm_key" not in repr(got)

    def test_plaintext_is_not_in_the_message(self):
        _, msg = _make()
        assert PW not in json.dumps(msg)
        assert PW.encode() not in base64.b64decode(msg["ciphertext"])


class TestRefusals:
    def test_wrong_hub_id(self):
        key, msg = _make()
        with pytest.raises(lc.LoginChangeCryptoError, match="could not decrypt"):
            lc.decrypt_login_change(key, "demo-home-002", REQ, **msg)

    def test_wrong_request_id(self):
        key, msg = _make()
        with pytest.raises(lc.LoginChangeCryptoError, match="could not decrypt"):
            lc.decrypt_login_change(key, HUB, "req_other_0123456789", **msg)

    def test_wrong_hub_key(self):
        _, msg = _make()
        with pytest.raises(lc.LoginChangeCryptoError):
            lc.decrypt_login_change(lc.generate_hub_private_key(), HUB, REQ, **msg)

    @pytest.mark.parametrize("field", ["ephemeral_public_key", "nonce", "ciphertext"])
    def test_changed_byte(self, field):
        key, msg = _make()
        raw = bytearray(base64.b64decode(msg[field]))
        raw[0] ^= 1
        msg[field] = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(lc.LoginChangeCryptoError):
            lc.decrypt_login_change(key, HUB, REQ, **msg)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("ephemeral_public_key", "not base64!"),
            ("ephemeral_public_key", base64.b64encode(b"short").decode()),
            ("ephemeral_public_key", None),
            ("ephemeral_public_key", "A" * 9000),
            ("nonce", base64.b64encode(b"x" * 11).decode()),
            ("ciphertext", base64.b64encode(b"x" * 16).decode()),
            ("ciphertext", base64.b64encode(b"x" * 5000).decode()),
            ("ciphertext", "***"),
        ],
    )
    def test_malformed_fields(self, field, value):
        key, msg = _make()
        msg[field] = value
        with pytest.raises(lc.LoginChangeCryptoError):
            lc.decrypt_login_change(key, HUB, REQ, **msg)

    def test_low_order_ephemeral_key(self):
        key, msg = _make()
        msg["ephemeral_public_key"] = base64.b64encode(bytes(32)).decode()
        with pytest.raises(lc.LoginChangeCryptoError, match="could not decrypt"):
            lc.decrypt_login_change(key, HUB, REQ, **msg)

    @pytest.mark.parametrize("hub_id", ["", "bad/hub", "broadcast", "+", None, 5])
    def test_bad_hub_id(self, hub_id):
        key, msg = _make()
        with pytest.raises(lc.LoginChangeCryptoError, match="hub id"):
            lc.decrypt_login_change(key, hub_id, REQ, **msg)

    @pytest.mark.parametrize("request_id", ["", "short", "has space 0123456789", "x" * 65, None, "a/b" * 8])
    def test_bad_request_id(self, request_id):
        key, msg = _make()
        with pytest.raises(lc.LoginChangeCryptoError, match="request id"):
            lc.decrypt_login_change(key, HUB, request_id, **msg)

    @pytest.mark.parametrize(
        "plaintext",
        [
            b"not json",
            b"\xff\xfe",
            b"[]",
            b'{"username":"a"}',
            b'{"username":"a","password":"b","extra":1}',
            b'{"username":1,"password":"b"}',
            b'{"username":"","password":"b"}',
            b'{"username":"a","password":""}',
            b'{"username":"%s","password":"b"}' % (b"u" * 257),
            b'{"username":"evil\\nINFO fake","password":"b"}',
            b'{"username":"a b","password":"b"}',
            b'{"username":"a","password":"bad\\npass"}',
            b'{"username":"a","password":"nul\\u0000"}',
        ],
    )
    def test_authentic_but_not_a_login(self, plaintext):
        key = lc.generate_hub_private_key()
        hub_pub = _raw_pub(key)
        eph = X25519PrivateKey.generate()
        eph_pub = _raw_pub(eph)
        aad = lc.associated_data(HUB, REQ)
        k = HKDF(hashes.SHA256(), 32, salt=eph_pub + hub_pub, info=lc.LABEL + b"\x00" + aad).derive(
            eph.exchange(key.public_key())
        )
        nonce = bytes(12)
        ct = AESGCM(k).encrypt(nonce, plaintext, aad)
        with pytest.raises(lc.LoginChangeCryptoError, match="not a login"):
            lc.decrypt_login_change(
                key, HUB, REQ,
                base64.b64encode(eph_pub).decode(), base64.b64encode(nonce).decode(), base64.b64encode(ct).decode(),
            )

    def test_error_text_never_holds_the_password(self):
        key, msg = _make()
        try:
            lc.decrypt_login_change(key, "demo-home-002", REQ, **msg)
        except lc.LoginChangeCryptoError as exc:
            assert PW not in str(exc) and USER not in str(exc)


class TestEncryptChecks:
    def test_bad_inputs(self):
        pub = lc.public_key_b64(lc.generate_hub_private_key())
        for bad_user in ("", "evil\nline", "has space", "-leading", "u" * 257, None):
            with pytest.raises(lc.LoginChangeCryptoError, match="username"):
                lc.encrypt_login_change(pub, HUB, REQ, bad_user, PW)
        for bad_pw in ("", "p" * 513, "new\nline", "nul\x00", None):
            with pytest.raises(lc.LoginChangeCryptoError, match="password"):
                lc.encrypt_login_change(pub, HUB, REQ, USER, bad_pw)
        with pytest.raises(lc.LoginChangeCryptoError, match="public key"):
            lc.encrypt_login_change("bogus", HUB, REQ, USER, PW)
        with pytest.raises(lc.LoginChangeCryptoError, match="nonce"):
            lc.encrypt_login_change(pub, HUB, REQ, USER, PW, nonce=b"short")

    def test_low_order_hub_key(self):
        zero = base64.b64encode(bytes(32)).decode()
        with pytest.raises(lc.LoginChangeCryptoError, match="not usable"):
            lc.encrypt_login_change(zero, HUB, REQ, USER, PW)


class TestConfirmation:
    def _pair(self):
        key = lc.generate_hub_private_key()
        msg, vault_key = lc.encrypt_login_change(lc.public_key_b64(key), HUB, REQ, USER, PW)
        hub_key = lc.decrypt_login_change(key, HUB, REQ, **msg).confirm_key
        return vault_key, hub_key

    def test_both_sides_derive_the_same_key(self):
        vault_key, hub_key = self._pair()
        assert vault_key == hub_key and len(vault_key) == 32

    def test_verifies_exactly_what_was_signed(self):
        vault_key, hub_key = self._pair()
        c = lc.result_confirmation(hub_key, HUB, REQ, "ok", None, USER)
        assert lc.verify_result_confirmation(vault_key, HUB, REQ, "ok", None, USER, c)
        assert lc.verify_result_confirmation(
            vault_key, HUB, REQ, "failed", "rolled_back", USER,
            lc.result_confirmation(hub_key, HUB, REQ, "failed", "rolled_back", USER),
        )

    @pytest.mark.parametrize(
        "args",
        [
            (HUB, REQ, "failed", None, USER),
            (HUB, REQ, "ok", "unchanged", USER),
            (HUB, REQ, "ok", None, "hub-other"),
            (HUB, REQ, "ok", None, None),
            ("demo-home-002", REQ, "ok", None, USER),
            (HUB, "req_other_0123456789", "ok", None, USER),
        ],
    )
    def test_any_changed_value_fails(self, args):
        vault_key, hub_key = self._pair()
        c = lc.result_confirmation(hub_key, HUB, REQ, "ok", None, USER)
        assert not lc.verify_result_confirmation(vault_key, *args, c)

    def test_forgeries_fail(self):
        vault_key, _ = self._pair()
        forged = lc.result_confirmation(bytes(32), HUB, REQ, "ok", None, USER)
        assert not lc.verify_result_confirmation(vault_key, HUB, REQ, "ok", None, USER, forged)
        for junk in (None, "", 5, "\u00e9\u00e9"):
            assert not lc.verify_result_confirmation(vault_key, HUB, REQ, "ok", None, USER, junk)


class TestX25519Anchor:
    def test_rfc7748_section_6_1(self):
        # Test vector from RFC 7748, section 6.1: anchors the primitive the helpers rely on.
        alice = X25519PrivateKey.from_private_bytes(
            bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
        )
        bob_pub = X25519PrivateKey.from_private_bytes(
            bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
        ).public_key()
        assert alice.exchange(bob_pub).hex() == "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"


class TestHelpers:
    def test_request_ids_are_valid_and_unique(self):
        a, b = lc.new_request_id(), lc.new_request_id()
        assert a != b and lc.is_valid_request_id(a) and len(a) == 22

    def test_fingerprint(self):
        fp = lc.key_fingerprint(VECTOR["hub_public_key"])
        assert fp.count("-") == 4 and all(len(g) == 4 for g in fp.split("-"))
        assert fp == lc.key_fingerprint(VECTOR["hub_public_key"])
        assert fp != lc.key_fingerprint(VECTOR["ephemeral_public_key"])
        with pytest.raises(lc.LoginChangeCryptoError):
            lc.key_fingerprint("nope")

    def test_timing_constants(self):
        assert (lc.KEY_TTL_SECONDS, lc.ROLLBACK_WINDOW_SECONDS) == (600, 120)
        assert lc.LOGIN_TEST_TIMEOUT_SECONDS > 0


class TestTopicsAndSchemas:
    def test_topics(self):
        kw = dict(hub_id=HUB, version=1)
        assert build_topic(CMD_LOGIN_KEY_REQUEST, **kw) == f"hubs/{HUB}/v1/cmd/login/key_request"
        assert build_topic(CMD_LOGIN_CHANGE, **kw) == f"hubs/{HUB}/v1/cmd/login/change"
        assert build_topic(LOGIN_KEY, command_id="c1", **kw) == f"hubs/{HUB}/v1/ack/login.key_request/c1"
        assert build_topic(LOGIN_CHANGE_RESULT, command_id="c2", **kw) == f"hubs/{HUB}/v1/ack/login.change/c2"

    def test_command_names(self):
        assert CommandName.LOGIN_KEY_REQUEST.value == "login.key_request"
        assert CommandName.LOGIN_CHANGE.value == "login.change"

    def test_key_request_needs_only_an_id(self):
        assert LoginKeyRequestCommand(command_id="c").command_id == "c"

    def test_login_key(self):
        key = LoginKey(
            command_id="c", request_id=REQ, public_key=VECTOR["hub_public_key"],
            expires_at="2026-10-13T10:10:00+00:00", timestamp="2026-10-13T10:00:00Z",
        )
        assert key.algorithm == lc.ALGORITHM and key.expires_at == "2026-10-13T10:10:00Z"
        with pytest.raises(ValidationError):
            LoginKey(command_id="c", request_id="short", public_key="k", expires_at="x", timestamp="y")

    def test_login_change_command(self):
        _, msg = _make()
        assert LoginChangeCommand(command_id="c", request_id=REQ, **msg).request_id == REQ
        with pytest.raises(ValidationError):
            LoginChangeCommand(command_id="c", request_id="bad id", **msg)
        with pytest.raises(ValidationError):
            LoginChangeCommand(command_id="c", request_id=REQ, **{**msg, "ciphertext": "A" * 8193})
        with pytest.raises(ValidationError):
            LoginChangeCommand(command_id="c", request_id=REQ)

    def test_result_has_no_password_field(self):
        assert not [f for f in LoginChangeResult.model_fields if "pass" in f or "secret" in f]
        ok = LoginChangeResult(command_id="c", status="ok", username=USER, timestamp="2026-10-13T10:00:00Z")
        assert ok.reason is None
        failed = LoginChangeResult(
            command_id="c", request_id=REQ, status="failed", reason="rolled_back", username=USER,
            timestamp="2026-10-13T10:00:00Z",
        )
        assert failed.reason is LoginChangeReason.ROLLED_BACK
        with pytest.raises(ValidationError):
            LoginChangeResult(command_id="c", status="maybe", timestamp="2026-10-13T10:00:00Z")

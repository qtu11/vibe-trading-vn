import base64
import hashlib
import json
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
from src.trading.forex.adapters.exness_auth import sign, private_key
from src.trading.forex.errors import ForexError


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@pytest.mark.parametrize("method,key,body", [("GET", "", b""), ("POST", "request-123", '{"comment":"mẫu"}'.encode())])
def test_exact_bytes(method, key, body):
    secret = Ed25519PrivateKey.generate()
    req = httpx.Request(method, "https://ap.example/x?a=1%2F2", content=body)
    headers = sign(req, "public", secret, key)
    payload = decode(headers["EXN-DATA"])
    secret.public_key().verify(decode(headers["EXN-SIGN"]), payload)
    data = json.loads(payload)
    assert data["path"] == "/x?a=1%2F2"
    assert decode(data["body_hash"]) == hashlib.sha256(body).digest()
    assert headers["EXN-IDEMPOTENCY-KEY"] == key
    with pytest.raises(ForexError):
        sign(httpx.Request("POST", "https://ap.example/x"), "public", secret)


def test_key_formats_and_mismatched_public_key():
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert private_key((seed + pub).hex()).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) == pub
    assert private_key(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode())
    with pytest.raises(ForexError):
        private_key((seed + bytes(32)).hex())

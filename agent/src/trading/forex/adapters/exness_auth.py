"""Exact-byte Exness signing, including the documented 64-byte hex key format."""

import base64
import hashlib
import json
import re
import time

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ..errors import ForexError


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def private_key(value: str) -> Ed25519PrivateKey:
    try:
        if value.lstrip().startswith("-----BEGIN"):
            result = serialization.load_pem_private_key(value.encode(), password=None)
            if not isinstance(result, Ed25519PrivateKey):
                raise ValueError("Wrong key type")
            return result
        if not re.fullmatch(r"[A-Fa-f0-9]{128}", value):
            raise ValueError("Expected PKCS8 PEM or Exness 64-byte hex private key")
        raw = bytes.fromhex(value)
        result = Ed25519PrivateKey.from_private_bytes(raw[:32])
        if result.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw) != raw[32:]:
            raise ValueError("Ed25519 public key does not match seed")
        return result
    except (ValueError, TypeError) as exc:
        raise ForexError("INVALID_SIGNING_KEY", "Invalid Exness Ed25519 signing key format") from exc


def sign(request: httpx.Request, api_key: str, key: Ed25519PrivateKey, request_key: str = "") -> dict:
    if request.method == "GET":
        if request_key:
            raise ForexError("INVALID_REQUEST_KEY", "GET requires an empty request key")
    elif not re.fullmatch(r"[A-Za-z0-9._~-]{5,128}", request_key):
        raise ForexError("INVALID_REQUEST_KEY", "A mutation requires a stable request key")
    stamp = time.time_ns() // 1_000_000
    payload = json.dumps(
        {
            "api_key": api_key,
            "idempotency_key": request_key,
            "timestamp": stamp,
            "sign_version": 1,
            "method": request.method,
            "path": request.url.raw_path.decode("ascii"),
            "body_hash": b64(hashlib.sha256(request.content).digest()),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return {
        "EXN-API-KEY": api_key,
        "EXN-IDEMPOTENCY-KEY": request_key,
        "EXN-TIMESTAMP": str(stamp),
        "EXN-SIGN-VERSION": "1",
        "EXN-DATA": b64(payload),
        "EXN-SIGN": b64(key.sign(payload)),
    }

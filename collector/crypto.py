"""Шифрование файла с настройками (список компаний и профилей) ключом RADAR_KEY."""
from __future__ import annotations

import hashlib
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"RDR1"


def _key(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), b"radar-config-v1", 200_000)


def encrypt(data: bytes, secret: str) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(_key(secret)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, secret: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("bad config file")
    nonce, ct = blob[4:16], blob[16:]
    return AESGCM(_key(secret)).decrypt(nonce, ct, MAGIC)


if __name__ == "__main__":
    # python collector/crypto.py encrypt config/private.json config/private.enc   (ключ в RADAR_KEY)
    mode, src, dst = sys.argv[1:4]
    k = os.environ["RADAR_KEY"]
    raw = open(src, "rb").read()
    open(dst, "wb").write(encrypt(raw, k) if mode == "encrypt" else decrypt(raw, k))

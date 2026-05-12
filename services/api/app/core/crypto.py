"""AES-256-GCM wrapper for at-rest face-embedding encryption.

Storage layout for an encrypted blob:

    [1 byte : key version][12 bytes : nonce][N bytes : ciphertext + tag]

The leading key-version byte lets us rotate `FACE_ENCRYPTION_KEY` later
without losing the ability to decrypt older rows — column
`users.face_key_version` records which version was used so a future
re-encryption job can find them.

M1 stores a stub embedding (the M8 face model isn't built yet). The
wrapper exists so the storage shape is locked in before real biometrics
land.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_BYTES = 12
_VERSION_BYTES = 1


def _load_key() -> bytes:
    raw = settings.face_encryption_key.get_secret_value()
    try:
        key = bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError("FACE_ENCRYPTION_KEY must be 64 hex characters (32 bytes)") from e
    if len(key) != 32:
        raise RuntimeError("FACE_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def encrypt_face_embedding(plaintext: bytes) -> bytes:
    """Encrypt `plaintext`. Returns version || nonce || ciphertext."""
    key = _load_key()
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    version = settings.face_key_version.to_bytes(_VERSION_BYTES, "big")
    return version + nonce + ct


def decrypt_face_embedding(blob: bytes) -> bytes:
    """Decrypt a blob produced by `encrypt_face_embedding`."""
    if len(blob) < _VERSION_BYTES + _NONCE_BYTES + 16:
        raise ValueError("encrypted blob is too short")
    version = blob[0]
    if version != settings.face_key_version:
        # Real key-rotation support comes when M8 ships; for now we only
        # know the current key. Surfacing the version mismatch makes the
        # need to migrate older rows visible rather than silent.
        raise RuntimeError(
            f"blob encrypted with key version {version}, current is {settings.face_key_version}"
        )
    nonce = blob[_VERSION_BYTES : _VERSION_BYTES + _NONCE_BYTES]
    ct = blob[_VERSION_BYTES + _NONCE_BYTES :]
    return AESGCM(_load_key()).decrypt(nonce, ct, associated_data=None)

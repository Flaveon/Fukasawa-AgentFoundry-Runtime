# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Signing and content-integrity primitives.

Two distinct guarantees, kept separate on purpose:

* **Integrity** — ``content_hash`` produces a stable SHA-256 over a graph or
  bundle. Pinning that hash into a checkpoint is how the kernel detects a
  graph swapped underneath a running graph (a validly-signed but *different*
  graph is still a different graph).

* **Authenticity** — ``sign``/``verify`` use Ed25519 detached signatures so a
  recipient can prove *who* produced an artifact and that it has not changed
  since. This is what makes a shared graph safe to run: the runner executes
  it only if a key the operator trusts signed the exact bytes.

Signing does not sandbox. A trusted author can still ship a destructive
graph. Trust here means "I vouch for this author," which is exactly the
decision a human should own — so the runtime enforces the signature and
leaves the vouching to a person (see security/trust.py).
"""

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_bytes(payload) -> bytes:
    """Serialize a value to stable bytes for hashing or signing.

    Uses sorted-key JSON so the same logical content always hashes the same
    way regardless of dict ordering or incidental whitespace. Strings and
    bytes pass through directly (a raw file's bytes are already canonical).
    """
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(payload) -> str:
    """Return the SHA-256 hex digest of a value's canonical bytes."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 signing identity, as PEM text for on-disk storage."""

    private_pem: str
    public_pem: str


def generate_keypair() -> KeyPair:
    """Create a fresh Ed25519 signing identity."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return KeyPair(private_pem=private_pem, public_pem=public_pem)


def _load_private(private_pem: str) -> Ed25519PrivateKey:
    """Parse a private key from PEM. Raises ValueError on malformed input."""
    key = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key


def _load_public(public_pem: str) -> Ed25519PublicKey:
    """Parse a public key from PEM. Raises ValueError on malformed input."""
    key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return key


def public_key_id(public_pem: str) -> str:
    """A short, stable fingerprint of a public key, for naming in a trust store."""
    return content_hash(public_pem)[:16]


def sign(payload, private_pem: str) -> str:
    """Sign a value's canonical bytes; return a base64 detached signature."""
    signature = _load_private(private_pem).sign(canonical_bytes(payload))
    return base64.b64encode(signature).decode("ascii")


def verify(payload, signature_b64: str, public_pem: str) -> bool:
    """Return True iff signature_b64 is a valid signature of payload by public_pem.

    Never raises on a bad signature — a failed verification is a normal,
    expected answer ("no, don't trust this"), not an exceptional condition.
    """
    try:
        _load_public(public_pem).verify(
            base64.b64decode(signature_b64), canonical_bytes(payload)
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False

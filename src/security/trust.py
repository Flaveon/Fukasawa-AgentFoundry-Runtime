# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""Trust store — the human decision about whose signatures to honor.

A TrustStore is a directory of trusted public keys plus one local signing
identity. The runtime never decides trust on its own: adding a key to the
store is a person saying "I vouch for this author." The runtime only
enforces the consequence — a graph or bundle signed by a key in the store
runs; anything else is refused when signature enforcement is on.

Layout (default: ~/.fukasawa/):
    identity/private.pem     this operator's signing key (kept local, 0600)
    identity/public.pem      this operator's public key
    trusted/<key_id>.pem     one file per trusted public key
    trusted/<key_id>.name    optional human label for that key

The local identity is auto-trusted: you always trust yourself, so
locally-authored graphs run without ceremony while shared graphs must clear
the bar.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from src.security.signing import (
    KeyPair,
    generate_keypair,
    public_key_id,
    sign,
    verify,
)

#: Default root for the trust store, overridable for tests and portable installs.
DEFAULT_TRUST_ROOT = Path(os.environ.get("FUKASAWA_HOME", "~/.fukasawa")).expanduser()


@dataclass
class TrustedKey:
    """One public key the operator has chosen to honor."""

    key_id: str
    public_pem: str
    name: str = ""


class TrustStore:
    """Filesystem-backed set of trusted keys and the local signing identity."""

    def __init__(self, root: str | Path = DEFAULT_TRUST_ROOT) -> None:
        """Open (creating if needed) the trust store at ``root``."""
        self.root = Path(root)
        self.identity_dir = self.root / "identity"
        self.trusted_dir = self.root / "trusted"
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        self.trusted_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- identity

    def ensure_identity(self, name: str = "") -> KeyPair:
        """Return the local signing identity, creating one on first use.

        The private key is written 0600 — a signing key readable by other
        users is not an identity, it is an impersonation waiting to happen.
        """
        priv_path = self.identity_dir / "private.pem"
        pub_path = self.identity_dir / "public.pem"
        if priv_path.exists() and pub_path.exists():
            return KeyPair(
                private_pem=priv_path.read_text(encoding="utf-8"),
                public_pem=pub_path.read_text(encoding="utf-8"),
            )
        keypair = generate_keypair()
        priv_path.write_text(keypair.private_pem, encoding="utf-8")
        os.chmod(priv_path, 0o600)
        pub_path.write_text(keypair.public_pem, encoding="utf-8")
        # Trust yourself, and label the key if a name was given.
        self.trust(keypair.public_pem, name=name or "local-identity")
        return keypair

    def sign_with_identity(self, payload) -> tuple[str, str]:
        """Sign a payload with the local identity; return (signature, public_pem)."""
        keypair = self.ensure_identity()
        return sign(payload, keypair.private_pem), keypair.public_pem

    # ------------------------------------------------------------------ trust

    def trust(self, public_pem: str, name: str = "") -> TrustedKey:
        """Add a public key to the trusted set (idempotent by key id)."""
        key_id = public_key_id(public_pem)
        (self.trusted_dir / f"{key_id}.pem").write_text(public_pem, encoding="utf-8")
        if name:
            (self.trusted_dir / f"{key_id}.name").write_text(name, encoding="utf-8")
        return TrustedKey(key_id=key_id, public_pem=public_pem, name=name)

    def revoke(self, key_id: str) -> bool:
        """Remove a key from the trusted set. Returns True if it was present."""
        pem = self.trusted_dir / f"{key_id}.pem"
        label = self.trusted_dir / f"{key_id}.name"
        existed = pem.exists()
        pem.unlink(missing_ok=True)
        label.unlink(missing_ok=True)
        return existed

    def trusted_keys(self) -> list[TrustedKey]:
        """Return every trusted key, with its label if one was set."""
        keys = []
        for pem_path in sorted(self.trusted_dir.glob("*.pem")):
            key_id = pem_path.stem
            name_path = self.trusted_dir / f"{key_id}.name"
            keys.append(
                TrustedKey(
                    key_id=key_id,
                    public_pem=pem_path.read_text(encoding="utf-8"),
                    name=name_path.read_text(encoding="utf-8") if name_path.exists() else "",
                )
            )
        return keys

    def is_trusted_signature(self, payload, signature_b64: str) -> bool:
        """True iff any trusted key verifies this signature over this payload.

        This is the whole enforcement point: the runtime asks the store, and
        the store answers only from keys a human put there.
        """
        return any(
            verify(payload, signature_b64, key.public_pem)
            for key in self.trusted_keys()
        )

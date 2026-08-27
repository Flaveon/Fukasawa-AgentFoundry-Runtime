# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
"""What an inference computer is, and what is known about it.

A person handed this product runs their own hardware, so the runtime has to
learn what they have from them. These contracts hold that knowledge, and one
field of them is unusual enough to call out: ``provenance`` records *where
each value came from* — read from the machine, measured with a clock, or typed
by a person. The screens show it, because a reader needs to know which rows to
check.

Values are flat with a separate ``provenance`` map rather than each value
wrapped in ``{value, source}``. These files are hand-editable and the wrapped
form doubles their depth.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

#: Reject unknown fields so a typo surfaces loudly rather than being ignored.
STRICT = ConfigDict(extra="forbid")

#: Slug pattern, matching the rest of the repository's identifiers.
SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"

#: Contract version for this module. Additive within a major version.
SCHEMA_VERSION = "1"


class ScanScope(str, Enum):
    """How far a person has permitted the scan to reach.

    NONE          — nothing is scanned; no socket is opened at all.
    THIS_MACHINE  — loopback ports, plus this computer's own CPU/RAM/OS.
    NAMED_HOST    — exactly one address, given by the person.
    LOCAL_NETWORK — the primary interface's /24, two known ports.
    """

    NONE = "NONE"
    THIS_MACHINE = "THIS_MACHINE"
    NAMED_HOST = "NAMED_HOST"
    LOCAL_NETWORK = "LOCAL_NETWORK"


class Provenance(str, Enum):
    """Where a value came from. Rendered in plain words on screen."""

    DETECTED = "DETECTED"   # read from the machine's own API
    MEASURED = "MEASURED"   # timed with a clock
    DECLARED = "DECLARED"   # a person typed it
    UNKNOWN = "UNKNOWN"     # nobody has said


class NodeKind(str, Enum):
    """Which inference server is answering."""

    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"


def slugify(label: str) -> str:
    """Turn a human label into a stable identifier.

    Falls back to ``computer`` when a label contains nothing usable, because an
    id is required and an empty string would fail validation somewhere less
    obvious.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "computer"


class ModelCapability(BaseModel):
    """One model an inference computer can serve."""

    model_config = STRICT

    name: str = Field(description="Model identifier, e.g. 'llama3.1:8b'.")
    family: str = Field(default="", description="Model family, e.g. 'llama'.")
    parameter_size: str = Field(
        default="", description="Parameter count as reported, e.g. '8.0B'."
    )
    quantization: str = Field(
        default="", description="Quantisation as reported, e.g. 'Q4_K_M'."
    )
    context_length: int = Field(
        default=0,
        description="Longest input in tokens. 0 means it was not established.",
    )
    supports_tools: bool = Field(
        default=False, description="Whether the model accepts tool definitions."
    )
    supports_vision: bool = Field(
        default=False, description="Whether the model accepts images."
    )
    size_bytes: int = Field(
        default=0, description="On-disk size as reported. 0 means unknown."
    )


class HostCapability(BaseModel):
    """What is known about the machine behind the server.

    ``vram_bytes`` is a **floor, never a total**: an inference server reports
    what a *currently loaded* model committed, so nothing loaded reads as zero
    and that does not mean there is no graphics card. ``gpu_present`` is a true
    tri-state for the same reason.
    """

    model_config = STRICT

    gpu_present: Optional[bool] = Field(
        default=None,
        description=(
            "True when committed video memory was observed, False only when a "
            "backend positively reports no offload, None when unestablished."
        ),
    )
    vram_bytes: int = Field(
        default=0,
        description="Video memory observed in use. A floor, not a total.",
    )
    cpu_count: int = Field(
        default=0, description="Processor count. Local scans only."
    )
    ram_bytes: int = Field(
        default=0, description="System memory. Local scans only."
    )
    platform: str = Field(
        default="", description="Operating system string. Local scans only."
    )
    tokens_per_second: float = Field(
        default=0.0, description="Generation rate, measured. 0.0 means unmeasured."
    )
    latency_ms: float = Field(
        default=0.0, description="Round-trip time to the server, measured."
    )


class InferenceNode(BaseModel):
    """One inference computer and everything known about it."""

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION, description="Contract version this was written against."
    )
    node_id: str = Field(
        pattern=SLUG, description="Stable identifier, unique within the store."
    )
    label: str = Field(description="What the person calls this computer.")
    kind: NodeKind = Field(description="Which inference server answers here.")
    url: str = Field(description="Base URL the server answers on.")
    is_local: bool = Field(
        default=False, description="Whether this is the machine Fukasawa runs on."
    )
    reachable: bool = Field(
        default=False, description="Whether it answered the last time it was tried."
    )
    backend_version: str = Field(
        default="", description="Server version as reported."
    )
    models: list[ModelCapability] = Field(
        default_factory=list, description="Models this computer can serve."
    )
    host: HostCapability = Field(
        default_factory=HostCapability, description="What is known about the machine."
    )
    provenance: dict[str, Provenance] = Field(
        default_factory=dict,
        description=(
            "Where each value came from, keyed by dotted field path such as "
            "'host.vram_bytes'. A missing key means UNKNOWN."
        ),
    )
    last_probed_at: Optional[datetime] = Field(
        default=None, description="When this computer was last examined (UTC)."
    )
    notes: str = Field(default="", description="Anything else worth recording.")

    def source_of(self, field_path: str) -> Provenance:
        """Where one value came from. UNKNOWN when nothing was recorded."""
        return self.provenance.get(field_path, Provenance.UNKNOWN)

    @property
    def max_context_length(self) -> int:
        """Longest input any model here accepts, in tokens. 0 if unestablished."""
        return max((m.context_length for m in self.models), default=0)


class ScanConsent(BaseModel):
    """A person's standing permission for how far a scan may reach.

    Defaults to NONE: nothing is examined until somebody says so. Attribution
    is self-attested, as everywhere else in this runtime — there is no
    authentication.
    """

    model_config = STRICT

    schema_version: str = Field(
        default=SCHEMA_VERSION, description="Contract version."
    )
    scope: ScanScope = Field(
        default=ScanScope.NONE, description="How far a scan may reach."
    )
    granted_by: str = Field(
        default="", description="Who granted it (self-attested)."
    )
    granted_at: Optional[datetime] = Field(
        default=None, description="When it was granted (UTC)."
    )

    @classmethod
    def granted(cls, scope: ScanScope, by: str) -> "ScanConsent":
        """Record a grant made now."""
        return cls(scope=scope, granted_by=by, granted_at=datetime.now(timezone.utc))

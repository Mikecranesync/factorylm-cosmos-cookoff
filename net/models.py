"""
Shared data models for FactoryLM Connect.

Canonical tag format used across extraction, polling, and API responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedTag:
    """A single tag discovered from a PLC."""
    name: str
    type: str = "UNKNOWN"
    value: Any = None
    address: str = ""
    writable: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "value": self.value,
            "address": self.address,
            "writable": self.writable,
        }


@dataclass
class TagExtractionResult:
    """Result of a tag extraction operation."""
    gateway_id: str
    plc_ip: str
    protocol: str
    tags: list[dict] = field(default_factory=list)
    extracted_at: str = ""

    def to_dict(self) -> dict:
        return {
            "gateway_id": self.gateway_id,
            "plc_ip": self.plc_ip,
            "protocol": self.protocol,
            "tags": self.tags,
            "extracted_at": self.extracted_at,
        }

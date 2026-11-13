"""Adapter registry. Adapter packages register their instances on import.

`discover()` imports the `accessory` and `host` packages with literal imports. A package
that does not exist is skipped; one that exists but fails to import raises loudly, so a
broken adapter never degrades into a silently missing one.
"""
from __future__ import annotations

import importlib.util

from .base import Adapter

REGISTRY: dict[str, Adapter] = {}


class RegistryError(ValueError):
    pass


def register(adapter: Adapter) -> Adapter:
    if not isinstance(adapter, Adapter):
        raise RegistryError("not an adapter")
    existing = REGISTRY.get(adapter.info.id)
    if existing is not None and existing is not adapter:
        raise RegistryError("adapter id already registered")
    REGISTRY[adapter.info.id] = adapter
    return adapter


def get(adapter_id: str) -> Adapter | None:
    return REGISTRY.get(adapter_id)


def all_adapters(kind: str | None = None) -> list[Adapter]:
    return [a for a in REGISTRY.values() if kind is None or a.info.kind == kind]


def _missing_ok(name: str) -> None:
    """Called from an `except ImportError`: skip an absent package, re-raise a present but broken one."""
    if importlib.util.find_spec(f"{__package__}.{name}") is not None:
        raise


def discover() -> None:
    try:
        from . import accessory  # noqa: F401
    except ImportError:
        _missing_ok("accessory")
    try:
        from . import host  # noqa: F401
    except ImportError:
        _missing_ok("host")

"""Backward-compatible re-exports; the implementation lives in microflow.persistence.

``microflow.testing.MemoryStateStore`` keeps working for existing hosts and
tests, but the canonical home of the memory provider is
``microflow.persistence.memory`` (it is also the default persistence kind).
"""
from .persistence.memory import MemoryStateStore

__all__ = ["MemoryStateStore"]

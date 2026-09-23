"""Data sources. Each exposes ``fetch(since) -> list[Trade]``."""

from .finansinspektionen import FinansinspektionenSource
from .oslo_bors import OsloBorsSource

__all__ = ["FinansinspektionenSource", "OsloBorsSource"]

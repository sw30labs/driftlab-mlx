"""DriftLab web command deck — stdlib-only, air-gapped, loopback-only."""

from .server import DeckHandler, main, serve

__all__ = ["DeckHandler", "main", "serve"]

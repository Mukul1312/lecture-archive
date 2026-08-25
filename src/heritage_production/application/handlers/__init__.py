"""Command handlers: one module per aggregate that owns the write."""

from .production import ProductionCommandHandlers


__all__ = ["ProductionCommandHandlers"]

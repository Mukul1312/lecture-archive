"""Command handlers: one module per aggregate that owns the write."""

from .production import ProductionCommandHandlers
from .registration import RegistrationCommandHandlers
from .transcription import TranscriptionCommandHandlers


__all__ = [
    "ProductionCommandHandlers",
    "RegistrationCommandHandlers",
    "TranscriptionCommandHandlers",
]

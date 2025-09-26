"""Utilities for building Mandarin study decks."""
from .builder import (
    DeckBuildConfig,
    DeckBuildError,
    DeckBuildResult,
    ProgressEvent,
    ProgressCallback,
    build_anki_deck,
)
from .audio_engine import AudioGenerationConfig, generate_audio_from_text

__version__ = "2.0.0"

__all__ = [
    "DeckBuildConfig",
    "DeckBuildError",
    "DeckBuildResult",
    "ProgressEvent",
    "ProgressCallback",
    "build_anki_deck",
    "AudioGenerationConfig",
    "generate_audio_from_text",
    "__version__",
]

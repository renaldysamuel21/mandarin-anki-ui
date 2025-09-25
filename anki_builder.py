"""Backward compatible entry-points for building Anki decks."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from mandarin_anki_ui import (
    DEFAULT_COLUMNS,
    DeckBuildConfig,
    DeckBuildResult,
    build_anki_deck as _build_anki_deck,
)


def build_anki_deck(
    *,
    csv_path: Path,
    output_dir: Path,
    ffmpeg_path: Optional[Path],
    tts_model_name: str,
    tts_lang: str,
    speaker_wav: Path,
    ambient_wav: Optional[Path] = None,
    regenerate_audio_if_exists: bool = False,
    delimiter: str = ";",
    encoding: str = "utf-8-sig",
    columns: Optional[Dict[str, str]] = None,
    use_literal_linebreaks: bool = True,
    volume_voice_db: float = -6.0,
    volume_ambient_db: float = -38.0,
    bitrate_mp3: str = "192k",
) -> Path:
    """Compatibility wrapper that mirrors the legacy signature."""

    config = DeckBuildConfig(
        csv_path=csv_path,
        output_dir=output_dir,
        speaker_wav=speaker_wav,
        tts_model_name=tts_model_name,
        tts_lang=tts_lang,
        ffmpeg_path=ffmpeg_path,
        ambient_wav=ambient_wav,
        regenerate_audio_if_exists=regenerate_audio_if_exists,
        delimiter=delimiter,
        encoding=encoding,
        columns=columns or DEFAULT_COLUMNS,
        use_literal_linebreaks=use_literal_linebreaks,
        volume_voice_db=volume_voice_db,
        volume_ambient_db=volume_ambient_db,
        bitrate_mp3=bitrate_mp3,
    )
    result: DeckBuildResult = _build_anki_deck(config)
    return result.apkg_path


__all__ = ["build_anki_deck", "DeckBuildConfig", "DeckBuildResult", "DEFAULT_COLUMNS"]

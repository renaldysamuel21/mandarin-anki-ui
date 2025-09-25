"""Audio helpers that wrap pydub operations for testability."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydub import AudioSegment


class AudioEngine(Protocol):
    """Simple protocol describing the audio pipeline used by the deck builder."""

    def render(
        self,
        *,
        voice_wav: Path,
        ambient_wav: Path | None,
        output_mp3: Path,
        volume_voice_db: float,
        volume_ambient_db: float,
        bitrate: str,
    ) -> None:
        """Render the final MP3 file from TTS voice and optional ambient track."""


class PydubAudioEngine:
    """Concrete :class:`AudioEngine` implementation powered by :mod:`pydub`."""

    def __init__(self, ffmpeg_path: Path | None = None) -> None:
        if ffmpeg_path and ffmpeg_path.exists():
            AudioSegment.converter = str(ffmpeg_path)

    def render(
        self,
        *,
        voice_wav: Path,
        ambient_wav: Path | None,
        output_mp3: Path,
        volume_voice_db: float,
        volume_ambient_db: float,
        bitrate: str,
    ) -> None:
        voice = AudioSegment.from_wav(voice_wav) + volume_voice_db
        if ambient_wav and ambient_wav.exists():
            ambient = AudioSegment.from_wav(ambient_wav)
            if len(ambient) < len(voice):
                repeats = (len(voice) // len(ambient)) + 1
                ambient = ambient * repeats
            ambient = ambient[: len(voice)] + volume_ambient_db
            final_audio = voice.overlay(ambient)
        else:
            final_audio = voice
        final_audio.export(output_mp3, format="mp3", bitrate=bitrate)

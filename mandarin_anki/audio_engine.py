"""Reusable helpers for synthesising Mandarin audio clips."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .builder import (
    DeckBuildError,
    DefaultTTSFactory,
    TTSFactory,
    TTSLike,
    _ensure_ffmpeg,
    _render_audio,
)


@dataclass(frozen=True)
class AudioGenerationConfig:
    """Configuration options for :func:`generate_audio_from_text`."""

    text: str
    output_path: Path
    speaker_wav: Path
    tts_model_name: str
    tts_lang: str
    ffmpeg_path: Optional[Path] = None
    ambient_wav: Optional[Path] = None
    volume_voice_db: float = -6.0
    volume_ambient_db: float = -38.0
    bitrate: str = "192k"
    audio_format: str = "mp3"
    device_preference: Sequence[str] = ("cuda", "cpu")


class _AudioConfigProxy:
    """Minimal view over deck config attributes consumed by ``_render_audio``."""

    def __init__(
        self,
        *,
        tts_lang: str,
        volume_voice_db: float,
        volume_ambient_db: float,
        bitrate: str,
        audio_format: str,
    ) -> None:
        self.tts_lang = tts_lang
        self.volume_voice_db = volume_voice_db
        self.volume_ambient_db = volume_ambient_db
        self.bitrate = bitrate
        self.audio_format = audio_format


def _prepare_tts(
    *,
    factory: TTSFactory,
    model_name: str,
    device_preference: Sequence[str],
) -> TTSLike:
    tts = factory.create(model_name)
    for device in device_preference:
        try:
            tts.to(device)
            break
        except Exception:
            continue
    return tts


def generate_audio_from_text(
    config: AudioGenerationConfig,
    *,
    tts_factory: Optional[TTSFactory] = None,
) -> Path:
    """Generate an audio clip for arbitrary Hanzi text and return the file path."""

    text = (config.text or "").strip()
    if not text:
        raise DeckBuildError("Teks Hanzi tidak boleh kosong.")

    speaker = config.speaker_wav.expanduser()
    if not speaker.exists():
        raise DeckBuildError(f"Speaker WAV tidak ditemukan: {speaker}")

    ambient = config.ambient_wav.expanduser() if config.ambient_wav else None
    if ambient is not None and not ambient.exists():
        ambient = None

    output_path = config.output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _ensure_ffmpeg(config.ffmpeg_path)

    factory = tts_factory or DefaultTTSFactory()
    tts = _prepare_tts(
        factory=factory,
        model_name=config.tts_model_name,
        device_preference=config.device_preference,
    )

    tmp_wav = output_path.with_name(f"{output_path.stem}_tmp.wav")
    proxy = _AudioConfigProxy(
        tts_lang=config.tts_lang,
        volume_voice_db=config.volume_voice_db,
        volume_ambient_db=config.volume_ambient_db,
        bitrate=config.bitrate,
        audio_format=config.audio_format,
    )

    _render_audio(
        tts=tts,
        text=text,
        tmp_wav=tmp_wav,
        speaker_wav=speaker,
        ambient_wav=ambient,
        config=proxy,
        final_path=output_path,
    )

    return output_path


__all__ = ["AudioGenerationConfig", "generate_audio_from_text"]

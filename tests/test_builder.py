from __future__ import annotations

import wave
from pathlib import Path
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_stubs() -> None:
    if "pydub" not in sys.modules:
        pydub_module = types.ModuleType("pydub")

        class _AudioSegment:
            converter = None

            def __init__(self, frames: int = 0) -> None:
                self._frames = frames

            @classmethod
            def from_wav(cls, path: Path) -> "_AudioSegment":
                with wave.open(str(path), "rb") as wav:
                    frames = wav.getnframes()
                return cls(frames)

            def __len__(self) -> int:
                return self._frames

            def __add__(self, other: float) -> "_AudioSegment":  # volume adjustments ignored in stub
                return self

            def __mul__(self, repeat: int) -> "_AudioSegment":
                return _AudioSegment(self._frames * repeat)

            def __getitem__(self, item) -> "_AudioSegment":
                if isinstance(item, slice):
                    stop = item.stop or self._frames
                    return _AudioSegment(min(self._frames, stop))
                raise TypeError("AudioSegment slicing only supports slices in tests")

            def overlay(self, other: "_AudioSegment") -> "_AudioSegment":
                return _AudioSegment(max(self._frames, other._frames))

            def export(self, path: Path, format: str, bitrate: str) -> None:
                _write_silence(Path(path))

        pydub_module.AudioSegment = _AudioSegment
        sys.modules["pydub"] = pydub_module

    if "genanki" not in sys.modules:
        genanki_module = types.ModuleType("genanki")

        class _Note:
            def __init__(self, *, model, fields, tags):
                self.model = model
                self.fields = fields
                self.tags = tags

        class _Deck:
            def __init__(self, deck_id: int, title: str):
                self.deck_id = deck_id
                self.title = title
                self.notes = []

            def add_note(self, note: _Note) -> None:
                self.notes.append(note)

        class _Model:
            def __init__(self, model_id: int, name: str, fields, templates, css):
                self.model_id = model_id
                self.name = name
                self.fields = fields
                self.templates = templates
                self.css = css

        class _Package:
            def __init__(self, deck: _Deck, media_files):
                self.deck = deck
                self.media_files = media_files

            def write_to_file(self, path: Path) -> None:
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("collection.anki2", b"stub")
                    for media in self.media_files:
                        archive.write(media, arcname=Path(media).name)

        genanki_module.Note = _Note
        genanki_module.Deck = _Deck
        genanki_module.Model = _Model
        genanki_module.Package = _Package
        sys.modules["genanki"] = genanki_module


_ensure_stubs()

from mandarin_anki import DeckBuildConfig, build_anki_deck


class _StubTTS:
    def __init__(self) -> None:
        self.device = "cpu"

    def to(self, device: str) -> None:  # pragma: no cover - trivial setter
        self.device = device

    def tts_to_file(self, *, text: str, speaker_wav: str, language: str, file_path: Path, split_sentences: bool) -> None:
        _write_silence(file_path)


class _StubFactory:
    def create(self, model_name: str):  # pragma: no cover - trivial factory
        return _StubTTS()


def _write_silence(path: Path, duration_seconds: int = 1) -> None:
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        num_frames = 22050 * duration_seconds
        wav.writeframes(b"\x00\x00" * num_frames)


def _build_wav(path: Path) -> None:
    _write_silence(path)


def test_build_anki_deck_creates_package(tmp_path):
    csv_path = tmp_path / "deck.csv"
    csv_path.write_text(
        """Hanzi,Pinyin,Indo
你好,nǐ hǎo,Halo
谢谢,xièxie,Terima kasih
""",
        encoding="utf-8",
    )

    speaker_wav = tmp_path / "speaker.wav"
    ambient_wav = tmp_path / "ambient.wav"
    _build_wav(speaker_wav)
    _build_wav(ambient_wav)
    ffmpeg_path = tmp_path / "ffmpeg"
    ffmpeg_path.write_text("#!/bin/sh\n")

    config = DeckBuildConfig(
        csv_path=csv_path,
        output_dir=tmp_path / "output",
        speaker_wav=speaker_wav,
        tts_model_name="stub",
        tts_lang="zh",
        ambient_wav=ambient_wav,
        regenerate_audio_if_exists=True,
        delimiter=",",
        audio_format="wav",
        ffmpeg_path=ffmpeg_path,
    )

    stages = []

    def _on_progress(event):
        stages.append(event.stage)

    result = build_anki_deck(config, tts_factory=_StubFactory(), progress_callback=_on_progress)

    assert result.apkg_path.exists()
    assert result.rows_processed == 2
    assert result.row_errors == []
    assert {"init", "rows", "row", "complete"}.issubset(stages)
    assert all(media.suffix == ".wav" and media.exists() for media in result.media_files)


def test_build_anki_deck_creates_nested_audio_directories(tmp_path):
    csv_path = tmp_path / "deck.csv"
    csv_path.write_text(
        """Hanzi,Audio\n你好,custom/nested/audio\n""",
        encoding="utf-8",
    )

    speaker_wav = tmp_path / "speaker.wav"
    _build_wav(speaker_wav)
    ffmpeg_path = tmp_path / "ffmpeg"
    ffmpeg_path.write_text("#!/bin/sh\n")

    config = DeckBuildConfig(
        csv_path=csv_path,
        output_dir=tmp_path / "output",
        speaker_wav=speaker_wav,
        tts_model_name="stub",
        tts_lang="zh",
        regenerate_audio_if_exists=True,
        delimiter=",",
        audio_format="wav",
        ffmpeg_path=ffmpeg_path,
    )

    result = build_anki_deck(config, tts_factory=_StubFactory())

    expected_audio = config.output_dir / "custom/nested/audio.wav"
    assert expected_audio.exists()
    assert expected_audio in result.media_files

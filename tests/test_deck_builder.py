from __future__ import annotations

import sys
import types
import wave
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeAudioSegment:
    converter: str = ""

    def __init__(self, duration: int = 1000) -> None:
        self._duration = duration

    @classmethod
    def from_wav(cls, path: Path) -> "_FakeAudioSegment":
        return cls()

    def __add__(self, _other: float) -> "_FakeAudioSegment":
        return self

    def overlay(self, _other: "_FakeAudioSegment") -> "_FakeAudioSegment":
        return self

    def export(self, target: Path, *, format: str, bitrate: str) -> None:  # noqa: A003 - match pydub signature
        Path(target).write_bytes(b"mp3")

    def __len__(self) -> int:
        return self._duration

    def __mul__(self, _repeat: int) -> "_FakeAudioSegment":
        return self

    def __getitem__(self, _key) -> "_FakeAudioSegment":
        return self


class _FakeModel:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _FakeDeck:
    def __init__(self, deck_id: int, title: str) -> None:
        self.deck_id = deck_id
        self.title = title
        self.notes: List[object] = []

    def add_note(self, note: object) -> None:
        self.notes.append(note)


class _FakeNote:
    def __init__(self, model: object, fields: List[str], tags: List[str]) -> None:
        self.model = model
        self.fields = fields
        self.tags = tags


class _FakePackage:
    def __init__(self, deck: _FakeDeck, media_files: List[str]) -> None:
        self.deck = deck
        self.media_files = media_files

    def write_to_file(self, target: Path) -> None:
        Path(target).write_bytes(b"apkg")


sys.modules.setdefault(
    "genanki",
    types.SimpleNamespace(
        Model=_FakeModel,
        Deck=_FakeDeck,
        Note=_FakeNote,
        Package=_FakePackage,
    ),
)

sys.modules.setdefault("pydub", types.SimpleNamespace(AudioSegment=_FakeAudioSegment))

from mandarin_anki_ui import DeckBuildConfig, build_anki_deck
from mandarin_anki_ui.audio_engine import AudioEngine


class DummyTTS:
    def __init__(self) -> None:
        self.device_calls: List[str] = []

    def to(self, device: str) -> "DummyTTS":
        self.device_calls.append(device)
        return self

    def tts_to_file(
        self,
        *,
        text: str,
        speaker_wav: str,
        language: str,
        file_path: Path,
        split_sentences: bool,
    ) -> None:
        with wave.open(str(file_path), "w") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"\x00\x00" * 22050)


class DummyAudioEngine(AudioEngine):
    def __init__(self) -> None:
        self.calls: List[Tuple[Path, Optional[Path], Path]] = []

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
        self.calls.append((voice_wav, ambient_wav, output_mp3))
        output_mp3.write_bytes(b"ID3test")


def _generate_wav(target: Path) -> None:
    with wave.open(str(target), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\x00\x00" * 22050)


def test_build_anki_deck_creates_apkg(tmp_path: Path) -> None:
    csv_content = "Hanzi;Pinyin;Indo\n你好;ni hao;Halo\n谢谢;xie xie;Terima kasih\n"
    csv_path = tmp_path / "cards.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    speaker = tmp_path / "speaker.wav"
    ambient = tmp_path / "ambient.wav"
    _generate_wav(speaker)
    _generate_wav(ambient)

    engine = DummyAudioEngine()
    config = DeckBuildConfig(
        csv_path=csv_path,
        output_dir=tmp_path,
        speaker_wav=speaker,
        tts_model_name="dummy",
        tts_lang="zh-cn",
        ambient_wav=ambient,
        regenerate_audio_if_exists=True,
    )

    progress_events: List[Tuple[str, int, int]] = []

    def on_progress(stage: str, current: int, total: int) -> None:
        progress_events.append((stage, current, total))

    result = build_anki_deck(
        config,
        tts_factory=lambda _: DummyTTS(),
        audio_engine=engine,
        on_progress=on_progress,
    )

    assert result.apkg_path.exists()
    assert result.processed_count == 2
    assert result.skipped_count == 0
    assert engine.calls  # audio engine must be used
    assert any(stage == "processing" for stage, *_ in progress_events)

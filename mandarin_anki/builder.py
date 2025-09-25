"""Core logic for building Mandarin Anki decks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import csv
import random
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Sequence

import genanki
from pydub import AudioSegment


DEFAULT_COLUMNS: Dict[str, str] = {
    "Hanzi": "Hanzi",
    "Pinyin": "Pinyin",
    "Indo": "Indo",
    "Literal": "Literal",
    "Grammar": "Grammar",
    "Audio": "Audio",
    "Enable_RM": "Enable_RM",
    "Enable_LT": "Enable_LT",
    "Enable_MP": "Enable_MP",
    "Tags": "Tags",
    "UID": "UID",
}


class TTSLike(Protocol):
    """Runtime interface of a TTS model that is sufficient for this builder."""

    def to(self, device: str) -> None:  # pragma: no cover - thin wrapper around external API
        ...

    def tts_to_file(
        self,
        *,
        text: str,
        speaker_wav: str,
        language: str,
        file_path: Path,
        split_sentences: bool,
    ) -> None:  # pragma: no cover - thin wrapper around external API
        ...


class TTSFactory(Protocol):
    """Factory used to lazily create a TTS model."""

    def create(self, model_name: str) -> TTSLike:  # pragma: no cover - behaviour covered via builder
        ...


class DefaultTTSFactory:
    """Factory that instantiates the Coqui `TTS` class on demand."""

    def create(self, model_name: str) -> TTSLike:  # pragma: no cover - thin wrapper
        from TTS.api import TTS

        return TTS(model_name)


@dataclass(frozen=True)
class ProgressEvent:
    """Structured progress updates emitted during deck generation."""

    stage: str
    current: int = 0
    total: int = 0
    message: Optional[str] = None


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(frozen=True)
class DeckBuildResult:
    """Metadata about the produced deck."""

    apkg_path: Path
    media_files: List[Path]
    rows_processed: int
    row_errors: List[str]


@dataclass(frozen=True)
class DeckBuildConfig:
    """Configuration for :func:`build_anki_deck`."""

    csv_path: Path
    output_dir: Path
    speaker_wav: Path
    tts_model_name: str
    tts_lang: str
    ffmpeg_path: Optional[Path] = None
    ambient_wav: Optional[Path] = None
    regenerate_audio_if_exists: bool = False
    delimiter: str = ";"
    encoding: str = "utf-8-sig"
    columns: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COLUMNS))
    use_literal_linebreaks: bool = True
    volume_voice_db: float = -6.0
    volume_ambient_db: float = -38.0
    bitrate: str = "192k"
    audio_format: str = "mp3"
    device_preference: Sequence[str] = ("cuda", "cpu")


class DeckBuildError(RuntimeError):
    """Raised when the deck cannot be generated."""

    def __init__(self, message: str, *, row_errors: Optional[List[str]] = None):
        super().__init__(message)
        self.row_errors = row_errors or []


def _clean(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.replace("\ufeff", "").replace("\u200b", "").strip()


def _literal_to_br(text: str, enable: bool) -> str:
    if not enable:
        return _clean(text)

    s = _clean(text)
    if not s:
        return ""

    s = re.sub(r"\s*[，,；;]\s*", "<br>", s)
    s = re.sub(r"(?:<br>\s*){2,}", "<br>", s).strip()
    s = re.sub(r"^(<br>)+", "", s)
    s = re.sub(r"(<br>)+$", "", s)
    return s


def _ensure_ffmpeg(path: Optional[Path]) -> None:
    if path and path.exists():
        AudioSegment.converter = str(path)


def _notify(callback: Optional[ProgressCallback], stage: str, *, current: int = 0, total: int = 0, message: Optional[str] = None) -> None:
    if not callback:
        return
    callback(ProgressEvent(stage=stage, current=current, total=total, message=message))


def _read_rows(config: DeckBuildConfig) -> List[Dict[str, str]]:
    if not config.csv_path.exists():
        raise DeckBuildError(f"CSV tidak ditemukan: {config.csv_path}")

    with open(config.csv_path, newline="", encoding=config.encoding) as handle:
        reader = csv.DictReader(handle, delimiter=config.delimiter)
        fieldnames = [_clean(name) for name in (reader.fieldnames or [])]
        reader.fieldnames = fieldnames
        rows = [{_clean(k): _clean(v) for k, v in raw.items()} for raw in reader]

    if not rows:
        raise DeckBuildError("CSV kosong atau tidak memiliki baris data.")

    return rows


def _validate_columns(columns: Dict[str, str]) -> Dict[str, str]:
    mapping = dict(DEFAULT_COLUMNS)
    mapping.update({k: v for k, v in (columns or {}).items() if v})
    return mapping


def _load_audio(path: Path, volume_db: float) -> AudioSegment:
    segment = AudioSegment.from_wav(path)
    return segment + volume_db


def _render_audio(
    *,
    tts: TTSLike,
    text: str,
    tmp_wav: Path,
    speaker_wav: Path,
    ambient_wav: Optional[Path],
    config: DeckBuildConfig,
    final_path: Path,
) -> None:
    tts.tts_to_file(
        text=text,
        speaker_wav=str(speaker_wav),
        language=config.tts_lang,
        file_path=tmp_wav,
        split_sentences=True,
    )

    voice = _load_audio(tmp_wav, config.volume_voice_db)
    if ambient_wav and ambient_wav.exists():
        ambient = _load_audio(ambient_wav, config.volume_ambient_db)
        if len(ambient) < len(voice):
            repeat = (len(voice) // len(ambient)) + 1
            ambient = ambient * repeat
        ambient = ambient[: len(voice)]
        mixed = voice.overlay(ambient)
    else:
        mixed = voice

    mixed.export(final_path, format=config.audio_format, bitrate=config.bitrate)
    try:
        tmp_wav.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best effort cleanup
        pass


def build_anki_deck(
    config: DeckBuildConfig,
    *,
    tts_factory: Optional[TTSFactory] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> DeckBuildResult:
    """Generate an Anki deck and return metadata about the produced package."""

    if not config.speaker_wav.exists():
        raise DeckBuildError(f"Speaker WAV tidak ditemukan: {config.speaker_wav}")

    columns = _validate_columns(config.columns)
    rows = _read_rows(config)
    total_rows = len(rows)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_ffmpeg(config.ffmpeg_path)

    _notify(progress_callback, "init", total=total_rows, message="Menyiapkan deck & model…")

    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id = random.randrange(1 << 30, 1 << 31)
    timestamp_tag = datetime.now().strftime("deck_%Y%m%d_%H%M%S")

    css = """
    .card { font-family: system-ui, 'Noto Sans CJK SC', 'PingFang SC', sans-serif; background:#0b0b0e; color:#eaeaf0; }
    hr { border: 0; border-top: 1px solid #2a2a34; }
    .hanzi { font-size: 32px; line-height: 1.35; margin: 10px 0; }
    .pinyin { margin: 6px 0; color:#c9d1d9; }
    .indo { margin: 4px 0; color:#a9b1bb; }
    .literal { margin-top: 8px; line-height: 1.4; color:#b7c2cc; }
    .grammar { margin-top: 10px; opacity: 0.9; color:#9aa3ad; }
    .hint { margin: 6px 0; color:#9aa3ad; }
    .audio { margin-top: 10px; }
    """

    template_read = {
        "name": "Card 1 - Reading→Meaning",
        "qfmt": """<div class=\"hanzi\">{{Hanzi}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"pinyin\">{{Pinyin}}</div><div class=\"indo\"><em>{{Indo}}</em></div><div class=\"literal\">{{LiteralBr}}</div><div class=\"grammar\">{{Grammar}}</div><div class=\"audio\">{{AudioMarkup}}</div>""",
    }
    template_listen = {
        "name": "Card 2 - Listening→Text",
        "qfmt": """<div class=\"audio\">{{AudioMarkup}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"hanzi\">{{Hanzi}}</div><div class=\"pinyin\">{{Pinyin}}</div><div class=\"indo\">{{Indo}}</div>""",
    }
    template_production = {
        "name": "Card 3 - Meaning→Production",
        "qfmt": """<div class=\"indo\">{{Indo}}</div><div class=\"hint\">Hint: {{Grammar}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"hanzi\">{{Hanzi}}</div><div class=\"pinyin\">{{Pinyin}}</div><div class=\"audio\">{{AudioMarkup}}</div>""",
    }

    model = genanki.Model(
        model_id,
        "CN Sentence (Putonghua)",
        fields=[
            {"name": "Hanzi"},
            {"name": "Pinyin"},
            {"name": "Indo"},
            {"name": "Literal"},
            {"name": "LiteralBr"},
            {"name": "Grammar"},
            {"name": "Audio"},
            {"name": "AudioMarkup"},
            {"name": "Enable_RM"},
            {"name": "Enable_LT"},
            {"name": "Enable_MP"},
            {"name": "Tags"},
            {"name": "UID"},
        ],
        templates=[template_read, template_listen, template_production],
        css=css,
    )

    base_name = config.csv_path.stem.replace(" ", "_")
    deck_title = f"Mandarin Grammar ({base_name}) - {timestamp_tag}"
    deck = genanki.Deck(deck_id, deck_title)
    media_files: List[Path] = []
    row_errors: List[str] = []

    tts_factory = tts_factory or DefaultTTSFactory()
    tts_model: Optional[TTSLike] = None

    def ensure_tts() -> TTSLike:
        nonlocal tts_model
        if tts_model is None:
            tts_model = tts_factory.create(config.tts_model_name)
            for device in config.device_preference:
                try:
                    tts_model.to(device)
                    break
                except Exception:
                    continue
        return tts_model

    _notify(progress_callback, "rows", total=total_rows, message="Memproses baris CSV…")

    for idx, row in enumerate(rows, start=1):
        try:
            hanzi = row.get(columns["Hanzi"], "")
            if not hanzi:
                row_errors.append(f"Baris {idx}: kolom Hanzi kosong, dilewati.")
                continue

            pinyin = row.get(columns["Pinyin"], "")
            indo = row.get(columns["Indo"], "")
            literal = row.get(columns["Literal"], "")
            grammar = row.get(columns["Grammar"], "")
            audio_name = row.get(columns["Audio"], "")
            enable_rm = row.get(columns["Enable_RM"], "1") or "1"
            enable_lt = row.get(columns["Enable_LT"], "1") or "1"
            enable_mp = row.get(columns["Enable_MP"], "1") or "1"
            tags = row.get(columns["Tags"], "")
            uid = row.get(columns["UID"], "") or f"{base_name}-{idx:04d}"

            literal_br = _literal_to_br(literal, config.use_literal_linebreaks)

            if not audio_name:
                audio_name = f"{base_name.lower()}_{idx:03d}.{config.audio_format}"
            elif not audio_name.lower().endswith(f".{config.audio_format}"):
                audio_name = f"{Path(audio_name).stem}.{config.audio_format}"

            audio_path = config.output_dir / audio_name

            if config.regenerate_audio_if_exists or not audio_path.exists():
                ensure_tts()
                tmp_wav = config.output_dir / f"tts_{idx:03d}.wav"
                _render_audio(
                    tts=tts_model,
                    text=hanzi,
                    tmp_wav=tmp_wav,
                    speaker_wav=config.speaker_wav,
                    ambient_wav=config.ambient_wav,
                    config=config,
                    final_path=audio_path,
                )

            media_files.append(audio_path)
            tag_list = [t for t in (tags or "").split() if t]
            tag_list.append(timestamp_tag)

            note = genanki.Note(
                model=model,
                fields=[
                    hanzi,
                    pinyin,
                    indo,
                    literal,
                    literal_br,
                    grammar,
                    audio_name,
                    f"[sound:{audio_name}]",
                    enable_rm,
                    enable_lt,
                    enable_mp,
                    " ".join(tag_list),
                    uid,
                ],
                tags=tag_list,
            )
            deck.add_note(note)
        except Exception as exc:  # pragma: no cover - defensive, errors surfaced in UI
            row_errors.append(f"Baris {idx}: {exc}")
        finally:
            _notify(progress_callback, "row", current=idx, total=total_rows)

    if not deck.notes:
        raise DeckBuildError("Tidak ada kartu yang berhasil dibangun.", row_errors=row_errors)

    apkg_name = f"{base_name}_{timestamp_tag}.apkg"
    apkg_path = config.output_dir / apkg_name
    genanki.Package(deck, [str(p) for p in media_files]).write_to_file(apkg_path)

    _notify(progress_callback, "complete", message="Deck selesai dibangun.")

    return DeckBuildResult(
        apkg_path=apkg_path,
        media_files=media_files,
        rows_processed=len(deck.notes),
        row_errors=row_errors,
    )

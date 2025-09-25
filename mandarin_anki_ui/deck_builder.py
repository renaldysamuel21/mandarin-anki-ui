"""Utilities to build Mandarin Anki decks from CSV sources."""
from __future__ import annotations

import csv
import random
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Mapping, MutableMapping, Optional, Sequence

import genanki

from .audio_engine import AudioEngine, PydubAudioEngine

try:  # pragma: no cover - optional dependency only used at runtime
    from TTS.api import TTS  # type: ignore
except Exception:  # pragma: no cover - lazy import handled later in build_anki_deck
    TTS = None  # type: ignore


DEFAULT_COLUMNS: Mapping[str, str] = {
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


@dataclass(slots=True)
class DeckBuildConfig:
    """Configuration for building an Anki deck."""

    csv_path: Path
    output_dir: Path
    speaker_wav: Path
    tts_model_name: str
    tts_lang: str = "zh-cn"
    ffmpeg_path: Optional[Path] = None
    ambient_wav: Optional[Path] = None
    regenerate_audio_if_exists: bool = False
    delimiter: str = ";"
    encoding: str = "utf-8-sig"
    columns: Optional[Mapping[str, str]] = None
    use_literal_linebreaks: bool = True
    volume_voice_db: float = -6.0
    volume_ambient_db: float = -38.0
    bitrate_mp3: str = "192k"
    tts_device_preference: Sequence[str] = ("cuda", "cpu")


@dataclass(slots=True)
class DeckBuildResult:
    """Result metadata from :func:`build_anki_deck`."""

    apkg_path: Path
    deck_title: str
    processed_count: int
    skipped_count: int
    warnings: List[str] = field(default_factory=list)


ProgressCallback = Callable[[str, int, int], None]
TTSFactory = Callable[[str], "_TTSEngine"]


class _TTSEngine:
    """Protocol-like helper describing the minimal interface of Coqui TTS."""

    def to(self, device: str) -> "_TTSEngine":  # pragma: no cover - exercised indirectly
        raise NotImplementedError

    def tts_to_file(self, *, text: str, speaker_wav: str, language: str, file_path: Path, split_sentences: bool) -> None:
        raise NotImplementedError


def _clean(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.replace("\ufeff", "").replace("\u200b", "").strip()


def _literal_to_br(text: str, enable: bool = True) -> str:
    if not enable:
        return _clean(text)
    value = _clean(text)
    if not value:
        return ""
    value = re.sub(r"\s*[，,；;]\s*", "<br>", value)
    value = re.sub(r"(?:<br>\s*){2,}", "<br>", value).strip()
    value = re.sub(r"^(<br>)+", "", value)
    value = re.sub(r"(<br>)+$", "", value)
    return value


def _prepare_columns(config: DeckBuildConfig) -> Mapping[str, str]:
    merged: MutableMapping[str, str] = dict(DEFAULT_COLUMNS)
    if config.columns:
        merged.update({k: v for k, v in config.columns.items() if v})
    return merged


def _read_rows(config: DeckBuildConfig) -> List[Dict[str, str]]:
    with open(config.csv_path, newline="", encoding=config.encoding) as handle:
        reader = csv.DictReader(handle, delimiter=config.delimiter)
        if reader.fieldnames is None:
            raise ValueError("CSV tidak memiliki header. Minimal siapkan Hanzi,Pinyin,Indo.")
        reader.fieldnames = [_clean(name) for name in reader.fieldnames]
        rows = [{_clean(key): _clean(value) for key, value in raw.items()} for raw in reader]
    return rows


def _select_tts_device(tts: _TTSEngine, candidates: Sequence[str]) -> str:
    last_error: Optional[Exception] = None
    for device in candidates:
        try:
            tts.to(device)
            return device
        except Exception as exc:  # pragma: no cover - depends on runtime env
            last_error = exc
    if last_error is not None:
        raise RuntimeError("Tidak bisa menginisialisasi perangkat TTS") from last_error
    raise RuntimeError("Tidak ada kandidat perangkat TTS yang diberikan")


def _default_tts_factory(model_name: str) -> _TTSEngine:
    if TTS is None:  # pragma: no cover - executed only during runtime when dependency missing
        from TTS.api import TTS as _TTS  # type: ignore

        return _TTS(model_name)
    return TTS(model_name)  # type: ignore


def build_anki_deck(
    config: DeckBuildConfig,
    *,
    tts_factory: Optional[TTSFactory] = None,
    audio_engine: Optional[AudioEngine] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> DeckBuildResult:
    """Build an Anki deck from the provided :class:`DeckBuildConfig`."""

    if not config.csv_path.exists():
        raise FileNotFoundError(f"CSV tidak ditemukan: {config.csv_path}")
    if not config.speaker_wav.exists():
        raise FileNotFoundError(f"Speaker WAV tidak ditemukan: {config.speaker_wav}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    engine = audio_engine or PydubAudioEngine(config.ffmpeg_path)

    rows = _read_rows(config)
    total_rows = len(rows)
    if total_rows == 0:
        raise ValueError("CSV tidak memiliki baris data.")

    if on_progress:
        on_progress("init", 0, total_rows)

    tts_creator = tts_factory or _default_tts_factory
    tts = tts_creator(config.tts_model_name)
    try:
        _select_tts_device(tts, config.tts_device_preference)
    except RuntimeError:
        device = "cpu"  # fallback terakhir
        try:
            tts.to(device)
        except Exception as exc:  # pragma: no cover - environment specific
            raise RuntimeError("TTS tidak dapat dijalankan di CPU.") from exc

    timestamp_tag = datetime.now().strftime("deck_%Y%m%d_%H%M%S")
    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id = random.randrange(1 << 30, 1 << 31)

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

    template_reading = {
        "name": "Card 1 - Reading→Meaning",
        "qfmt": "<div class=\"hanzi\">{{Hanzi}}</div>",
        "afmt": """{{FrontSide}}<hr>
<div class=\"pinyin\">{{Pinyin}}</div>
<div class=\"indo\"><em>{{Indo}}</em></div>
<div class=\"literal\">{{LiteralBr}}</div>
<div class=\"grammar\">{{Grammar}}</div>
<div class=\"audio\">{{AudioMarkup}}</div>""",
    }

    template_listening = {
        "name": "Card 2 - Listening→Text",
        "qfmt": "<div class=\"audio\">{{AudioMarkup}}</div>",
        "afmt": """{{FrontSide}}<hr>
<div class=\"hanzi\">{{Hanzi}}</div>
<div class=\"pinyin\">{{Pinyin}}</div>
<div class=\"indo\">{{Indo}}</div>""",
    }

    template_production = {
        "name": "Card 3 - Meaning→Production",
        "qfmt": "<div class=\"indo\">{{Indo}}</div><div class=\"hint\">Hint: {{Grammar}}</div>",
        "afmt": """{{FrontSide}}<hr>
<div class=\"hanzi\">{{Hanzi}}</div>
<div class=\"pinyin\">{{Pinyin}}</div>
<div class=\"audio\">{{AudioMarkup}}</div>""",
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
        templates=[template_reading, template_listening, template_production],
        css=css,
    )

    columns = _prepare_columns(config)
    base_name = config.csv_path.stem.replace(" ", "_")
    deck_title = f"Mandarin Grammar ({base_name}) - {timestamp_tag}"
    deck = genanki.Deck(deck_id, deck_title)

    processed = 0
    skipped = 0
    warnings: List[str] = []
    media_files: List[str] = []
    ambient_path = config.ambient_wav if config.ambient_wav and config.ambient_wav.exists() else None

    for idx, row in enumerate(rows, start=1):
        if on_progress:
            on_progress("processing", idx - 1, total_rows)

        try:
            hanzi = row.get(columns["Hanzi"], "")
            if not hanzi:
                skipped += 1
                warnings.append(f"Baris {idx} dilewati karena kolom Hanzi kosong.")
                continue

            pinyin = row.get(columns["Pinyin"], "")
            indo = row.get(columns["Indo"], "")
            literal = row.get(columns["Literal"], "")
            grammar = row.get(columns["Grammar"], "")
            audio = row.get(columns["Audio"], "") or f"{base_name.lower()}_{idx:03}.mp3"
            er = row.get(columns["Enable_RM"], "1") or "1"
            el = row.get(columns["Enable_LT"], "1") or "1"
            ep = row.get(columns["Enable_MP"], "1") or "1"
            tags = row.get(columns["Tags"], "")
            uid = row.get(columns["UID"], "") or f"{base_name}-{idx:04d}"

            literal_br = _literal_to_br(literal, config.use_literal_linebreaks)
            mp3_path = config.output_dir / audio
            if config.regenerate_audio_if_exists or not mp3_path.exists():
                tmp_wav = config.output_dir / f"tts_{idx:03}.wav"
                tts.tts_to_file(
                    text=hanzi,
                    speaker_wav=str(config.speaker_wav),
                    language=config.tts_lang,
                    file_path=tmp_wav,
                    split_sentences=True,
                )
                engine.render(
                    voice_wav=tmp_wav,
                    ambient_wav=ambient_path,
                    output_mp3=mp3_path,
                    volume_voice_db=config.volume_voice_db,
                    volume_ambient_db=config.volume_ambient_db,
                    bitrate=config.bitrate_mp3,
                )
                try:
                    tmp_wav.unlink()
                except FileNotFoundError:
                    pass

            media_files.append(str(mp3_path))
            audio_markup = f"[sound:{audio}]"
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
                    audio,
                    audio_markup,
                    er,
                    el,
                    ep,
                    " ".join(tag_list),
                    uid,
                ],
                tags=tag_list,
            )
            deck.add_note(note)
            processed += 1
        except Exception as exc:
            skipped += 1
            warnings.append(f"Baris {idx} gagal diproses: {exc}")
            traceback.print_exc()

    if processed == 0:
        raise RuntimeError("Tidak ada kartu yang berhasil dibuat dari CSV yang diberikan.")

    apkg_name = f"{base_name}_{timestamp_tag}.apkg"
    apkg_path = config.output_dir / apkg_name
    package = genanki.Package(deck, media_files)
    package.write_to_file(apkg_path)

    if on_progress:
        on_progress("finalizing", total_rows, total_rows)

    return DeckBuildResult(
        apkg_path=apkg_path,
        deck_title=deck_title,
        processed_count=processed,
        skipped_count=skipped,
        warnings=warnings,
    )

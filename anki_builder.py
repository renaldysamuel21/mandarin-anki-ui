# anki_builder.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import csv, random, traceback, re
from typing import Optional, Dict, List

from pydub import AudioSegment
from TTS.api import TTS
import genanki

# ----------------------------
# Helpers
# ----------------------------
def _clean(s: Optional[str]) -> str:
    if s is None: return ""
    return s.replace("\ufeff", "").replace("\u200b", "").strip()

def _literal_to_br(text: str, enable: bool = True) -> str:
    """Ganti koma/semicolon ASCII & CJK jadi <br> (opsional)."""
    if not enable: return _clean(text)
    s = _clean(text)
    if not s: return ""
    s = re.sub(r"\s*[，,；;]\s*", "<br>", s)
    s = re.sub(r"(?:<br>\s*){2,}", "<br>", s).strip()
    s = re.sub(r"^(<br>)+", "", s)
    s = re.sub(r"(<br>)+$", "", s)
    return s

def _ensure_ffmpeg(ffmpeg_path: Optional[Path]):
    if ffmpeg_path and ffmpeg_path.exists():
        AudioSegment.converter = str(ffmpeg_path)

# ----------------------------
# Public API
# ----------------------------
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
    # mapping kolom CSV -> field
    columns: Dict[str, str] = None,
    # opsi format
    use_literal_linebreaks: bool = True,
    volume_voice_db: float = -6.0,
    volume_ambient_db: float = -38.0,
    bitrate_mp3: str = "192k",
) -> Path:
    """
    Bangun Anki deck (.apkg) dari CSV + TTS.
    Mengembalikan path .apkg yang siap diunduh.
    """
    columns = columns or {
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

    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_ffmpeg(ffmpeg_path)

    # Init TTS
    tts = TTS(tts_model_name)
    # catatan: kalau tidak ada GPU, bisa diubah "cuda" -> "cpu"
    try:
        tts.to("cuda")
    except Exception:
        tts.to("cpu")

    # IDs & timestamp
    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id  = random.randrange(1 << 30, 1 << 31)
    timestamp_tag = datetime.now().strftime("deck_%Y%m%d_%H%M%S")

    # CSS & templates (3 kartu seperti punyamu)
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
    tmpl_read = {
        'name': 'Card 1 - Reading→Meaning',
        'qfmt': """<div class="hanzi">{{Hanzi}}</div>""",
        'afmt': """{{FrontSide}}<hr>
<div class="pinyin">{{Pinyin}}</div>
<div class="indo"><em>{{Indo}}</em></div>
<div class="literal">{{LiteralBr}}</div>
<div class="grammar">{{Grammar}}</div>
<div class="audio">{{AudioMarkup}}</div>"""
    }
    tmpl_listen = {
        'name': 'Card 2 - Listening→Text',
        'qfmt': """<div class="audio">{{AudioMarkup}}</div>""",
        'afmt': """{{FrontSide}}<hr>
<div class="hanzi">{{Hanzi}}</div>
<div class="pinyin">{{Pinyin}}</div>
<div class="indo">{{Indo}}</div>"""
    }
    tmpl_prod = {
        'name': 'Card 3 - Meaning→Production',
        'qfmt': """<div class="indo">{{Indo}}</div><div class="hint">Hint: {{Grammar}}</div>""",
        'afmt': """{{FrontSide}}<hr>
<div class="hanzi">{{Hanzi}}</div>
<div class="pinyin">{{Pinyin}}</div>
<div class="audio">{{AudioMarkup}}</div>"""
    }

    model = genanki.Model(
        model_id,
        'CN Sentence (Putonghua)',
        fields=[
            {'name': 'Hanzi'},
            {'name': 'Pinyin'},
            {'name': 'Indo'},
            {'name': 'Literal'},
            {'name': 'LiteralBr'},
            {'name': 'Grammar'},
            {'name': 'Audio'},
            {'name': 'AudioMarkup'},
            {'name': 'Enable_RM'},
            {'name': 'Enable_LT'},
            {'name': 'Enable_MP'},
            {'name': 'Tags'},
            {'name': 'UID'},
        ],
        templates=[tmpl_read, tmpl_listen, tmpl_prod],
        css=css
    )

    base_name  = csv_path.stem.replace(" ", "_")
    deck_title = f"Mandarin Grammar ({base_name}) - {timestamp_tag}"
    deck       = genanki.Deck(deck_id, deck_title)
    media_files: List[str] = []

    # Baca CSV
    with open(csv_path, newline='', encoding=encoding) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        # normalisasi header
        reader.fieldnames = [_clean(fn) for fn in (reader.fieldnames or [])]
        rows = [{_clean(k): _clean(v) for k, v in raw.items()} for raw in reader]

    # Safety
    if not Path(speaker_wav).exists():
        raise FileNotFoundError(f"Speaker WAV tidak ditemukan: {speaker_wav}")

    # Proses baris
    for idx, row in enumerate(rows, start=1):
        try:
            hanzi   = row.get(columns["Hanzi"], '')
            pinyin  = row.get(columns["Pinyin"], '')
            indo    = row.get(columns["Indo"], '')
            literal = row.get(columns["Literal"], '')
            grammar = row.get(columns["Grammar"], '')
            audio   = row.get(columns["Audio"], '') or f"{base_name.lower()}_{idx:03}.mp3"
            er      = row.get(columns["Enable_RM"], '1') or '1'
            el      = row.get(columns["Enable_LT"], '1') or '1'
            ep      = row.get(columns["Enable_MP"], '1') or '1'
            tags    = row.get(columns["Tags"], '')
            uid     = row.get(columns["UID"], '') or f"{base_name}-{idx:04d}"

            if not hanzi:
                print(f"⚠️ Skip baris {idx}: kolom 'Hanzi' kosong.")
                continue

            literal_br = _literal_to_br(literal, enable=use_literal_linebreaks)
            mp3_path = output_dir / audio

            # TTS jika belum ada / force regen
            if regenerate_audio_if_exists or not mp3_path.exists():
                tmp_wav = output_dir / f"tts_{idx:03}.wav"
                tts.tts_to_file(
                    text=hanzi,
                    speaker_wav=str(speaker_wav),
                    language=tts_lang,
                    file_path=tmp_wav,
                    split_sentences=True,
                )
                voice = AudioSegment.from_wav(tmp_wav) + volume_voice_db  # volume_voice_db negatif = turunkan
                if ambient_wav and Path(ambient_wav).exists():
                    ambient = AudioSegment.from_wav(ambient_wav)
                    while len(ambient) < len(voice):
                        ambient += ambient
                    ambient = ambient[:len(voice)] + volume_ambient_db
                    final_audio = voice.overlay(ambient)
                else:
                    final_audio = voice
                final_audio.export(mp3_path, format="mp3", bitrate=bitrate_mp3)
                try: tmp_wav.unlink(missing_ok=True)
                except Exception: pass

            media_files.append(str(mp3_path))
            audio_markup = f"[sound:{audio}]"
            tag_list = [t for t in (tags or "").split() if t] + [timestamp_tag]

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
                    er, el, ep,
                    " ".join(tag_list),
                    uid
                ],
                tags=tag_list
            )
            deck.add_note(note)
        except Exception as e:
            print(f"❌ Gagal proses baris {idx}: {e}")
            traceback.print_exc()

    apkg_name = f"{base_name}_{timestamp_tag}.apkg"
    apkg_path = output_dir / apkg_name
    genanki.Package(deck, media_files).write_to_file(apkg_path)
    return apkg_path

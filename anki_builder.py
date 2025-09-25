import csv
import random
from pathlib import Path
from datetime import datetime
from pydub import AudioSegment
from TTS.api import TTS
import genanki
import traceback
import re

# ---------- Paths & Config ----------
FFMPEG_PATH  = Path(r"S:/ffmpeg/bin/ffmpeg.exe")   # <- ubah jika perlu
CSV_PATH     = Path("HSK1 Advanced1.csv")           # <- CSV (delimiter ; )
OUTPUT_DIR   = Path("anki_output")
OUTPUT_DIR.mkdir(exist_ok=True)

LANG         = "zh-cn"
MODEL_NAME   = "tts_models/multilingual/multi-dataset/xtts_v2"
SPEAKER_WAV  = Path("vocal serena1.wav")           # <- pastikan ada
ROOM_AMBIENT = Path("room.wav")                    # <- opsional

REGENERATE_AUDIO_IF_EXISTS = False

# Set ffmpeg untuk pydub
if FFMPEG_PATH.exists():
    AudioSegment.converter = str(FFMPEG_PATH)
else:
    print(f"⚠️ FFmpeg path tidak ditemukan: {FFMPEG_PATH}. Pastikan ffmpeg ada di PATH.")

def clean(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\ufeff", "").replace("\u200b", "").strip()

def literal_to_br(text: str) -> str:
    """
    Ubah pemisah (koma/semicolon ASCII & CJK) menjadi <br>.
    Tidak mengubah isi; pinyin di dalam kurung tetap tampil.
    """
    s = clean(text)
    if not s:
        return ""
    # Ganti semua variasi koma/semicolon dengan <br>
    s = re.sub(r"\s*[，,；;]\s*", "<br>", s)
    # Rapikan: hapus <br> ganda dan trim di awal/akhir
    s = re.sub(r"(?:<br>\s*){2,}", "<br>", s).strip()
    s = re.sub(r"^(<br>)+", "", s)
    s = re.sub(r"(<br>)+$", "", s)
    return s

def ensure_speaker():
    if not SPEAKER_WAV.exists():
        raise FileNotFoundError(f"Speaker WAV tidak ditemukan: {SPEAKER_WAV.resolve()}")

print("🔊 Init XTTS…")
tts = TTS(MODEL_NAME)
tts.to("cuda")

model_id = random.randrange(1 << 30, 1 << 31)
deck_id  = random.randrange(1 << 30, 1 << 31)
timestamp_tag = datetime.now().strftime("deck1_%Y%m%d_%H%M%S")

# ---------- Note Type (3 kartu) ----------
css = """
.card { font-family: system-ui, 'Noto Sans CJK SC', 'PingFang SC', sans-serif; background:#fff; color:#000; }
.hanzi { font-size: 28px; line-height: 1.35; margin: 8px 0; }
.pinyin { margin: 6px 0; }
.indo { margin: 4px 0; }
.literal { margin-top: 8px; line-height: 1.4; }
.grammar { margin-top: 10px; opacity: 0.9; }
.hint { margin: 4px 0; }
.audio { margin-top: 10px; }
"""

# Card 1: Reading → Meaning (sesuai contohmu)
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

# Card 2: Listening → Text
tmpl_listen = {
    'name': 'Card 2 - Listening→Text',
    'qfmt': """<div class="audio">{{AudioMarkup}}</div>""",
    'afmt': """{{FrontSide}}<hr>
<div class="hanzi">{{Hanzi}}</div>
<div class="pinyin">{{Pinyin}}</div>
<div class="indo">{{Indo}}</div>"""
}

# Card 3: Meaning → Production
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
        {'name': 'Literal'},      # original dari CSV
        {'name': 'LiteralBr'},    # versi HTML: koma -> <br>
        {'name': 'Grammar'},
        {'name': 'Audio'},        # nama file mp3 (tanpa path)
        {'name': 'AudioMarkup'},  # [sound:xxx.mp3] => pasti tampil player
        {'name': 'Enable_RM'},
        {'name': 'Enable_LT'},
        {'name': 'Enable_MP'},
        {'name': 'Tags'},
        {'name': 'UID'},
    ],
    templates=[tmpl_read, tmpl_listen, tmpl_prod],
    css=css
)

base_name  = CSV_PATH.stem.replace(" ", "_")
deck_title = f"Mandarin Grammar ({base_name}) - {timestamp_tag}"
deck       = genanki.Deck(deck_id, deck_title)
media_files = []

print(f"📥 Baca CSV: {CSV_PATH}")
with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f, delimiter=';')
    reader.fieldnames = [clean(fn) for fn in (reader.fieldnames or [])]
    rows = [{clean(k): clean(v) for k, v in raw.items()} for raw in reader]

ensure_speaker()

for idx, row in enumerate(rows, start=1):
    try:
        hanzi   = row.get('Hanzi', '')
        pinyin  = row.get('Pinyin', '')
        indo    = row.get('Indo', '')
        literal = row.get('Literal', '')
        grammar = row.get('Grammar', '')
        audio   = row.get('Audio', '')   # boleh kosong
        er      = row.get('Enable_RM', '1') or '1'
        el      = row.get('Enable_LT', '1') or '1'
        ep      = row.get('Enable_MP', '1') or '1'
        tags    = row.get('Tags', '')
        uid     = row.get('UID', '')

        if not hanzi:
            print(f"⚠️ Skip baris {idx}: kolom 'Hanzi' kosong.")
            continue

        # Auto-nama audio & UID bila kosong
        if not audio:
            audio = f"{base_name.lower()}_{idx:03}.mp3"
        if not uid:
            uid = f"{base_name}-{idx:04d}"

        literal_br = literal_to_br(literal)

        mp3_path = OUTPUT_DIR / audio

        # Generate audio bila belum ada (atau force regen)
        if REGENERATE_AUDIO_IF_EXISTS or not mp3_path.exists():
            print(f"🎙️  TTS [{idx:02d}] {hanzi} -> {audio}")
            temp_wav = OUTPUT_DIR / f"tts_{idx:03}.wav"
            tts.tts_to_file(
                text=hanzi,
                speaker_wav=str(SPEAKER_WAV),
                language=LANG,
                file_path=temp_wav,
                split_sentences=True,
            )
            voice = AudioSegment.from_wav(temp_wav)
            voice = voice - 6  # sedikit diturunkan volumenya
            if ROOM_AMBIENT.exists():
                ambient = AudioSegment.from_wav(ROOM_AMBIENT)
                while len(ambient) < len(voice):
                    ambient += ambient
                ambient = ambient[:len(voice)] - 38
                final_audio = voice.overlay(ambient)
            else:
                final_audio = voice
            final_audio.export(mp3_path, format="mp3", bitrate="192k")
            try:
                temp_wav.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            print(f"✅ Audio sudah ada: {audio}")

        media_files.append(str(mp3_path))

        # Siapkan tag & note (AudioMarkup = [sound:xxx.mp3])
        audio_markup = f"[sound:{audio}]"
        tag_list = [t for t in tags.split() if t] + [timestamp_tag]

        note = genanki.Note(
            model=model,
            fields=[
                hanzi,          # Hanzi
                pinyin,         # Pinyin
                indo,           # Indo
                literal,        # Literal (asli)
                literal_br,     # LiteralBr (koma -> <br>)
                grammar,        # Grammar
                audio,          # Audio (nama file)
                audio_markup,   # AudioMarkup
                er, el, ep,     # Enable_RM, Enable_LT, Enable_MP
                " ".join(tag_list),  # Tags (string)
                uid             # UID
            ],
            tags=tag_list
        )
        deck.add_note(note)

    except Exception as e:
        print(f"❌ Gagal proses baris {idx}: {e}")
        traceback.print_exc()

apkg_name = f"{base_name}_{timestamp_tag}.apkg"
print(f"📦 Bundle APKG: {apkg_name} (media: {len(media_files)})")
genanki.Package(deck, media_files).write_to_file(apkg_name)
print("✅ Selesai. Import .apkg ini ke Anki (audio ter-bundle & player tampil).")

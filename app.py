# app.py
import streamlit as st
from pathlib import Path
import tempfile

from anki_builder import build_anki_deck

st.set_page_config(page_title="Mandarin → Anki Builder", page_icon="🀄", layout="wide")

# --- theme / CSS sederhana ala SD ---
st.markdown("""
<style>
:root { --bg:#0b0b0e; --panel:#15151c; --accent:#6ee7b7; --muted:#9aa3ad; --text:#eaeaf0; }
html, body, [class^="css"]  { background-color: var(--bg) !important; color: var(--text) !important; }
section.main > div { padding-top: 1rem; }
.sidebar .sidebar-content { background: var(--panel) !important; }
.block-container { padding-top: 1rem; }
div.stButton>button { background: var(--panel); border:1px solid #2a2a34; color:var(--text); border-radius:12px; padding:0.6rem 1rem; }
div.stDownloadButton>button { background: var(--accent); color:#0b0b0e; font-weight:700; border-radius:12px; }
hr { border: 0; border-top:1px solid #2a2a34; }
.small { color: var(--muted); font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

st.title("🀄 Mandarin → Anki Deck Builder")
st.caption("Upload CSV & audio, atur parameter, lalu hasilkan .apkg siap import ke Anki.")

# ---------- Sidebar: Parameter ----------
with st.sidebar:
    st.header("⚙️ Settings")

    # Lokasi default file di project root (optional)
    project_root = Path(".").resolve()
    default_speaker = project_root / "vocal_serena1.wav"
    default_ambient = project_root / "room.wav"
    default_ffmpeg = Path(r"S:/ffmpeg/bin/ffmpeg.exe")

    ffmpeg_path = st.text_input("FFmpeg Path", str(default_ffmpeg))
    tts_model   = st.text_input("TTS Model", "tts_models/multilingual/multi-dataset/xtts_v2")
    tts_lang    = st.text_input("Bahasa TTS", "zh-cn")

    st.markdown("---")
    st.subheader("🔊 Audio")
    regen = st.checkbox("Regenerate audio jika file mp3 sudah ada", False)
    voice_db = st.slider("Volume voice (dB, negatif lebih pelan)", -24, 6, -6)
    amb_db   = st.slider("Volume ambient (dB, negatif lebih pelan)", -60, 0, -38)

    st.markdown("---")
    st.subheader("🧾 Parsing CSV")
    delimiter = st.selectbox("Delimiter", [";", ",", "\\t"], index=0)
    if delimiter == "\\t": delimiter = "\t"
    encoding  = st.selectbox("Encoding", ["utf-8-sig", "utf-8", "cp936", "cp950"], index=0)
    literal_br = st.checkbox("Literal → <br> (pisahkan dengan koma/semicolon)", True)

    st.markdown("---")
    st.subheader("🗂️ Mapping Kolom")
    # nama default sesuai skrip
    col_hanzi   = st.text_input("Kolom Hanzi", "Hanzi")
    col_pinyin  = st.text_input("Kolom Pinyin", "Pinyin")
    col_indo    = st.text_input("Kolom Indo", "Indo")
    col_literal = st.text_input("Kolom Literal", "Literal")
    col_grammar = st.text_input("Kolom Grammar", "Grammar")
    col_audio   = st.text_input("Kolom Audio (opsional)", "Audio")
    col_rm      = st.text_input("Kolom Enable_RM", "Enable_RM")
    col_lt      = st.text_input("Kolom Enable_LT", "Enable_LT")
    col_mp      = st.text_input("Kolom Enable_MP", "Enable_MP")
    col_tags    = st.text_input("Kolom Tags", "Tags")
    col_uid     = st.text_input("Kolom UID", "UID")

# ---------- Main: Uploads ----------
left, right = st.columns([2,1])

with left:
    st.subheader("📥 Upload")
    csv_file     = st.file_uploader("CSV (delimiter sesuai pilihan)", type=["csv", "txt"])
    speaker_file = st.file_uploader("Speaker WAV (opsional jika ada default)", type=["wav"])
    ambient_file = st.file_uploader("Ambient WAV (opsional)", type=["wav"])

    st.markdown("<span class='small'>Jika tidak upload speaker/ambient, app akan mencoba memakai file default di folder proyek.</span>", unsafe_allow_html=True)

with right:
    st.subheader("📦 Output")
    out_dir = st.text_input("Output folder", "anki_output")
    bitrate = st.selectbox("MP3 bitrate", ["128k", "160k", "192k", "256k"], index=2)

st.markdown("---")

# ---------- Action ----------
generate = st.button("🚀 Generate Deck")

if generate:
    if not csv_file:
        st.warning("CSV wajib diunggah.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Simpan CSV upload
            csv_path = tmp / "input.csv"
            csv_path.write_bytes(csv_file.read())

            # Tentukan speaker & ambient
            if speaker_file:
                spk_path = tmp / "speaker.wav"
                spk_path.write_bytes(speaker_file.read())
            else:
                spk_path = default_speaker

            amb_path = None
            if ambient_file:
                amb_path = tmp / "ambient.wav"
                amb_path.write_bytes(ambient_file.read())
            elif default_ambient.exists():
                amb_path = default_ambient

            # Validasi speaker
            if not Path(spk_path).exists():
                st.error("Speaker WAV tidak ditemukan (upload atau letakkan 'vocal_serena1.wav' di root proyek).")
            else:
                try:
                    st.info("Memproses… ini bisa memakan waktu tergantung panjang CSV & TTS.")
                    apkg = build_anki_deck(
                        csv_path=csv_path,
                        output_dir=Path(out_dir),
                        ffmpeg_path=Path(ffmpeg_path) if ffmpeg_path else None,
                        tts_model_name=tts_model,
                        tts_lang=tts_lang,
                        speaker_wav=Path(spk_path),
                        ambient_wav=Path(amb_path) if amb_path else None,
                        regenerate_audio_if_exists=regen,
                        delimiter=delimiter,
                        encoding=encoding,
                        columns={
                            "Hanzi": col_hanzi,
                            "Pinyin": col_pinyin,
                            "Indo": col_indo,
                            "Literal": col_literal,
                            "Grammar": col_grammar,
                            "Audio": col_audio,
                            "Enable_RM": col_rm,
                            "Enable_LT": col_lt,
                            "Enable_MP": col_mp,
                            "Tags": col_tags,
                            "UID": col_uid,
                        },
                        use_literal_linebreaks=literal_br,
                        volume_voice_db=voice_db,
                        volume_ambient_db=amb_db,
                        bitrate_mp3=bitrate,
                    )
                    st.success("Selesai! Deck siap diunduh.")
                    st.download_button("⬇️ Download .apkg", apkg.read_bytes(), file_name=apkg.name)
                except Exception as e:
                    st.error(f"Gagal: {e}")

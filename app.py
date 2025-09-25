"""Streamlit UI for the Mandarin → Anki deck builder."""
from __future__ import annotations

from pathlib import Path
import tempfile
import traceback
from typing import Optional

import streamlit as st

from mandarin_anki import (
    DeckBuildConfig,
    DeckBuildError,
    DeckBuildResult,
    build_anki_deck,
    ProgressEvent,
)

st.set_page_config(page_title="Mandarin → Anki Builder", page_icon="🀄", layout="wide")

st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)

st.title("🀄 Mandarin → Anki Deck Builder")
st.caption("Upload CSV & audio, atur parameter, lalu hasilkan .apkg siap import ke Anki.")

project_root = Path(".").resolve()
default_speaker = project_root / "vocal_serena1.wav"
default_ambient = project_root / "room.wav"

def _resolve_default_audio(label: str, default_path: Path) -> None:
    if not default_path.exists():
        st.sidebar.warning(f"Letakkan file default {label} di: {default_path}")


def _format_delimiter(label: str) -> str:
    return "\t" if label == "\\t" else label


with st.sidebar:
    st.header("⚙️ Settings")

    ffmpeg_path_text = st.text_input("FFmpeg Path (opsional)", "")
    tts_model = st.text_input("TTS Model", "tts_models/multilingual/multi-dataset/xtts_v2")
    tts_lang = st.text_input("Bahasa TTS", "zh-cn")

    st.markdown("---")
    st.subheader("🔊 Audio")
    regenerate = st.checkbox("Regenerate audio jika file sudah ada", False)
    voice_db = st.slider("Volume voice (dB, negatif lebih pelan)", -24, 6, -6)
    ambient_db = st.slider("Volume ambient (dB, negatif lebih pelan)", -60, 0, -38)

    st.markdown("---")
    st.subheader("🧾 Parsing CSV")
    delimiter_label = st.selectbox("Delimiter", [";", ",", "\\t"], index=0)
    encoding = st.selectbox("Encoding", ["utf-8-sig", "utf-8", "cp936", "cp950"], index=0)
    literal_br = st.checkbox("Literal → <br> (pisahkan dengan koma/semicolon)", True)

    st.markdown("---")
    st.subheader("🗂️ Mapping Kolom")
    col_hanzi = st.text_input("Kolom Hanzi", "Hanzi")
    col_pinyin = st.text_input("Kolom Pinyin", "Pinyin")
    col_indo = st.text_input("Kolom Indo", "Indo")
    col_literal = st.text_input("Kolom Literal", "Literal")
    col_grammar = st.text_input("Kolom Grammar", "Grammar")
    col_audio = st.text_input("Kolom Audio (opsional)", "Audio")
    col_rm = st.text_input("Kolom Enable_RM", "Enable_RM")
    col_lt = st.text_input("Kolom Enable_LT", "Enable_LT")
    col_mp = st.text_input("Kolom Enable_MP", "Enable_MP")
    col_tags = st.text_input("Kolom Tags", "Tags")
    col_uid = st.text_input("Kolom UID", "UID")

    _resolve_default_audio("speaker (vocal_serena1.wav)", default_speaker)
    _resolve_default_audio("ambient (room.wav)", default_ambient)

left, right = st.columns([2, 1])

with left:
    st.subheader("📥 Upload")
    csv_file = st.file_uploader("CSV (delimiter sesuai pilihan)", type=["csv", "txt"])
    speaker_file = st.file_uploader("Speaker WAV (opsional)", type=["wav"])
    ambient_file = st.file_uploader("Ambient WAV (opsional)", type=["wav"])

    st.markdown(
        "<span class='small'>Jika tidak upload speaker/ambient, app memakai default di folder proyek.</span>",
        unsafe_allow_html=True,
    )

with right:
    st.subheader("📦 Output")
    output_dir_text = st.text_input("Output folder", "anki_output")
    bitrate = st.selectbox("Audio bitrate", ["128k", "160k", "192k", "256k"], index=2)
    audio_format = st.selectbox("Format audio", ["mp3", "wav"], index=0)

st.markdown("---")

def _progress_callback_factory(status, progress_bar):
    def _on_progress(event: ProgressEvent) -> None:
        if event.message:
            status.write(event.message)

        if event.stage == "row" and event.total:
            percent = min(100, int(event.current / event.total * 100))
            progress_bar.progress(percent, text=f"Memproses kartu {event.current}/{event.total}")
        elif event.stage == "complete":
            progress_bar.progress(100, text="Deck selesai dibangun")
        elif event.stage == "init":
            progress_bar.progress(0, text=event.message or "Menyiapkan…")

    return _on_progress


def _prepare_audio_file(upload, tmp_dir: Path, filename: str, fallback: Path) -> Path:
    if upload is not None:
        path = tmp_dir / filename
        path.write_bytes(upload.read())
        return path
    return fallback


def _handle_generation(tmp_dir: Path) -> Optional[DeckBuildResult]:
    csv_path = tmp_dir / "input.csv"
    csv_path.write_bytes(csv_file.read())

    speaker_path = _prepare_audio_file(speaker_file, tmp_dir, "speaker.wav", default_speaker)
    ambient_path = None
    if ambient_file:
        ambient_path = _prepare_audio_file(ambient_file, tmp_dir, "ambient.wav", default_ambient)
    elif default_ambient.exists():
        ambient_path = default_ambient

    if not speaker_path.exists():
        st.error("Speaker WAV tidak ditemukan (upload atau letakkan 'vocal_serena1.wav' di root proyek).")
        return None

    ffmpeg_text = ffmpeg_path_text.strip()
    if ffmpeg_text.startswith('"') and ffmpeg_text.endswith('"'):
        ffmpeg_text = ffmpeg_text[1:-1]
    ffmpeg_path = Path(ffmpeg_text).expanduser() if ffmpeg_text else None
    out_dir = Path(output_dir_text).expanduser()

    with st.status("Menyiapkan…", expanded=True) as status:
        progress_bar = st.progress(0, text="Menyiapkan…")
        try:
            result = build_anki_deck(
                DeckBuildConfig(
                    csv_path=csv_path,
                    output_dir=out_dir,
                    ffmpeg_path=ffmpeg_path,
                    tts_model_name=tts_model,
                    tts_lang=tts_lang,
                    speaker_wav=speaker_path,
                    ambient_wav=ambient_path,
                    regenerate_audio_if_exists=regenerate,
                    delimiter=_format_delimiter(delimiter_label),
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
                    volume_ambient_db=ambient_db,
                    bitrate=bitrate,
                    audio_format=audio_format,
                ),
                progress_callback=_progress_callback_factory(status, progress_bar),
            )
        except DeckBuildError as exc:
            progress_bar.progress(0, text="Gagal")
            status.error(str(exc))
            if exc.row_errors:
                with st.expander("Detail galat per baris"):
                    st.write("\n".join(exc.row_errors))
            return None
        except Exception as exc:  # pragma: no cover - defensive against unexpected issues
            progress_bar.progress(0, text="Gagal")
            status.error(f"Gagal: {exc}")
            status.write("""<pre style='white-space:pre-wrap;'>""" + traceback.format_exc() + "</pre>", unsafe_allow_html=True)
            st.toast("Terjadi error saat membangun deck.", icon="⚠️")
            return None
        else:
            status.success("Deck selesai dibangun.")
            return result


if st.button("🚀 Generate Deck", type="primary"):
    if not csv_file:
        st.warning("CSV wajib diunggah.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _handle_generation(Path(tmpdir))

        if result:
            st.success(f"Selesai! {result.rows_processed} kartu berhasil dibuat.")
            if result.row_errors:
                st.warning(f"Ada {len(result.row_errors)} baris dilewati.")
                with st.expander("Lihat detail baris yang dilewati"):
                    st.write("\n".join(result.row_errors))

            data = result.apkg_path.read_bytes()
            st.download_button(
                "⬇️ Download .apkg",
                data,
                file_name=result.apkg_path.name,
                mime="application/vnd.anki",
            )

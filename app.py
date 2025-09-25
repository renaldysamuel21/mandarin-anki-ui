"""Streamlit UI for Mandarin Anki deck generation."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st

from mandarin_anki_ui import DeckBuildConfig, build_anki_deck

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_SPEAKER = ROOT_DIR / "vocal_serena1.wav"
DEFAULT_AMBIENT = ROOT_DIR / "room.wav"
DEFAULT_TTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_TTS_LANG = "zh-cn"


def _persist_uploaded_file(upload, directory: Path, fallback: Optional[Path]) -> Optional[Path]:
    if upload is None:
        return fallback if fallback and fallback.exists() else None
    file_path = directory / upload.name
    file_path.write_bytes(upload.getbuffer())
    return file_path


def _create_progress_handler(progress_bar, status_placeholder):
    stage_labels = {
        "init": "Menyiapkan model TTS",
        "processing": "Membangun kartu",
        "finalizing": "Mengemas deck",
    }

    def _handler(stage: str, current: int, total: int) -> None:
        label = stage_labels.get(stage, stage.title())
        if total > 0:
            value = min(1.0, current / total)
        else:
            value = 0.0
        progress_bar.progress(value, text=f"{label} ({current}/{total})")
        status_placeholder.markdown(f"**{label}** — {current}/{total} kartu")

    return _handler


def main() -> None:
    st.set_page_config(page_title="Mandarin Anki Builder", page_icon="🀄", layout="wide")
    st.title("🀄 Mandarin Anki Deck Builder")
    st.write(
        "Bangun deck Anki dari CSV berbahasa Mandarin lengkap dengan audio TTS."
        " Pastikan CSV minimal memiliki kolom `Hanzi`, `Pinyin`, dan `Indo`."
    )

    with st.expander("Contoh CSV minimal"):
        st.code("Hanzi;Pinyin;Indo\n你好;ni hao;Halo\n谢谢;xie xie;Terima kasih\n", language="csv")

    csv_file = st.file_uploader("Upload CSV", type=["csv"])  # type: ignore[arg-type]
    speaker_upload = st.file_uploader("Upload voice clone (WAV, opsional)", type=["wav"], key="speaker")
    ambient_upload = st.file_uploader("Upload ambience (WAV, opsional)", type=["wav"], key="ambient")

    st.caption(
        "Jika tidak mengunggah file, aplikasi akan memakai `vocal_serena1.wav`"
        " dan `room.wav` bawaan repositori."
    )

    cols = st.columns(2)
    with cols[0]:
        tts_model = st.text_input("Model TTS", value=DEFAULT_TTS_MODEL)
        tts_lang = st.text_input("Kode bahasa TTS", value=DEFAULT_TTS_LANG)
        regenerate = st.toggle("Force regen audio (tulis ulang MP3 meski sudah ada)", value=False)
    with cols[1]:
        ffmpeg_path_str = st.text_input("Path FFmpeg (opsional, contoh: C:/ffmpeg/bin/ffmpeg.exe)")
        volume_voice = st.slider("Volume suara (dB)", min_value=-24.0, max_value=6.0, value=-6.0, step=0.5)
        volume_ambient = st.slider("Volume ambience (dB)", min_value=-60.0, max_value=0.0, value=-38.0, step=1.0)

    progress_bar = st.progress(0.0, text="Menunggu input...")
    status_placeholder = st.empty()

    if st.button("Bangun deck", type="primary"):
        if csv_file is None:
            st.error("Harap unggah file CSV terlebih dahulu.")
            return

        ffmpeg_path = Path(ffmpeg_path_str).expanduser() if ffmpeg_path_str.strip() else None

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = tmp_path / csv_file.name
            csv_path.write_bytes(csv_file.getbuffer())

            speaker_path = _persist_uploaded_file(speaker_upload, tmp_path, DEFAULT_SPEAKER)
            ambient_path = _persist_uploaded_file(ambient_upload, tmp_path, DEFAULT_AMBIENT)

            if speaker_path is None:
                st.error("File speaker WAV bawaan tidak ditemukan. Pastikan `vocal_serena1.wav` ada.")
                return

            progress_handler = _create_progress_handler(progress_bar, status_placeholder)

            try:
                result = build_anki_deck(
                    DeckBuildConfig(
                        csv_path=csv_path,
                        output_dir=tmp_path,
                        speaker_wav=speaker_path,
                        tts_model_name=tts_model,
                        tts_lang=tts_lang,
                        ffmpeg_path=ffmpeg_path,
                        ambient_wav=ambient_path,
                        regenerate_audio_if_exists=regenerate,
                        volume_voice_db=volume_voice,
                        volume_ambient_db=volume_ambient,
                    ),
                    on_progress=progress_handler,
                )
            except Exception as exc:
                progress_bar.progress(0.0, text="Terjadi kesalahan")
                status_placeholder.error("Gagal membangun deck.")
                st.error(str(exc))
                st.exception(exc)
                return

            progress_bar.progress(1.0, text="Selesai!")
            status_placeholder.success(
                f"Berhasil membuat {result.processed_count} kartu (lewat: {result.skipped_count})."
            )
            deck_bytes = result.apkg_path.read_bytes()
            st.download_button(
                "Unduh deck .apkg",
                data=deck_bytes,
                file_name=result.apkg_path.name,
                mime="application/vnd.anki",
            )
            if result.warnings:
                with st.expander("Peringatan selama build"):
                    for warning in result.warnings:
                        st.write(f"- {warning}")
            st.toast("Deck siap diunduh!", icon="✅")


if __name__ == "__main__":
    main()

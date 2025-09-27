"""Streamlit UI for the Mandarin → Anki deck builder."""
from __future__ import annotations

import csv
import html
import hashlib
from dataclasses import dataclass
import io
from pathlib import Path
import tempfile
import traceback
from typing import Dict, List, Optional, Tuple
import re

import streamlit as st

from mandarin_anki import (
    AudioGenerationConfig,
    DeckBuildConfig,
    DeckBuildError,
    DeckBuildResult,
    ProgressEvent,
    build_anki_deck,
    generate_audio_from_text,
)
from mandarin_anki.anki_preview import (
    ApkgPreview,
    ApkgPreviewError,
    PreviewCard,
    load_apkg_preview,
    render_template as render_anki_template,
    wrap_card_html,
)
from mandarin_anki.builder import DEFAULT_COLUMNS

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

st.title("🀄 Mandarin → Anki Deck Builder v2.0")
st.caption("Bangun deck Anki dari CSV atau buat audio Hanzi instan dalam satu aplikasi.")

project_root = Path(".").resolve()
default_speaker = project_root / "vocal_serena1.wav"
default_ambient = project_root / "room.wav"

DECK_CARD_CSS = """
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

BUILDER_TEMPLATES = [
    {
        "name": "Card 1 - Reading→Meaning",
        "qfmt": """<div class=\"hanzi\">{{Hanzi}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"pinyin\">{{Pinyin}}</div><div class=\"indo\"><em>{{Indo}}</em></div><div class=\"literal\">{{LiteralBr}}</div><div class=\"grammar\">{{Grammar}}</div><div class=\"audio\">{{AudioMarkup}}</div>""",
    },
    {
        "name": "Card 2 - Listening→Text",
        "qfmt": """<div class=\"audio\">{{AudioMarkup}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"hanzi\">{{Hanzi}}</div><div class=\"pinyin\">{{Pinyin}}</div><div class=\"indo\">{{Indo}}</div>""",
    },
    {
        "name": "Card 3 - Meaning→Production",
        "qfmt": """<div class=\"indo\">{{Indo}}</div><div class=\"hint\">Hint: {{Grammar}}</div>""",
        "afmt": """{{FrontSide}}<hr><div class=\"hanzi\">{{Hanzi}}</div><div class=\"pinyin\">{{Pinyin}}</div><div class=\"audio\">{{AudioMarkup}}</div>""",
    },
]

AUDIO_PLACEHOLDER_TEMPLATE = (
    "<span class='preview-placeholder'>Audio {name} akan dibuat saat ekspor deck.</span>"
)

# Placeholder to satisfy type checkers; actual value diberikan oleh uploader Streamlit di tab deck.
deck_speaker_file = None


@dataclass(frozen=True)
class BuilderPreviewCard:
    name: str
    front: str
    back: str


@dataclass(frozen=True)
class BuilderPreviewRow:
    index: int
    uid: str
    cards: List[BuilderPreviewCard]

def _resolve_default_audio(label: str, default_path: Path) -> None:
    if not default_path.exists():
        st.sidebar.warning(f"Letakkan file default {label} di: {default_path}")


def _clean_cell(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.replace("\ufeff", "").replace("\u200b", "").strip()


def _literal_preview(text: str, enable: bool) -> str:
    if not enable:
        return _clean_cell(text)

    s = _clean_cell(text)
    if not s:
        return ""

    s = re.sub(r"\s*[，,；;]\s*", "<br>", s)
    s = re.sub(r"(?:<br>\s*){2,}", "<br>", s).strip()
    s = re.sub(r"^(<br>)+", "", s)
    s = re.sub(r"(<br>)+$", "", s)
    return s


def _resolve_columns_mapping(overrides: Dict[str, str]) -> Dict[str, str]:
    mapping = dict(DEFAULT_COLUMNS)
    mapping.update({k: v for k, v in (overrides or {}).items() if v})
    return mapping


def _render_builder_cards(fields: Dict[str, str]) -> List[BuilderPreviewCard]:
    cards: List[BuilderPreviewCard] = []
    for template in BUILDER_TEMPLATES:
        front = render_anki_template(template["qfmt"], fields, media_map={})
        back = render_anki_template(
            template["afmt"], fields, media_map={}, front_side=front
        )
        cards.append(BuilderPreviewCard(name=template["name"], front=front, back=back))
    return cards


def _build_csv_preview_rows(
    csv_bytes: bytes,
    *,
    csv_name: str,
    delimiter: str,
    encoding: str,
    columns: Dict[str, str],
    literal_linebreaks: bool,
    audio_format: str,
    limit: int = 10,
) -> Tuple[List[BuilderPreviewRow], List[str]]:
    text = csv_bytes.decode(encoding)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = [_clean_cell(name) for name in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames

    base_name = Path(csv_name or "input.csv").stem.replace(" ", "_") or "deck"

    rows: List[BuilderPreviewRow] = []
    errors: List[str] = []
    for idx, raw in enumerate(reader, start=1):
        if len(rows) >= limit:
            break

        clean_row = {_clean_cell(k): _clean_cell(v) for k, v in raw.items()}
        hanzi = clean_row.get(columns["Hanzi"], "")
        if not hanzi:
            errors.append(
                f"Baris {idx}: kolom Hanzi kosong, kartu akan dilewati saat build."
            )

        pinyin = clean_row.get(columns["Pinyin"], "")
        indo = clean_row.get(columns["Indo"], "")
        literal = clean_row.get(columns["Literal"], "")
        grammar = clean_row.get(columns["Grammar"], "")
        audio_name = clean_row.get(columns["Audio"], "")
        enable_rm = clean_row.get(columns["Enable_RM"], "1") or "1"
        enable_lt = clean_row.get(columns["Enable_LT"], "1") or "1"
        enable_mp = clean_row.get(columns["Enable_MP"], "1") or "1"
        tags = clean_row.get(columns["Tags"], "")
        uid = clean_row.get(columns["UID"], "") or f"{base_name}-{idx:04d}"

        literal_br = _literal_preview(literal, literal_linebreaks)

        if not audio_name:
            audio_name = f"{base_name.lower()}_{idx:03d}.{audio_format}"
        elif not audio_name.lower().endswith(f".{audio_format}"):
            audio_name = f"{Path(audio_name).stem}.{audio_format}"

        placeholder = AUDIO_PLACEHOLDER_TEMPLATE.format(name=html.escape(audio_name))

        fields = {
            "Hanzi": hanzi,
            "Pinyin": pinyin,
            "Indo": indo,
            "Literal": literal,
            "LiteralBr": literal_br,
            "Grammar": grammar,
            "Audio": audio_name,
            "AudioMarkup": placeholder,
            "Enable_RM": enable_rm,
            "Enable_LT": enable_lt,
            "Enable_MP": enable_mp,
            "Tags": tags,
            "UID": uid,
        }

        cards = _render_builder_cards(fields)
        rows.append(BuilderPreviewRow(index=idx, uid=uid, cards=cards))

    return rows, errors


def _render_csv_preview_html(rows: List[BuilderPreviewRow]) -> str:
    row_blocks = []
    for row in rows:
        cards_html = []
        for card in row.cards:
            cards_html.append(
                """
                <div class='preview-card'>
                    <div class='preview-card__header'>{title} — Front</div>
                    <div class='card'>{front}</div>
                    <div class='preview-card__header preview-card__header--back'>{title} — Back</div>
                    <div class='card'>{back}</div>
                </div>
                """.format(
                    title=html.escape(card.name), front=card.front, back=card.back
                )
            )

        row_blocks.append(
            """
            <div class='preview-row'>
                <div class='preview-row__meta'>Baris {index} • UID: {uid}</div>
                {cards}
            </div>
            """.format(index=row.index, uid=html.escape(row.uid), cards="".join(cards_html))
        )

    extra_css = """
    .preview-scroll { max-height: 520px; overflow-y: auto; padding-right: 1rem; }
    .preview-row { margin-bottom: 1.5rem; border:1px solid #2a2a34; border-radius:12px; padding:1rem; background:#15151c; }
    .preview-row__meta { font-weight:600; color:#9aa3ad; margin-bottom:0.75rem; }
    .preview-card { margin-bottom:1.25rem; }
    .preview-card:last-child { margin-bottom:0; }
    .preview-card__header { font-size:0.95rem; color:#6ee7b7; margin:0.4rem 0; }
    .preview-card__header--back { color:#f9a8d4; }
    .preview-card .card { border:1px solid #2a2a34; border-radius:10px; padding:0.75rem; background:#0b0b0e; }
    .preview-placeholder { color:#9aa3ad; font-style:italic; }
    .missing-media { color:#f87171; font-style:italic; }
    """

    return (
        "<html><head><meta charset='utf-8'><style>"
        + DECK_CARD_CSS
        + extra_css
        + "</style></head><body><div class='preview-scroll'>"
        + "".join(row_blocks)
        + "</div></body></html>"
    )

def _format_delimiter(label: str) -> str:
    return "\t" if label == "\\t" else label


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


def _parse_ffmpeg_path(raw: str) -> Optional[Path]:
    text = (raw or "").strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return Path(text).expanduser() if text else None


def _handle_generation(tmp_dir: Path, csv_bytes: bytes) -> Optional[DeckBuildResult]:
    csv_path = tmp_dir / "input.csv"
    csv_path.write_bytes(csv_bytes)

    speaker_path = _prepare_audio_file(deck_speaker_file, tmp_dir, "speaker.wav", default_speaker)
    ambient_path = None
    if ambient_file:
        ambient_path = _prepare_audio_file(ambient_file, tmp_dir, "ambient.wav", default_ambient)
    elif default_ambient.exists():
        ambient_path = default_ambient

    if not speaker_path.exists():
        st.error("Speaker WAV tidak ditemukan (upload atau letakkan 'vocal_serena1.wav' di root proyek).")
        return None

    ffmpeg_path = _parse_ffmpeg_path(ffmpeg_path_text)
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

with st.sidebar:
    st.header("⚙️ Settings")

    ffmpeg_path_text = st.text_input("FFmpeg Path", "S:/ffmpeg/bin/ffmpeg.exe")
    tts_model = st.text_input("TTS Model", "tts_models/multilingual/multi-dataset/xtts_v2")
    tts_lang = st.text_input("Bahasa TTS", "zh-cn")

    st.markdown("---")
    st.subheader("🔊 Audio")
    regenerate = st.checkbox("Regenerate audio jika file sudah ada", True)
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

deck_tab, audio_tab, preview_tab = st.tabs([
    "📦 Deck Builder",
    "🔊 Hanzi → Audio",
    "🃏 Anki Deck Previewer",
])


with deck_tab:
    csv_preview_bytes: Optional[bytes] = None
    csv_preview_rows: List[BuilderPreviewRow] = []
    csv_preview_errors: List[str] = []
    csv_preview_error_message: Optional[str] = None
    csv_preview_html: Optional[str] = None

    left, right = st.columns([2, 1])

    with left:
        st.subheader("📥 Upload")
        csv_file = st.file_uploader(
            "CSV (delimiter sesuai pilihan)", type=["csv", "txt"], key="csv_uploader"
        )
        deck_speaker_file = st.file_uploader(
            "Speaker WAV (opsional)", type=["wav"], key="speaker_uploader"
        )
        ambient_file = st.file_uploader("Ambient WAV (opsional)", type=["wav"], key="ambient_uploader")

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

    delimiter_char = _format_delimiter(delimiter_label)
    column_mapping = _resolve_columns_mapping(
        {
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
        }
    )

    if csv_file is not None:
        csv_preview_bytes = csv_file.getvalue()
        try:
            csv_preview_rows, csv_preview_errors = _build_csv_preview_rows(
                csv_preview_bytes,
                csv_name=csv_file.name or "input.csv",
                delimiter=delimiter_char,
                encoding=encoding,
                columns=column_mapping,
                literal_linebreaks=literal_br,
                audio_format=audio_format,
            )
        except UnicodeDecodeError:
            csv_preview_error_message = (
                f"Gagal membaca CSV menggunakan encoding {encoding}. Pilih encoding lain lalu coba lagi."
            )
        except csv.Error as exc:
            csv_preview_error_message = f"Gagal membaca CSV: {exc}"
        else:
            if csv_preview_rows:
                csv_preview_html = _render_csv_preview_html(csv_preview_rows)
            st.session_state["csv_preview_bytes"] = csv_preview_bytes
    else:
        st.session_state.pop("csv_preview_bytes", None)

    if csv_preview_error_message:
        st.error(csv_preview_error_message)
    elif csv_file is not None:
        st.subheader("👀 Preview 10 baris pertama")
        if csv_preview_html:
            st.components.v1.html(csv_preview_html, height=560, scrolling=False)
        else:
            st.info(
                "Tidak ada baris yang dapat ditampilkan. Pastikan kolom Hanzi diisi dan mapping kolom sudah benar."
            )
        if csv_preview_errors:
            st.warning(
                "Beberapa baris memiliki isu yang akan menyebabkan kartu dilewati saat build:"
            )
            st.markdown("\n".join(f"- {msg}" for msg in csv_preview_errors))

    st.markdown("---")

    if st.button("🚀 Lanjutkan Build Deck", type="primary"):
        if not csv_file:
            st.warning("CSV wajib diunggah.")
        elif csv_preview_error_message:
            st.error("Perbaiki error CSV terlebih dahulu sebelum melanjutkan build deck.")
        else:
            payload = csv_preview_bytes or st.session_state.get("csv_preview_bytes")
            if not payload:
                payload = csv_file.getvalue()

            with tempfile.TemporaryDirectory() as tmpdir:
                result = _handle_generation(Path(tmpdir), payload)

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


with audio_tab:
    st.subheader("🔊 Hanzi → Audio Helper")
    st.markdown(
        "<span class='small'>Masukkan teks Hanzi apa pun untuk membuat audio TTS cepat.</span>",
        unsafe_allow_html=True,
    )

    hanzi_text = st.text_area("Teks Hanzi", height=220, placeholder="例如：今天的天气怎么样？")

    audio_speaker_file = st.file_uploader(
        "Speaker WAV khusus tab ini (opsional)",
        type=["wav"],
        key="audio_tab_speaker_uploader",
    )
    st.markdown(
        "<span class='small'>Opsional: unggah sampel suara .wav untuk meniru speaker tertentu."
        " Jika dikosongkan, aplikasi memakai `vocal_serena1.wav` bawaan.</span>",
        unsafe_allow_html=True,
    )

    preview_state = st.session_state.setdefault("audio_preview", {})

    if st.button("🎧 Generate Audio", type="primary", key="generate_audio_button"):
        if not hanzi_text.strip():
            st.warning("Masukkan teks Hanzi terlebih dahulu.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_dir = Path(tmpdir)
                speaker_path = _prepare_audio_file(
                    audio_speaker_file, tmp_dir, "speaker.wav", default_speaker
                )
                ambient_path = None
                if ambient_file:
                    ambient_path = _prepare_audio_file(ambient_file, tmp_dir, "ambient.wav", default_ambient)
                elif default_ambient.exists():
                    ambient_path = default_ambient

                if not speaker_path.exists():
                    st.error("Speaker WAV tidak ditemukan (upload atau letakkan 'vocal_serena1.wav' di root proyek).")
                else:
                    output_file = tmp_dir / f"hanzi_audio.{audio_format}"
                    try:
                        generated_path = generate_audio_from_text(
                            AudioGenerationConfig(
                                text=hanzi_text,
                                output_path=output_file,
                                speaker_wav=speaker_path,
                                ambient_wav=ambient_path,
                                ffmpeg_path=_parse_ffmpeg_path(ffmpeg_path_text),
                                tts_model_name=tts_model,
                                tts_lang=tts_lang,
                                volume_voice_db=voice_db,
                                volume_ambient_db=ambient_db,
                                bitrate=bitrate,
                                audio_format=audio_format,
                            )
                        )
                    except DeckBuildError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # pragma: no cover - defensive against unexpected issues
                        st.error(f"Gagal menghasilkan audio: {exc}")
                        st.write(
                            """<pre style='white-space:pre-wrap;'>""" + traceback.format_exc() + "</pre>",
                            unsafe_allow_html=True,
                        )
                    else:
                        data = generated_path.read_bytes()
                        mime = "audio/mpeg" if audio_format == "mp3" else "audio/wav"
                        filename = f"hanzi_audio.{audio_format}"
                        preview_state.update({
                            "data": data,
                            "mime": mime,
                            "filename": filename,
                        })
                        st.success("Audio berhasil dibuat.")

    if preview_state.get("data"):
        st.audio(preview_state["data"], format=preview_state.get("mime", "audio/mpeg"))
        st.download_button(
            "⬇️ Download Audio",
            preview_state["data"],
            file_name=preview_state.get("filename", "hanzi_audio.mp3"),
            mime=preview_state.get("mime", "audio/mpeg"),
        )


with preview_tab:
    st.subheader("🃏 Anki Deck Previewer")
    st.markdown(
        "<span class='small'>Upload file deck `.apkg` untuk melihat kartu lengkap dengan template dan audio.</span>",
        unsafe_allow_html=True,
    )

    apkg_state = st.session_state.setdefault("apkg_preview", {})
    apkg_file = st.file_uploader(
        "Deck Anki (.apkg)", type=["apkg"], key="apkg_uploader"
    )

    if apkg_file is not None:
        apkg_bytes = apkg_file.getvalue()
        digest = hashlib.sha1(apkg_bytes).hexdigest()
        if apkg_state.get("digest") != digest:
            with st.spinner("Memuat deck…"):
                try:
                    preview_data: ApkgPreview = load_apkg_preview(apkg_bytes)
                except ApkgPreviewError as exc:
                    st.error(str(exc))
                    apkg_state.clear()
                    apkg_state["error"] = str(exc)
                except Exception as exc:  # pragma: no cover - defensive logging
                    st.error(f"Gagal memuat deck: {exc}")
                    st.write(
                        """<pre style='white-space:pre-wrap;'>"""
                        + traceback.format_exc()
                        + "</pre>",
                        unsafe_allow_html=True,
                    )
                    apkg_state.clear()
                    apkg_state["error"] = str(exc)
                else:
                    apkg_state.clear()
                    apkg_state.update(
                        {
                            "digest": digest,
                            "cards": preview_data.cards,
                            "filename": apkg_file.name,
                            "error": None,
                            "selected": preview_data.cards[0].card_id if preview_data.cards else None,
                            "show_answer": False,
                        }
                    )
                    st.session_state.pop("apkg_card_radio", None)
    elif not apkg_state:
        apkg_state["cards"] = []

    if apkg_state.get("error"):
        st.error(apkg_state["error"])

    cards: List[PreviewCard] = apkg_state.get("cards") or []
    if cards:
        selected_id = apkg_state.get("selected")
        card_ids = {card.card_id for card in cards}
        if selected_id not in card_ids:
            selected_id = cards[0].card_id
            apkg_state["selected"] = selected_id

        labels: List[str] = []
        label_to_id: Dict[str, int] = {}
        for card in cards:
            summary = card.front_summary or "(kosong)"
            if len(summary) > 80:
                summary = summary[:77] + "…"
            base_label = f"{card.deck_name} • {summary}"
            label = base_label if base_label not in label_to_id else f"{base_label} (#{card.card_id})"
            labels.append(label)
            label_to_id[label] = card.card_id

        default_label = next(
            (label for label, cid in label_to_id.items() if cid == selected_id),
            labels[0],
        )
        if st.session_state.get("apkg_card_radio") not in label_to_id:
            st.session_state["apkg_card_radio"] = default_label

        list_col, preview_col = st.columns([1, 2])

        with list_col:
            filename = apkg_state.get("filename") or "Tanpa nama"
            st.caption(f"Deck: {filename} • {len(cards)} kartu")
            selected_label = st.radio("Daftar kartu", labels, key="apkg_card_radio")
            selected_id = label_to_id[selected_label]
            if selected_id != apkg_state.get("selected"):
                apkg_state["selected"] = selected_id
                apkg_state["show_answer"] = False

        selected_card = next(card for card in cards if card.card_id == selected_id)
        show_answer = apkg_state.get("show_answer", False)

        with preview_col:
            st.markdown(
                f"**Template:** {selected_card.template_name}"
            )
            toggle_label = "Show Answer" if not show_answer else "Tampilkan Front"
            if st.button(toggle_label, key="apkg_toggle_answer"):
                show_answer = not show_answer
                apkg_state["show_answer"] = show_answer

            html_doc = wrap_card_html(
                selected_card.back_html if show_answer else selected_card.front_html,
                selected_card.css,
            )
            st.components.v1.html(html_doc, height=560, scrolling=True)
    elif apkg_file is not None and not apkg_state.get("error"):
        st.info("Deck tidak memiliki kartu untuk dipreview.")
    else:
        st.info("Upload file deck .apkg untuk mulai melakukan preview.")

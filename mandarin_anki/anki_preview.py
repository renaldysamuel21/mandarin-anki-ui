"""Utilities for rendering and previewing Anki decks."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import html
import json
import mimetypes
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
import zipfile


class ApkgPreviewError(RuntimeError):
    """Raised when an uploaded ``.apkg`` file cannot be parsed."""


@dataclass(frozen=True)
class PreviewCard:
    """Rendered representation of a single card inside an Anki deck."""

    card_id: int
    deck_id: int
    deck_name: str
    note_id: int
    template_name: str
    front_html: str
    back_html: str
    back_only_html: str
    front_summary: str
    css: str


@dataclass(frozen=True)
class ApkgPreview:
    """Collection of rendered cards extracted from an ``.apkg`` archive."""

    cards: List[PreviewCard]


FIELD_RE = re.compile(r"{{([^{}]+)}}")
SECTION_RE = re.compile(r"{{([#^])([^{}]+)}}")
CLOZE_RE = re.compile(r"{{c\d+::(.*?)(?:::(.*?))?}}", re.DOTALL)
SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")


def load_apkg_preview(apkg_bytes: bytes) -> ApkgPreview:
    """Parse a ``.apkg`` archive and return rendered card previews."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "uploaded.apkg"
        tmp_path.write_bytes(apkg_bytes)
        return _load_from_path(tmp_path)


def wrap_card_html(body: str, css: str) -> str:
    """Wrap raw card HTML with a minimal document scaffold for embedding."""

    return (
        "<html><head><meta charset='utf-8'><style>"
        + css
        + "</style></head><body><div class='card'>"
        + body
        + "</div></body></html>"
    )


def render_template(
    template: str,
    fields: Mapping[str, str],
    *,
    media_map: Optional[Mapping[str, bytes]] = None,
    front_side: Optional[str] = None,
) -> str:
    """Render an Anki template with the provided field values."""

    rendered = _render_sections(template, fields)
    if "{{FrontSide}}" in rendered:
        rendered = rendered.replace("{{FrontSide}}", front_side or "")
    rendered = FIELD_RE.sub(lambda m: _replace_field(m, fields), rendered)
    rendered = _replace_sound_refs(rendered, media_map or {})
    return rendered


def _load_from_path(path: Path) -> ApkgPreview:
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                with archive.open("media") as handle:
                    media_map = json.load(handle)
            except KeyError as exc:
                raise ApkgPreviewError("File .apkg tidak memiliki berkas media.") from exc

            media_bytes: Dict[str, bytes] = {}
            for key, name in media_map.items():
                if not name:
                    continue
                try:
                    media_bytes[name] = archive.read(key)
                except KeyError:
                    continue

            with tempfile.TemporaryDirectory() as tmp_extract:
                archive.extractall(tmp_extract)
                collection_path = Path(tmp_extract) / "collection.anki2"
                return _load_collection(collection_path, media_bytes)
    except zipfile.BadZipFile as exc:  # pragma: no cover - defensive
        raise ApkgPreviewError("File .apkg tidak valid atau rusak.") from exc


def _load_collection(collection_path: Path, media_bytes: Mapping[str, bytes]) -> ApkgPreview:
    if not collection_path.exists():
        raise ApkgPreviewError("File .apkg tidak memiliki collection.anki2.")

    conn = sqlite3.connect(str(collection_path))
    conn.row_factory = sqlite3.Row
    try:
        col_row = conn.execute("SELECT models, decks FROM col").fetchone()
        if col_row is None:
            raise ApkgPreviewError("Database Anki tidak memiliki metadata deck.")

        models = json.loads(col_row["models"] or "{}")
        decks = json.loads(col_row["decks"] or "{}")
        deck_names = {int(k): v.get("name", f"Deck {k}") for k, v in decks.items() if isinstance(v, dict)}

        note_rows = conn.execute("SELECT id, mid, flds FROM notes").fetchall()
        notes = {
            row["id"]: (row["mid"], row["flds"].split("\x1f"))
            for row in note_rows
        }

        card_rows = conn.execute(
            "SELECT id, nid, did, ord FROM cards ORDER BY did, id"
        ).fetchall()

        cards: List[PreviewCard] = []
        for row in card_rows:
            note = notes.get(row["nid"])
            if not note:
                continue
            model = models.get(str(note[0]))
            if not model:
                continue
            templates: Iterable[Mapping[str, str]] = model.get("tmpls", [])
            templates = list(templates)
            ord_index = row["ord"]
            if ord_index >= len(templates):
                continue

            template = templates[ord_index]
            field_names = [fld.get("name", "") for fld in model.get("flds", [])]
            values = note[1]
            field_map = {
                name: values[idx] if idx < len(values) else ""
                for idx, name in enumerate(field_names)
            }

            css = model.get("css", "")
            front = render_template(template.get("qfmt", ""), field_map, media_map=media_bytes)
            back = render_template(
                template.get("afmt", ""),
                field_map,
                media_map=media_bytes,
                front_side=front,
            )
            back_only = render_template(
                template.get("afmt", ""),
                field_map,
                media_map=media_bytes,
                front_side="",
            )
            summary = _summarise_front(front)
            deck_name = deck_names.get(row["did"], f"Deck {row['did']}")
            cards.append(
                PreviewCard(
                    card_id=row["id"],
                    deck_id=row["did"],
                    deck_name=deck_name,
                    note_id=row["nid"],
                    template_name=str(template.get("name", f"Card {ord_index}")),
                    front_html=front,
                    back_html=back,
                    back_only_html=back_only,
                    front_summary=summary,
                    css=css,
                )
            )

        if not cards:
            raise ApkgPreviewError("Deck tidak memiliki kartu yang dapat dipreview.")

        return ApkgPreview(cards=cards)
    finally:
        conn.close()


def _render_sections(template: str, fields: Mapping[str, str]) -> str:
    text = template
    while True:
        match = SECTION_RE.search(text)
        if not match:
            break
        tag_type, raw_field = match.groups()
        field_name = raw_field.strip()
        start = match.end()
        end, inner = _extract_section(text, field_name, start)
        if end == -1:
            break
        value = fields.get(field_name, "")
        truthy = bool(value.strip())
        replacement = inner if (truthy if tag_type == "#" else not truthy) else ""
        text = text[: match.start()] + replacement + text[end:]
    return text


def _extract_section(text: str, field: str, start: int) -> Tuple[int, str]:
    close_tag = f"{{{{/{field}}}}}"
    open_hash = f"{{{{#{field}}}}}"
    open_caret = f"{{{{^{field}}}}}"
    depth = 1
    idx = start
    while depth > 0:
        next_close = text.find(close_tag, idx)
        if next_close == -1:
            return -1, ""
        next_hash = text.find(open_hash, idx)
        next_caret = text.find(open_caret, idx)
        next_open_candidates = [pos for pos in (next_hash, next_caret) if pos != -1]
        next_open = min(next_open_candidates) if next_open_candidates else -1
        if next_open != -1 and next_open < next_close:
            depth += 1
            if next_hash != -1 and next_hash == next_open:
                idx = next_open + len(open_hash)
            else:
                idx = next_open + len(open_caret)
            continue
        depth -= 1
        idx = next_close + len(close_tag)
        if depth == 0:
            inner = text[start:next_close]
            return idx, inner
    return -1, ""


def _replace_field(match: re.Match[str], fields: Mapping[str, str]) -> str:
    expr = match.group(1).strip()
    if not expr:
        return ""

    if ":" in expr:
        prefix, field_name = expr.split(":", 1)
        prefix = prefix.strip().lower()
        field_name = field_name.strip()
        value = fields.get(field_name, "")
        if prefix == "text":
            return html.escape(value)
        if prefix == "type":
            return f"<span class=\"typeAnswer\">{value}</span>"
        if prefix == "cloze":
            return _apply_cloze(value)
        # unsupported filters fall back to the raw value
        return value

    if expr == "FrontSide":
        return ""

    return fields.get(expr, "")


def _apply_cloze(value: str) -> str:
    return CLOZE_RE.sub(lambda m: f"<span class='cloze'>{m.group(1)}</span>", value)


def _replace_sound_refs(text: str, media_map: Mapping[str, bytes]) -> str:
    def _replace(match: re.Match[str]) -> str:
        filename = match.group(1)
        data = media_map.get(filename)
        if not data:
            return f"<span class=\"missing-media\">[sound:{html.escape(filename)}]</span>"
        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return (
            "<audio controls preload='metadata' style=\"width:100%; margin-top:0.5rem;\">"
            f"<source src='data:{mime};base64,{encoded}'>"
            "Your browser does not support audio playback."
            "</audio>"
        )

    return SOUND_RE.sub(_replace, text)


def _summarise_front(text: str) -> str:
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:140] + ("…" if len(clean) > 140 else "")


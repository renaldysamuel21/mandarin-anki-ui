# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2024-05-12
### Added
- Streamlit UI now features separate tabs for the deck builder and a new "Hanzi → Audio" helper.
- Quick audio helper synthesises Hanzi text to MP3/WAV using the existing TTS pipeline with in-app preview and download.
- Exposed reusable `generate_audio_from_text` helper via `mandarin_anki.audio_engine` for standalone audio generation.

### Changed
- Sidebar now includes an editable FFmpeg path field.
- Documentation updated to highlight version 2.0 capabilities.

[2.0.0]: https://github.com/<username>/mandarin-anki-ui/releases/tag/v2.0.0

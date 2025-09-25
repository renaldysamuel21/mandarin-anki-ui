# Mandarin Anki UI

A Streamlit front-end and deck builder utilities for converting Mandarin CSV lesson data into ready-to-import Anki decks. The builder wraps Coqui TTS so every card ships with synthesized audio.

## Features

- CSV → `.apkg` conversion with three card templates (reading, listening, production).
- Optional ambience mixing and literal meaning formatting.
- Streamlit UI with progress feedback, error reporting, and sensible defaults.
- Dependency-light module layout with unit tests for the deck builder core.

## Requirements

- Python 3.10 or newer (tested on Windows 11 & Ubuntu 22.04).
- FFmpeg (for MP3 export through `pydub`).
- A GPU with CUDA *optional*. The app automatically falls back to CPU when CUDA is not available.

## Windows setup

1. **Install Python**
   - Download Python 3.10+ from [python.org](https://www.python.org/downloads/windows/).
   - During installation check **“Add python.exe to PATH”**.
2. **Create and activate a virtual environment**
   ```powershell
   cd path\to\mandarin-anki-ui
   py -3.10 -m venv .venv
   .venv\Scripts\activate
   ```
3. **Install dependencies**
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. **(Optional) Install FFmpeg**
   - Download a static build from [Gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
   - Extract and add `ffmpeg\bin` to your PATH, or remember the full `ffmpeg.exe` path for the app input field.
5. **Run the Streamlit UI**
   ```powershell
   streamlit run app.py
   ```
6. Open the displayed local URL in your browser to start generating decks.

## Troubleshooting

### CUDA / GPU issues
- If CUDA drivers are missing or incompatible, the app falls back to CPU automatically.
- For manual override, edit `DeckBuildConfig.tts_device_preference` (e.g. `("cpu",)`) before calling `build_anki_deck`.
- Installing the correct [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) and matching drivers may improve performance but is **not required**.

### FFmpeg errors
- The error `Couldn’t find ffmpeg or avconv` means FFmpeg is not on PATH.
- Use the “Path FFmpeg” input in the UI to point to `ffmpeg.exe` (Windows) or `/usr/bin/ffmpeg` (Linux/macOS).
- Re-run the app after adjusting PATH or the input value.

### TTS voice glitches
- Ensure your cloned voice WAV is a clean mono/stereo PCM WAV file.
- When no file is uploaded the app reuses the bundled `vocal_serena1.wav` and ambience `room.wav`.

## Example CSV

The builder expects at least the three columns shown below. Additional columns (`Literal`, `Grammar`, etc.) will be consumed automatically when present.

```csv
Hanzi;Pinyin;Indo
你好;ni hao;Halo
谢谢;xie xie;Terima kasih
```

## Running tests

Run unit tests from an activated virtual environment:

```bash
pytest
```

## Project structure

```
mandarin-anki-ui/
├── app.py                  # Streamlit entry point
├── anki_builder.py         # Legacy wrapper importing the new builder module
├── mandarin_anki_ui/       # Core package
│   ├── __init__.py
│   ├── audio_engine.py
│   └── deck_builder.py
├── requirements.txt
├── tests/
│   └── test_deck_builder.py
├── room.wav
└── vocal_serena1.wav
```


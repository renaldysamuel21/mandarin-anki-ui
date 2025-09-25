from TTS.api import TTS
from pathlib import Path
import time
from pydub import AudioSegment

# --- Set manual lokasi ffmpeg ---
AudioSegment.converter = r"S:\ffmpeg\bin\ffmpeg.exe"

# --- Konfigurasi TTS ---
TEXT = """
啊啊啊……我要了！
"""

SPEAKER_WAV = Path("vocal_serena1.wav")
TEMP_WAV = Path("temp_output.wav")  # file sementara
FINAL_MP3 = Path("output1_啊啊啊……我要了！.mp3")
LANG = "zh-cn"

# --- Proses TTS ---
start = time.time()
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
tts.to("cuda")

tts.tts_to_file(
    text=TEXT.strip(),
    speaker_wav=SPEAKER_WAV,
    language=LANG,
    file_path=TEMP_WAV,
    split_sentences=True
)

print(f"🗣 TTS done in {time.time() - start:.2f}s. Temp WAV saved to {TEMP_WAV}")

# --- Audio Mixing ---
voice = AudioSegment.from_wav(TEMP_WAV)
voice = voice - 8  # turunkan volume TTS

ROOM_AMBIENT = Path("room.wav")
ambient = AudioSegment.from_wav(ROOM_AMBIENT)

# Loop dan potong ambient agar sama panjang
while len(ambient) < len(voice):
    ambient += ambient
ambient = ambient[:len(voice)]
ambient = ambient - 30  # pelankan ambient

# Gabung suara
final_audio = voice.overlay(ambient)

# Export sebagai MP3
final_audio.export(FINAL_MP3, format="mp3", bitrate="192k")
print(f"✅ Final output saved to {FINAL_MP3}")

# Optional: hapus file temp WAV kalau mau bersih
TEMP_WAV.unlink()

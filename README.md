# Mandarin → Anki Deck Builder

A Streamlit web app that turns Mandarin vocabulary or sentence lists into polished Anki decks complete with Coqui TTS audio.

## ✨ Fitur utama

- Upload CSV dengan kolom Hanzi, Pinyin, dan terjemahan Indonesia.
- Mixing otomatis antara suara TTS dan ambience ruangan.
- Pengaturan delimiter, encoding, pemetaan kolom, dan bitrate audio.
- Progress bar & log status saat build deck.
- Galat per baris ditampilkan sehingga mudah diperbaiki.

## 🚀 Persiapan di Windows

1. **Install Python 3.10+** dan tambahkan ke `PATH` saat instalasi.
2. **Clone repo** dan buka terminal (PowerShell):
   ```powershell
   git clone https://github.com/<username>/mandarin-anki-ui.git
   cd mandarin-anki-ui
   ```
3. **Buat virtual environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
4. **Install dependency**:
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
5. **Pastikan audio default tersedia** di folder proyek:
   - `vocal_serena1.wav` (voice sample)
   - `room.wav` (ambient)
6. **Jalankan aplikasi**:
   ```powershell
   streamlit run app.py
   ```
7. Buka browser ke `http://localhost:8501`.

## 🛠️ Troubleshooting

### CUDA / GPU tidak tersedia
- Aplikasi otomatis jatuh ke CPU. Jika ingin pakai GPU, install driver NVIDIA terbaru dan CUDA Toolkit yang kompatibel.
- Pastikan `torch` mendeteksi GPU:
  ```python
  python -c "import torch; print(torch.cuda.is_available())"
  ```
- Jika `False`, install ulang `torch` dengan wheel CUDA dari https://pytorch.org.

### FFmpeg tidak terdeteksi
- Unduh FFmpeg build Windows dari https://www.gyan.dev/ffmpeg/builds/.
- Ekstrak ke misalnya `C:\ffmpeg` dan set `bin` ke PATH atau isi field `FFmpeg Path` di sidebar dengan `C:\ffmpeg\bin\ffmpeg.exe`.
- Tanpa FFmpeg, ekspor MP3 akan gagal. Gunakan opsi format WAV pada UI untuk testing jika belum sempat memasang FFmpeg.

### Suara TTS serak / delay
- Turunkan volume ambience atau matikan dengan menghapus file `room.wav`.
- Pastikan kualitas input `vocal_serena1.wav` sesuai format WAV 16-bit PCM.

### Error `numpy.core.multiarray failed to import`
- Biasanya muncul saat wheel `numpy` tidak cocok dengan versi Python/OS.
- Instal ulang `numpy` versi stabil yang kompatibel:
  ```powershell
  pip install --force-reinstall "numpy==1.26.4"
  ```
- Jalankan kembali `pip install -r requirements.txt` setelahnya untuk memastikan semua paket TTS tersusun rapi.

## 📄 Contoh CSV minimal

Simpan sebagai `contoh.csv` (delimiter koma). Kolom wajib minimal `Hanzi`, `Pinyin`, `Indo`.

```csv
Hanzi,Pinyin,Indo
你好,nǐ hǎo,Halo
谢谢,xièxie,Terima kasih
再见,zàijiàn,Sampai jumpa
```

## 🧪 Testing

Menjalankan unit test ringan untuk memastikan builder bekerja:

```bash
pytest
```

## 📦 Lisensi

Gunakan secara bebas untuk kebutuhan pribadi atau pembelajaran. Periksa lisensi Coqui TTS bila ingin distribusi komersial.

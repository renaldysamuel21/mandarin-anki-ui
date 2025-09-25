Berikut ringkasan **app\_summary.md** yang bisa kamu pakai untuk mendeskripsikan project dan rencana konversi ke aplikasi web dengan UI:

---

# Mandarin → Anki Deck Builder

## 🎯 Tujuan

Aplikasi ini menghasilkan file **`.apkg`** yang siap diimport ke Anki dari sebuah file **CSV** berisi data Mandarin (Hanzi, pinyin, arti, literal, grammar).
Versi awal skrip ditulis **hardcoded**: semua path (CSV, TTS model, FFmpeg, output) dan parameter dipasang langsung di dalam file Python. Bisa cek di file `anki_builder.py`.

Target baru: **membuat aplikasi web ringan** (misal dengan Streamlit) agar pengguna bisa meng-upload CSV dan file pendukung (audio speaker, ambient), memilih opsi parsing/konfigurasi melalui UI, lalu mengunduh hasil `.apkg` yang dihasilkan.

---

## ⚙️ Cara Kerja Script Lama

1. **Input:**

   * CSV berisi kolom `Hanzi`, `Pinyin`, `Indo`, `Literal`, `Grammar`, dll.
   * File audio *speaker voice* (WAV) dan *ambient noise* opsional.
2. **TTS:**

   * Menggunakan model `TTS` (misal `tts_models/multilingual/multi-dataset/xtts_v2`) untuk membuat audio MP3 setiap baris Hanzi.
3. **Audio Processing:**

   * Memadukan suara TTS dengan suara ambient memakai `pydub`.
4. **Anki Deck:**

   * Membangun **model kartu 3 tipe** (Reading→Meaning, Listening→Text, Meaning→Production) menggunakan `genanki`.
5. **Output:**

   * Menghasilkan file `.apkg` yang sudah termasuk media audio dan siap diimport ke Anki.

---

## 🔧 Keterbatasan Versi Hardcode

* Semua **path dan parameter** (FFmpeg, model TTS, bahasa, nama CSV, output folder) ditulis manual dalam script.
* Tiap kali ganti CSV atau pengaturan, pengguna harus mengedit kode.
* Tidak ada antarmuka pengguna.

---

## 🚀 Rencana Pengembangan (Versi Web UI)

### Fitur yang Diinginkan

* **Upload CSV** langsung dari browser.
* **Upload file Speaker WAV** dan (opsional) Ambient WAV.
* Input **parameter TTS**: model, bahasa, FFmpeg path, opsi regenerate audio, dll.
* **Preview** parsing (misalnya konversi koma → `<br>`, dsb).
* Tombol **Generate Deck** → menghasilkan `.apkg`.
* Tombol **Download Deck** untuk mengambil file hasil.

### Teknologi

* **Backend & UI:** [Streamlit](https://streamlit.io/) (sederhana, cepat dibuat).
* **Audio & TTS:** tetap `pydub` + `TTS`.
* **Deck:** `genanki`.
* **Python environment:** isolasi lewat `venv` + `requirements.txt`.

### Struktur Project Baru

```
mandarin-anki-ui/
├─ anki_builder.py   # fungsi utama pembuat deck (dipindah dari script lama)
├─ app.py            # UI Streamlit
├─ requirements.txt
└─ .gitignore
```

* **`anki_builder.py`**: refactor script lama jadi fungsi `build_anki()` dengan parameter yang bisa dipanggil dari UI.
* **`app.py`**: Streamlit UI untuk upload, input setting, jalankan builder, dan unduh hasil `.apkg`.

### Dependensi Minimal (`requirements.txt`)

```
pydub
TTS
genanki
streamlit
```

---

## ✅ Alur Penggunaan Versi Baru

1. Jalankan lokal: `streamlit run app.py`.
2. Buka UI di browser.
3. Upload CSV dan file pendukung → atur parameter.
4. Klik **Generate Deck** → tunggu proses TTS + bundling media.
5. Download `.apkg` yang sudah jadi.

---

> Dengan pendekatan ini, kamu tidak lagi perlu mengedit kode setiap kali ingin mengubah input. Semua opsi dapat dikontrol langsung melalui UI, sementara logika pembuatan deck tetap menggunakan script lama yang telah dipindahkan ke modul terpisah.

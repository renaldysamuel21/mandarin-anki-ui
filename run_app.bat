@echo off
REM --- pindah ke folder project ---
cd /d S:\Python Projects\mandarin-anki-ui

REM --- aktifkan virtual env ---
call venv\Scripts\activate.bat

REM --- jalankan streamlit ---
streamlit run app.py

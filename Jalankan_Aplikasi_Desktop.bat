@echo off
title Social Media Sentiment Analysis Desktop v1.1
color 0B
echo ========================================================================
echo   SOCIAL MEDIA SENTIMENT ANALYSIS FOR PUBLIC POLICY (DESKTOP v1.1)
echo ========================================================================
echo.
echo Membuka aplikasi dasbor eksekutif berbasis AI...
echo.

cd /d "%~dp0"

if exist ".\venv\Scripts\python.exe" (
    ".\venv\Scripts\python.exe" desktop_launcher.py
) else (
    python desktop_launcher.py
)

pause

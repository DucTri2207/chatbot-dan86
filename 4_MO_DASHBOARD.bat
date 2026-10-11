@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   MO DASHBOARD THEO DOI BOT TRUC FANPAGE DAN86 (24/24)
echo   (SIEU NHE - KHONG TON RAM/O CUNG - CAP NHAT REAL-TIME)
echo ====================================================================
echo.
python dashboard.py
echo.
pause

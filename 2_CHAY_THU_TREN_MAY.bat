@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   CHAY BOT TRUC FANPAGE DAN86 (COMMENT + AUTO INBOX + MESSENGER)
echo ====================================================================
echo.
echo [1] Chay thu an toan (Dry-Run: Chi xem truoc cau tra loi, KHONG bam gui)
echo [2] Chay THAT tren may tinh (Tu dong rep Comment + Inbox + Messenger)
echo.
set /p mode="Chon che do (nhap 1 hoac 2, mac dinh la 1): "
if "%mode%"=="2" (
    python "2_chay_bot_truc_page.py"
) else (
    python "2_chay_bot_truc_page.py" --dry-run
)
echo.
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   CHAY BOT TRUC FANPAGE DAN86 (COMMENT + AUTO INBOX + MESSENGER)
echo ====================================================================
echo.
echo [1] Chay thu an toan (Dry-Run: Chi xem truoc cau tra loi, KHONG bam gui)
echo [2] Chay THAT hien trinh duyet (De quan sat truc quan tren man hinh)
echo [3] Chay THAT chay NGAM (Headless: Khong hien trinh duyet, sieu nhe may)
echo.
set /p mode="Chon che do (nhap 1, 2 hoac 3, mac dinh la 3): "
if "%mode%"=="1" (
    python "2_chay_bot_truc_page.py" --dry-run
) else if "%mode%"=="2" (
    python "2_chay_bot_truc_page.py"
) else (
    python "2_chay_bot_truc_page.py" --headless
)
echo.
pause

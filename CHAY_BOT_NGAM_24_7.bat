@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   KHOI DONG DAN86 BOT CHAY NGAM (HEADLESS) TREN MAY TINH
echo   (SIEU NHE: 1-2%% CPU, ~150MB RAM, HOAN TOAN KHONG LAM CHAM MAY)
echo ====================================================================
echo 👉 Bot dang chay truc Fanpage ngam...
echo    De theo doi truc quan, ban co the mo Dashboard bang cach chay file:
echo    4_MO_DASHBOARD.bat
echo ====================================================================
python "2_chay_bot_truc_page.py" --headless
echo.
pause

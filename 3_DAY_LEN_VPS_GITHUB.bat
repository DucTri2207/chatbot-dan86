@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   BUOC 3: DAY BO CODE BOT + TU DONG CAI SECRET LEN VPS GITHUB 24/24
echo   Repo: https://github.com/DucTri2207/chatbot-dan86.git
echo ====================================================================
echo.
echo [1/4] Dang dong goi va day code len GitHub (nhanh master)...
git add .
git status -s
git commit -m "feat: trien khai bot Playwright truc Fanpage DAN86 24/24 tren GitHub Actions"
git push origin HEAD:master

echo.
echo [2/4] Dang tu dong nap khoa phien dang nhap FB_STORAGE_STATE len GitHub Secrets...
if exist "state\GITHUB_SECRET_VALUE.txt" (
    gh secret set FB_STORAGE_STATE --repo DucTri2207/chatbot-dan86 < "state\GITHUB_SECRET_VALUE.txt"
    echo    -^> Da nap Secret FB_STORAGE_STATE thanh cong!
) else (
    echo    -^> CANH BAO: Chua co file state\GITHUB_SECRET_VALUE.txt. Hay chay 1_DANG_NHAP_PAGE.bat truoc!
)

echo.
echo [3/4] Dang cap quyen Read/Write cho GitHub Actions luu bo nho bot_memory.json...
gh api --method PUT /repos/DucTri2207/chatbot-dan86/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true >nul 2>&1

echo.
echo [4/4] Dang kich hoat Ca VPS 24/24 dau tien tren GitHub Actions...
gh workflow run vps_bot_24_7.yml --repo DucTri2207/chatbot-dan86

echo.
echo ====================================================================
echo   HOAN TAT! VPS GITHUB DA DUOC KICH HOAT CHAY 24/24!
echo   Xem trang thai chay tai: https://github.com/DucTri2207/chatbot-dan86/actions
echo ====================================================================
pause

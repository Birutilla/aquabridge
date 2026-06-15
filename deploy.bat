@echo off
cd /d "%~dp0"
echo.
echo Publishing AquaBridge website...
echo.

:: Clean stale lock files FIRST — before any git commands
for /r ".git" %%f in (*.lock) do del /f /q "%%f" 2>nul

:: Remove loose origin/main ref if it conflicts with packed-refs
if exist ".git\refs\remotes\origin\main" del /f /q ".git\refs\remotes\origin\main"

git add .
git commit -m "Update website %date% %time%"

:: Fetch and rebase separately for reliability
git fetch origin main
git rebase origin/main
git push origin HEAD:main
echo.
echo Done! Changes will be live at www.aquabridge.cl in about a minute.
echo.
pause

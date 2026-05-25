@echo off
cd /d "%~dp0"
echo.
echo Publishing AquaBridge website...
echo.
git add .
git commit -m "Update website %date% %time%"
git pull --rebase origin main
git push
echo.
echo Done! Changes will be live at www.aquabridge.cl in about a minute.
echo.
pause

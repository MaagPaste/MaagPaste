@echo off
echo ===================================
echo   Building MaagPaste.exe
echo ===================================

py -m pip install --upgrade pip >nul
py -m pip install -r requirements.txt

py -m PyInstaller --noconfirm --onefile --windowed ^
  --name MaagPaste ^
  --icon=icon.ico ^
  --add-data "icon.ico;." ^
  maagpaste.py

echo.
echo ===================================
echo   Done! Your exe is at:
echo   dist\MaagPaste.exe
echo ===================================
pause

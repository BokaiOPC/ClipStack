@echo off
REM ClipStack one-click build script
REM Requires: Python 3.10+ and "pip install pillow pyinstaller"
cd /d "%~dp0"
if not exist "复制开.wav" python gen_sounds.py
python -m PyInstaller --onefile --noconsole --name ClipStack --clean clipstack_win32.py
echo.
echo Build done: dist\ClipStack.exe
pause

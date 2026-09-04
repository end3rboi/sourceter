@echo off
REM Build Sourceter.exe — run this on Windows, inside the activated venv.
python -m pip install --upgrade pyinstaller pillow
python make_icon.py
pyinstaller --noconfirm --clean ^
    --onefile ^
    --noconsole ^
    --name Sourceter ^
    --icon icon.ico ^
    app.py
echo.
echo Done. Your app is dist\Sourceter.exe
pause

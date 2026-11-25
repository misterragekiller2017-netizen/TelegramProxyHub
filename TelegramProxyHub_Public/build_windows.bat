@echo off
chcp 65001 >nul
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m PyInstaller --noconfirm --clean --onefile --windowed --name TelegramProxyHub main.py
echo.
echo Готово. EXE находится в папке dist.
pause

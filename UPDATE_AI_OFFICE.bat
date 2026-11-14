@echo off
chcp 65001 >nul
title AI OFFICE - Guncelleme
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" ( echo Once INSTALL_AI_OFFICE.bat calistirin. & pause & exit /b 1 )
echo Once otomatik yedek aliniyor...
"%PY%" "%~dp0backend\cli.py" backup
echo Python paketleri guncelleniyor...
"%PY%" -m pip install --upgrade --disable-pip-version-check -r "%~dp0backend\requirements.txt"
echo Eksik motor/model dosyalari kontrol ediliyor...
"%PY%" "%~dp0backend\cli.py" prepare
echo Guncelleme tamamlandi.
pause

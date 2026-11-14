@echo off
chcp 65001 >nul
title AI OFFICE - Yedekleme
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" ( echo Once INSTALL_AI_OFFICE.bat calistirin. & pause & exit /b 1 )
set "PW="
set /p PW="Sifreli yedek icin parola girin (bos birakirsaniz sifresiz ZIP): "
"%PY%" "%~dp0backend\cli.py" backup --password "%PW%"
echo Yedekler: %~dp0backups
pause

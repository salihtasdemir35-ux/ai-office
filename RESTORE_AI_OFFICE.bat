@echo off
chcp 65001 >nul
title AI OFFICE - Geri Yukleme
cd /d "%~dp0"
set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" ( echo Once INSTALL_AI_OFFICE.bat calistirin. & pause & exit /b 1 )
echo UYARI: AI OFFICE kapaliyken calistirin. Mevcut veriler once otomatik yedeklenir.
"%PY%" "%~dp0backend\cli.py" restore
pause

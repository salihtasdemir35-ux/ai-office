@echo off
chcp 65001 >nul
title AI OFFICE - Bu pencereyi kapatmayin
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY=%~dp0runtime\python\python.exe"
if exist "%PY%" goto :run
rem Paket ici Python yoksa bilgisayardaki Python'u dene
for %%P in (python.exe) do set "PY=%%~$PATH:P"
if not defined PY goto :nopy
if "%PY%"=="" goto :nopy
:run
"%PY%" -c "import fastapi, docx, pymupdf" >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Gerekli bilesenler eksik. Once INSTALL_AI_OFFICE.bat dosyasini calistirin.
  echo.
  pause
  exit /b 1
)
"%PY%" "%~dp0backend\run.py"
echo.
echo  AI OFFICE kapandi.
timeout /t 5 >nul
exit /b 0
:nopy
echo.
echo  Python bulunamadi. Once INSTALL_AI_OFFICE.bat dosyasini calistirin (yonetici yetkisi gerekmez).
echo.
pause
exit /b 1

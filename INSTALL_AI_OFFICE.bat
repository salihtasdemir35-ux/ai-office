@echo off
chcp 65001 >nul
title AI OFFICE - Kurulum / Paketleme
cd /d "%~dp0"
echo ============================================================
echo   AI OFFICE - Kurulum ve Paketleme
echo   Yonetici yetkisi GEREKMEZ. Her sey bu klasore kurulur.
echo   Yarida kalirsa tekrar calistirin; kaldigi yerden devam eder.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\prepare_runtime.ps1" -Root "%~dp0."
if errorlevel 1 goto :fail
set "PY=%~dp0runtime\python\python.exe"
set "PYTHONUTF8=1"
echo.
echo  Model konumu secin:
echo    1 = USB / bu klasor (tam tasinabilir)  [varsayilan]
echo    2 = Bu bilgisayarda (%%LOCALAPPDATA%%\AI_OFFICE\models)
echo    3 = Karma (kucuk model USB'de, buyuk model bilgisayarda)
set "LOC=usb"
set /p SEL="Seciminiz (1/2/3): "
if "%SEL%"=="2" set "LOC=local"
if "%SEL%"=="3" set "LOC=hybrid"
echo.
echo  Donanim analiz ediliyor ve en uygun model otomatik seciliyor...
"%PY%" "%~dp0backend\cli.py" prepare --location %LOC%
if errorlevel 1 goto :fail
echo.
echo  Kurulum tamamlandi. Simdi START_AI_OFFICE.bat ile baslatabilirsiniz.
echo  Tum modelleri pakete eklemek icin:  runtime\python\python.exe backend\cli.py prepare --all-models
pause
exit /b 0
:fail
echo.
echo  HATA olustu. Internet baglantinizi kontrol edip bu dosyayi tekrar calistirin.
pause
exit /b 1

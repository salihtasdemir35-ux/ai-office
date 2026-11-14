@echo off
chcp 65001 >nul
title AI OFFICE - Guvenli Kapat ve Cikar
cd /d "%~dp0"
if not exist "%~dp0runtime\port.txt" ( echo AI OFFICE zaten kapali. USB'yi guvenle cikarabilirsiniz. & pause & exit /b 0 )
set /p PORT=<"%~dp0runtime\port.txt"
echo Aktif gorevler durduruluyor, veriler diske yaziliyor...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:%PORT%/api/system/safe-exit; $r.steps | ForEach-Object { Write-Host ' [OK]' $_ }; Write-Host ''; Write-Host $r.message } catch { Write-Host 'Sunucuya ulasilamadi (zaten kapali olabilir).' }"
pause

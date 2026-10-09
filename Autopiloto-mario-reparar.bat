@echo off
rem Reparación de «Supersalto» (proyecto «mario», lista autopilot\mario-reparar.md), 100 % local y sin Claude (0 $).
rem La barrera tests\modulos.test.mjs del proyecto obliga a que cada módulo reparado cargue y exporte lo suyo.
rem Sin --continuo: al acabarse la lista, para. No lo lances con otro autopiloto en marcha: comparten GPU.
chcp 65001 >nul
title LocalHarness - Reparar Supersalto (no cierres esta ventana)
cd /d "%~dp0"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8095/api/llama -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Abriendo LocalHarness...
  start "LocalHarness" cmd /c "%~dp0LocalHarness.bat"
)
powershell -NoProfile -Command "$t = 0; while ($t -lt 240) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8095/api/llama -TimeoutSec 3 | Out-Null; exit 0 } catch { Start-Sleep 5; $t += 5 } }; exit 1"
if errorlevel 1 (
  echo LocalHarness no contesta en 4 minutos: abre LocalHarness.bat a mano y luego este .bat otra vez
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m localharness autopilot --project mario --agent "Jefe local" --list "autopilot\mario-reparar.md" --hours 8 --budget 1 --task-minutes 45 --check "npm test"
echo.
echo Autopiloto terminado. Informe: data\autopilot\mario-reparar-informe.md
pause

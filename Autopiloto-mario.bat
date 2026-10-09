@echo off
rem Autopiloto 100 % local del Mario casero «Supersalto» (proyecto «mario», lista autopilot\mario.md): abre
rem LocalHarness si no está abierto, espera a que conteste y hace 24 h sin Claude (0 $). Cada parche trae dos módulos
rem independientes para que gpt-oss-20b (3060) y Qwen3.5-4B (1060) trabajen a la vez. Cuando se acaba la lista, los
rem modelos proponen los parches siguientes (--continuo). No lo lances con otro autopiloto en marcha: comparten GPU.
chcp 65001 >nul
title LocalHarness - Autopiloto Supersalto (no cierres esta ventana)
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
".venv\Scripts\python.exe" -m localharness autopilot --project mario --agent "Jefe local" --list "autopilot\mario.md" --hours 24 --budget 1 --task-minutes 45 --check "npm test" --continuo
echo.
echo Autopiloto terminado. Informe: data\autopilot\mario-informe.md
pause

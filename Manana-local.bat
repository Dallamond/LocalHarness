@echo off
rem Plan automático de mañana (lo lanza la tarea programada «LocalHarness - autopiloto local»): abre LocalHarness si
rem no está abierto, espera a que conteste y hace 6 h de autopiloto 100 % local (sin Claude, 0 $) con la lista
rem autopilot\poeta-local.md; cuando se acaba, los modelos proponen los parches siguientes (--continuo).
rem Los modelos los arranca el autopiloto: gpt-oss-20b en la 3060 (n_cpu_moe 4) y Qwen3.5-4B en la 1060.
chcp 65001 >nul
title LocalHarness - Autopiloto local de la mañana (no cierres esta ventana)
cd /d "%~dp0"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8095/api/llama -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Abriendo LocalHarness...
  start "LocalHarness" cmd /c "%~dp0LocalHarness.bat"
)
powershell -NoProfile -Command "$t = 0; while ($t -lt 240) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8095/api/llama -TimeoutSec 3 | Out-Null; exit 0 } catch { Start-Sleep 5; $t += 5 } }; exit 1"
if errorlevel 1 (
  echo LocalHarness no contesta en 4 minutos: abre LocalHarness.bat a mano y luego Autopiloto-local.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m localharness autopilot --project poeta --agent "Jefe local" --list "autopilot\poeta-local.md" --hours 6 --budget 1 --task-minutes 40 --check "node --test" --continuo
echo.
echo Autopiloto terminado. Informe: data\autopilot\poeta-local-informe.md
pause

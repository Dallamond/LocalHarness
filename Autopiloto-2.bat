@echo off
rem Segunda jornada del autopiloto: lista autopilot\poeta-2.md (19 parches de código con tests) en el proyecto «poeta».
rem Doble clic con LocalHarness YA ABIERTO y los modelos arrancados. Como mucho 5 h y 10 $ (estimados). Si lo cierras y
rem lo vuelves a abrir, sigue donde se quedó. Informe: data\autopilot\poeta-2-informe.md (se actualiza tras cada parche).
chcp 65001 >nul
title LocalHarness - Autopiloto 2 (no cierres esta ventana)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m localharness autopilot --project poeta --agent "Jefe de obra" --list "autopilot\poeta-2.md" --hours 5 --budget 10 --task-minutes 30 --check "node --test"
echo.
echo Autopiloto terminado. Informe: data\autopilot\poeta-2-informe.md
pause

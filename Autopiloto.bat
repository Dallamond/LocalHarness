@echo off
rem Doble clic con LocalHarness YA ABIERTO y los dos modelos arrancados: hace sola la lista de parches de
rem autopilot\poeta.md en el proyecto «poeta» durante 6 h como mucho (tope nominal de 15 $). Si lo cierras y lo vuelves a abrir, sigue
rem donde se quedó. El informe queda en data\autopilot\poeta-informe.md (se actualiza tras cada parche).
chcp 65001 >nul
title LocalHarness - Autopiloto (no cierres esta ventana)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m localharness autopilot --project poeta --agent "Jefe de obra" --list "autopilot\poeta.md" --hours 6 --budget 15 --task-minutes 30 --check "node --test"
echo.
echo Autopiloto terminado. Informe: data\autopilot\poeta-informe.md
pause

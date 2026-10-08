@echo off
rem Autopiloto 100 % LOCAL: el «Jefe local» hace la lista autopilot\poeta-local.md en el proyecto «poeta» sin Claude
rem (0 $). Cuando se acaba la lista, el modelo local propone los parches siguientes y sigue (--continuo) hasta 10 h.
rem Doble clic con LocalHarness YA ABIERTO. Modelos recomendados (medido el 08/10): gpt-oss-20b en la 3060 con
rem n_cpu_moe 4 y Qwen3.5-4B en la 1060, con las GPU separadas. Informe: data\autopilot\poeta-local-informe.md
chcp 65001 >nul
title LocalHarness - Autopiloto local (no cierres esta ventana)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m localharness autopilot --project poeta --agent "Jefe local" --list "autopilot\poeta-local.md" --hours 10 --budget 1 --task-minutes 40 --check "node --test" --continuo
echo.
echo Autopiloto terminado. Informe: data\autopilot\poeta-local-informe.md
pause

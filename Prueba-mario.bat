@echo off
rem Comparativa de modelos: «Supersalto» desde cero con los modelos que tengas cargados en LocalHarness, los 39
rem parches de autopilot\mario-base.md y al final el examen oculto (nota en data\examenes). 100 % local, 0 $.
rem Antes: carga en LocalHarness la pareja de modelos que quieras probar. No lo lances con otro autopiloto en marcha.
chcp 65001 >nul
cd /d "%~dp0"
set /p NOMBRE=Nombre de esta prueba (p. ej. qwen36-qwen4b):
if "%NOMBRE%"=="" exit /b 1
title LocalHarness - Prueba mario-%NOMBRE% (no cierres esta ventana)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\prueba-mario.ps1" -Nombre "%NOMBRE%"
echo.
pause

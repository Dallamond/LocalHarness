@echo off
rem Doble clic: prepara lo que falte (la primera vez), arranca LocalHarness y abre el navegador.
chcp 65001 >nul
title LocalHarness - no cierres esta ventana mientras lo uses
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto :prepare
if not exist "web\dist\index.html" goto :prepare
goto :run

:prepare
echo Primera vez en este PC: preparando LocalHarness. Tarda unos minutos...
call "%~dp0scripts\preparar.bat"
if errorlevel 1 goto :error

:run
".venv\Scripts\python.exe" -m localharness start
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Algo ha fallado. Lee el mensaje de arriba; si no sabes que es, copialo y pasaselo a Claude.
pause
exit /b 1

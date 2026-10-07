@echo off
rem Doble clic: baja la ultima version de main y vuelve a preparar (dependencias y web).
chcp 65001 >nul
title Actualizar LocalHarness
cd /d "%~dp0"
echo Actualizando LocalHarness...
git checkout -- web/package-lock.json 2>nul
git checkout main
if errorlevel 1 goto :error
git pull origin main
if errorlevel 1 goto :error
call "%~dp0scripts\preparar.bat"
if errorlevel 1 goto :error
echo.
echo Listo. Abre LocalHarness con su icono o con LocalHarness.bat.
pause
exit /b 0

:error
echo.
echo La actualizacion ha fallado.
echo - "Could not resolve host": este PC no tiene internet ahora o la red no deja llegar a GitHub.
echo - "Your local changes would be overwritten": tienes cambios a mano; pasale el mensaje a Claude.
pause
exit /b 1

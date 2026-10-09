@echo off
rem Banco de pruebas: el mismo proyecto desde cero para cada contendiente (banco\contendientes\*.json), uno detrás
rem de otro, con el examen oculto tras cada parche. Cada contendiente carga sus propios modelos. Resultados en
rem http://127.0.0.1:8095/banco y en data\banco. Doble clic con LocalHarness YA ABIERTO y sin otro autopiloto en marcha.
rem Si se corta, se retoma con: .venv\Scripts\python.exe -m localharness banco seguir data\banco\<prueba>-<modalidad>\<carpeta>
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -m localharness banco lista
echo.
set /p PRUEBA=Prueba (p. ej. cuentas-claras o supersalto):
if "%PRUEBA%"=="" exit /b 1
set MODALIDAD=guiada
set /p MODALIDAD=Modalidad [guiada / libre, Intro = guiada]:
set /p CONTENDIENTES=Contendientes separados por espacios (p. ej. gptoss-qwen4b gptoss-solo):
if "%CONTENDIENTES%"=="" exit /b 1
title LocalHarness - Banco %PRUEBA% %MODALIDAD% (no cierres esta ventana)
".venv\Scripts\python.exe" -m localharness banco correr --prueba %PRUEBA% --modalidad %MODALIDAD% --contendiente %CONTENDIENTES%
echo.
echo Banco terminado. Resultados: http://127.0.0.1:8095/banco
pause

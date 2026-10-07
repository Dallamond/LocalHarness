@echo off
rem Instala o pone al dia lo que necesita LocalHarness: entorno de Python, dependencias y la web compilada.
rem Lo llaman LocalHarness.bat (la primera vez) y Actualizar.bat.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" goto :deps
echo [1/3] Creando el entorno de Python...
where py >nul 2>nul
if not errorlevel 1 py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if exist ".venv\Scripts\python.exe" goto :deps
echo No encuentro Python 3. Instalalo desde https://www.python.org/downloads/
echo y marca la casilla "Add python.exe to PATH". Luego vuelve a abrir LocalHarness.
exit /b 1

:deps
echo [2/3] Instalando dependencias de Python...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e .[server]
if errorlevel 1 exit /b 1

where npm >nul 2>nul
if not errorlevel 1 goto :web
if exist "web\dist\index.html" (
  echo Aviso: no encuentro Node.js; uso la web que ya estaba compilada.
  exit /b 0
)
echo No encuentro Node.js (hace falta para compilar la web la primera vez).
echo Instalalo desde https://nodejs.org (version LTS) y vuelve a abrir LocalHarness.
exit /b 1

:web
echo [3/3] Compilando la web...
pushd web
call npm install --no-audit --no-fund --loglevel=error
if errorlevel 1 goto :weberr
call npm run build
if errorlevel 1 goto :weberr
popd
exit /b 0

:weberr
popd
exit /b 1

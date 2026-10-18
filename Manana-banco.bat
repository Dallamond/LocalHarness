@echo off
rem Jornada larga del banco con las dos GPU (M40 + 3060): abre LocalHarness si no esta abierto, encola la jornada
rem (scripts\encolar_manana.py: A/B del reparto, 2.a tirada de la referencia, modelos nuevos si estan descargados y
rem cuentas-claras guiada) y arranca la cola. Es seguro repetirlo: no duplica tandas. Resultados: http://127.0.0.1:8095/banco
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "try { (Invoke-WebRequest http://127.0.0.1:8095/api/health -UseBasicParsing -TimeoutSec 3) | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo LocalHarness no estaba abierto: lo arranco...
  start "LocalHarness (no cierres esta ventana)" /min ".venv\Scripts\python.exe" -m localharness serve
  powershell -NoProfile -Command "for ($i=0; $i -lt 40; $i++) { try { Invoke-WebRequest http://127.0.0.1:8095/api/health -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { Start-Sleep 3 } }; exit 1"
)
".venv\Scripts\python.exe" scripts\encolar_manana.py --aplicar --empezar
echo.
echo Cola en marcha. Resultados: http://127.0.0.1:8095/banco
pause

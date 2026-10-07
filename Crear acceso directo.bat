@echo off
rem Doble clic: pone el icono de LocalHarness en el escritorio y en el menu Inicio.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$sh = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $s = $sh.CreateShortcut((Join-Path $dir 'LocalHarness.lnk'));" ^
  "  $s.TargetPath = (Join-Path '%~dp0' 'LocalHarness.bat');" ^
  "  $s.WorkingDirectory = '%~dp0';" ^
  "  $s.IconLocation = (Join-Path '%~dp0' 'scripts\localharness.ico');" ^
  "  $s.Description = 'Oficina de agentes LocalHarness';" ^
  "  $s.WindowStyle = 7;" ^
  "  $s.Save() }"
if errorlevel 1 (
  echo No se pudo crear el acceso directo.
  pause
  exit /b 1
)
echo Hecho: tienes LocalHarness en el escritorio y en el menu Inicio.
pause

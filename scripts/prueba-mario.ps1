# Comparativa de modelos con «Supersalto»: copia limpia del proyecto en el Parche 000, los 39 parches de
# autopilot/mario-base.md con el Jefe local y, al final, el examen oculto (banco/pruebas/supersalto/examen). Los modelos son los que
# estén cargados en LocalHarness (el autopiloto vuelve a arrancar los últimos si se caen).
# Uso: powershell -File scripts\prueba-mario.ps1 -Nombre qwen36  (lo llama Prueba-mario.bat)
# -Seguir: la copia y el proyecto ya existen (p. ej. la prueba se cortó porque LocalHarness estaba cerrado): no los
# vuelve a crear y archiva el estado anterior del autopiloto para empezar la lista desde el principio.
# -Continuar: como -Seguir, pero conserva el estado (sigue por donde iba y adopta la tarea que siga viva).
param([Parameter(Mandatory = $true)][string]$Nombre, [double]$Horas = 12, [switch]$Seguir, [switch]$Continuar)
if ($Continuar) { $Seguir = $true }
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$base = "D:\LocalHarness-proyectos\mario"
$destino = "D:\LocalHarness-proyectos\mario-$Nombre"
$commit0 = "b97d35c"  # Parche 000: encargo, diseños de nivel, package.json y primer test
$api = "http://127.0.0.1:8095"

if ($Nombre -notmatch '^[\w.-]+$') { throw "El nombre solo puede llevar letras, números, punto, guion y guion bajo" }
if ((Test-Path $destino) -and -not $Seguir) { throw "Ya existe ${destino}: usa otro nombre o -Seguir para retomarla" }

# el 09/10 la primera prueba arrancó con LocalHarness reiniciándose y los 3 primeros parches no encontraron el
# servidor: se espera a que conteste (hasta 4 min), como los .bat del autopiloto
$listo = $false
for ($t = 0; $t -lt 240 -and -not $listo; $t += 5) {
    try { Invoke-WebRequest -UseBasicParsing "$api/api/llama" -TimeoutSec 3 | Out-Null; $listo = $true }
    catch { if ($t -eq 0) { Write-Host "Esperando a que LocalHarness conteste..." }; Start-Sleep 5 }
}
if (-not $listo) { throw "LocalHarness no contesta en 4 minutos: abre LocalHarness.bat y vuelve a lanzar la prueba" }

$lista = Join-Path $raiz "autopilot\mario-$Nombre.md"  # el estado del autopiloto va por nombre de lista
if ($Seguir) {
    $estado = Join-Path $raiz "data\autopilot\mario-$Nombre-estado.json"
    if ((Test-Path $estado) -and -not $Continuar) {
        Rename-Item $estado "mario-$Nombre-estado-$(Get-Date -Format 'yyyyMMdd-HHmm').json"
        Write-Host "Estado anterior archivado: la lista empieza desde el parche 1"
    }
} else {
    Write-Host "Copia limpia del proyecto en el Parche 000 -> $destino"
    git clone --quiet $base $destino
    git -C $destino checkout --quiet -B main $commit0
    git -C $destino remote remove origin

    # por la API, no por la CLI: la CLI marca como interrumpidas las tareas que estén en marcha
    $cuerpo = @{ name = "mario-$Nombre"; repo_path = $destino } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$api/api/projects" -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($cuerpo)) | Out-Null
    Copy-Item (Join-Path $raiz "autopilot\mario-base.md") $lista
}


& (Join-Path $raiz ".venv\Scripts\python.exe") -m localharness autopilot --project "mario-$Nombre" --agent "Jefe local" `
    --list $lista --hours $Horas --budget 1 --task-minutes 45 --check "npm test"

# los modelos se miran al final: al empezar puede que aún no estén cargados (los arranca el autopiloto)
$llama = Invoke-RestMethod "$api/api/llama"
$modelos = ($llama.servers | ForEach-Object { "$($_.id): $([IO.Path]::GetFileNameWithoutExtension([string]$_.status.model))" }) -join " · "
Write-Host "`nModelos: $modelos"
$examenes = Join-Path $raiz "data\examenes"
New-Item -ItemType Directory -Force $examenes | Out-Null
Set-Content -Encoding utf8 (Join-Path $examenes "mario-$Nombre-modelos.txt") "$(Get-Date -Format 'dd/MM/yyyy HH:mm') · $modelos"

Write-Host "`nExamen oculto:"
node (Join-Path $raiz "banco\puntuar.mjs") (Join-Path $raiz "banco\pruebas\supersalto\examen") $destino $Nombre
Write-Host "Informe del autopiloto: data\autopilot\mario-$Nombre-informe.md"

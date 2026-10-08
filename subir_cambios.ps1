# subir_cambios.ps1: sube a GitHub los cambios hechos (por ejemplo los que pida el profesor) y sigue el build de Jenkins.
# Uso (doble clic en subir_cambios.bat, o desde la carpeta del proyecto):
#   .\subir_cambios.ps1
#   .\subir_cambios.ps1 -Mensaje "Endpoint nuevo pedido por el profesor"
#   .\subir_cambios.ps1 -JenkinsUrl "https://xxxx.trycloudflare.com" -JenkinsClave "la-clave"   (si Jenkins corre en OTRO PC)
# Hace: revisa errores de sintaxis de Python > muestra los cambios > pide confirmacion > commit > git pull (sin borrar nada)
#       > git push > espera el build de Jenkins y muestra si salio en verde o en rojo.
# NUNCA usa --force ni reset --hard: el historial de commits no se pierde.
param(
    [string]$Mensaje,
    [switch]$Confirmar,
    [switch]$SinSeguimiento,
    [string]$JenkinsUrl = "http://localhost:8080",
    [string]$JenkinsClave
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Aviso($t) { Write-Host $t -ForegroundColor Yellow }
function Fallo($t) { Write-Host "`nERROR: $t" -ForegroundColor Red; exit 1 }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fallo "git no esta instalado" }
cmd /c "git rev-parse --is-inside-work-tree >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fallo "esta carpeta no es un repositorio git. Para subir cambios hay que trabajar en una carpeta clonada con: git clone https://github.com/biltormenta/parcial-big-data.git" }

$nombre = (git config user.name); $correo = (git config user.email)
if (-not $nombre -or -not $correo) {
    Fallo "git no sabe quien eres. Ejecuta una sola vez:`n  git config --global user.name `"Tu Nombre`"`n  git config --global user.email `"correo-de-tu-cuenta-de-github`""
}
$rama = (git branch --show-current)
if ($rama -ne "main") { Aviso "AVISO: estas en la rama '$rama'. Jenkins solo construye cambios que llegan a 'main'." }

# ---------------------------------------------------------------- 1. Sintaxis de Python
Paso "1. Revisando que el codigo Python no tenga errores de sintaxis"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if ($py) {
    $archivos = @(Get-ChildItem app, tests, spark_jobs -Recurse -Filter *.py -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    & $py.Source -c "import ast,sys; [ast.parse(open(f,encoding='utf-8').read(), f) for f in sys.argv[1:]]; print('sintaxis OK en', len(sys.argv)-1, 'archivos')" @archivos
    if ($LASTEXITCODE -ne 0) { Fallo "hay un error de sintaxis (se ve arriba, con el archivo y la linea). Corrigelo y vuelve a ejecutar: no se subio nada." }
} else {
    Aviso "Python no esta instalado en este PC: se omite la revision (Jenkins igual correra las pruebas)."
}

# ---------------------------------------------------------------- 2. Cambios
Paso "2. Cambios que se van a subir"
git add -A
$cambios = @(git status --short)
if ($cambios.Count -eq 0) { Write-Host "No hay cambios para subir."; exit 0 }
$cambios | ForEach-Object { Write-Host "  $_" }

# seguridad: nunca subir el .env ni claves
$prohibidos = @(git diff --cached --name-only | Where-Object { $_ -match '(^|/)\.env$' -or $_ -match 'kaggle\.json$' })
# el patron se arma en pedazos para que esta misma linea no se detecte a si misma como una clave
$patron = 'gh' + 'p_[A-Za-z0-9]{20,}|github' + '_pat_[A-Za-z0-9_]{20,}|KAGGLE' + '_KEY=[A-Za-z0-9]{8,}'
$claves = @(git diff --cached | Select-String -Pattern $patron)
if ($prohibidos.Count -gt 0 -or $claves.Count -gt 0) {
    git reset -q
    if ($prohibidos.Count -gt 0) { $motivo = "el archivo $($prohibidos -join ', ') no se debe subir" } else { $motivo = "se detecto una clave o token escrito dentro de los cambios" }
    Fallo "$motivo. No se subio nada: quita esa credencial y vuelve a ejecutar."
}

if (-not $Mensaje) {
    $Mensaje = Read-Host "`nMensaje del commit (Enter = 'Cambio pedido en la sustentacion')"
    if (-not $Mensaje) { $Mensaje = "Cambio pedido en la sustentacion" }
}
if (-not $Confirmar) {
    $r = Read-Host "Subir estos cambios a GitHub como '$nombre'? (S/N)"
    if ($r -notmatch '^[sS]') { git reset -q; Write-Host "Cancelado. No se subio nada."; exit 0 }
}

# ---------------------------------------------------------------- Jenkins: build actual antes de subir
$jenkinsOk = $false; $prev = 0
if (-not $SinSeguimiento) {
    $clave = $JenkinsClave
    if (-not $clave -and (Test-Path ".env")) {
        $l = Select-String -Path ".env" -Pattern '^JENKINS_ADMIN_PASSWORD=(.*)$' | Select-Object -First 1
        if ($l) { $clave = $l.Matches[0].Groups[1].Value }
    }
    if ($clave) {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$clave"))
        $hd = @{ Authorization = "Basic $b64" }
        $job = "$($JenkinsUrl.TrimEnd('/'))/job/geolife-geoespacial"
        try {
            $info = Invoke-RestMethod "$job/api/json" -Headers $hd -TimeoutSec 15
            if ($info.lastBuild) { $prev = [int]$info.lastBuild.number }
            $jenkinsOk = $true
        } catch { }
    }
}

# ---------------------------------------------------------------- 3. Commit, pull, push
Paso "3. Commit y push"
git commit -q -m $Mensaje
if ($LASTEXITCODE -ne 0) { Fallo "no se pudo hacer el commit" }
git pull --no-rebase --no-edit
if ($LASTEXITCODE -ne 0) {
    Fallo "al traer los cambios de GitHub hubo un conflicto. NO se subio nada y NO se perdio nada.`nAbre los archivos marcados con <<<<<<<, deja la version correcta, y ejecuta: git add . ; git commit ; luego este script otra vez.`nNo uses --force."
}
git push
if ($LASTEXITCODE -ne 0) { Fallo "el push fallo (mira el mensaje de arriba). Si dice 'Authentication failed', inicia sesion en GitHub con la cuenta que tiene permiso en el repositorio." }
$hash = (git rev-parse --short HEAD)
Write-Host "Subido: commit $hash en '$rama'" -ForegroundColor Green

# ---------------------------------------------------------------- 4. Seguimiento de Jenkins
if ($SinSeguimiento) { exit 0 }
if (-not $jenkinsOk) {
    Aviso "`nNo pude consultar Jenkins desde este PC. Mira el build en el navegador (el job geolife-geoespacial)."
    Aviso "Si Jenkins corre en otro PC usa: .\subir_cambios.ps1 -JenkinsUrl 'https://LA-URL-DEL-TUNEL' -JenkinsClave 'LA-CLAVE'"
    exit 0
}
Paso "4. Esperando el build de Jenkins (el webhook deberia dispararlo solo)"
$n = 0
foreach ($i in 1..40) {
    Start-Sleep 3
    try { $x = Invoke-RestMethod "$job/api/json" -Headers $hd -TimeoutSec 15; if ($x.lastBuild -and [int]$x.lastBuild.number -gt $prev) { $n = [int]$x.lastBuild.number; break } } catch { }
}
if ($n -eq 0) {
    Aviso "Jenkins no arranco ningun build en 2 minutos. Causas probables: el tunel se cayo o la URL del webhook en GitHub quedo vieja."
    Aviso "Para lanzarlo a mano: Jenkins > geolife-geoespacial > Build Now."
    exit 0
}
Write-Host "Jenkins arranco el build #$n. Siguiendo el resultado..."
$t0 = Get-Date
$res = $null
foreach ($i in 1..180) {
    try {
        $b = Invoke-RestMethod "$job/$n/api/json" -Headers $hd -TimeoutSec 15
        if (-not $b.building) { $res = $b.result; break }
    } catch { }
    Write-Host ("  ... en curso ({0:N0} s)" -f ((Get-Date) - $t0).TotalSeconds)
    Start-Sleep 5
}
if ($res -eq "SUCCESS") {
    Write-Host "`nBUILD #$n EN VERDE: se construyo, paso las pruebas y se desplego." -ForegroundColor Green
} elseif ($res) {
    Write-Host "`nBUILD #$n TERMINO EN $res. No se desplego. Revisa: $job/$n/console" -ForegroundColor Red
} else {
    Aviso "`nEl build #$n sigue corriendo; revisa: $job/$n/console"
}

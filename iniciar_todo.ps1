# iniciar_todo.ps1: levanta TODO el sistema y deja listo el webhook.
# Uso (desde la carpeta del proyecto, o con doble clic en iniciar_todo.bat):
#   .\iniciar_todo.ps1               levanta todo, abre los tuneles e imprime la URL del webhook
#   .\iniciar_todo.ps1 -CargarDatos  fuerza la descarga y carga de datos aunque Mongo ya tenga puntos
#   .\iniciar_todo.ps1 -Detener      cierra los tuneles y apaga los contenedores (los datos se conservan)
# La ventana debe quedar ABIERTA: si se cierra, se cierran los tuneles y GitHub deja de llegar a Jenkins.
param(
    [switch]$CargarDatos,
    [switch]$Detener,
    [switch]$SinPruebaJenkins
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Aviso($t) { Write-Host $t -ForegroundColor Yellow }
function Fallo($t) { Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }

# Solo se tocan los tuneles de ESTE proyecto (los que apuntan a los puertos 8080 y 5000)
function CerrarTuneles {
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'localhost:(8080|5000)' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function DockerListo {
    cmd /c "docker info >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

if ($Detener) {
    Paso "Cerrando tuneles y apagando contenedores"
    CerrarTuneles
    & "$PSScriptRoot\preparar_sustentacion.ps1" -Detener
    exit 0
}

# ---------------------------------------------------------------- 1. Docker
Paso "1. Docker Desktop"
if (-not (DockerListo)) {
    $exe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $exe)) { Fallo "Docker Desktop no esta instalado" }
    Aviso "Docker no esta corriendo, abriendolo (puede tardar 1 o 2 minutos)..."
    Start-Process $exe
    $listo = $false
    foreach ($i in 1..60) { Start-Sleep 5; if (DockerListo) { $listo = $true; break } }
    if (-not $listo) { Fallo "Docker no arranco a tiempo: abrelo a mano, espera a que diga 'running' y vuelve a ejecutar" }
}
Write-Host "Docker listo"

# ---------------------------------------------------------------- 2. cloudflared
Paso "2. cloudflared (genera la URL publica)"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    Aviso "No esta instalado, instalandolo con winget..."
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cf) { Fallo "no se pudo instalar cloudflared; instalalo con: winget install Cloudflare.cloudflared" }
}
Write-Host "cloudflared: $cf"

# ---------------------------------------------------------------- 3. Sistema
Paso "3. Sistema (Mongo, Dask, Spark, API, Jenkins)"
& "$PSScriptRoot\preparar_sustentacion.ps1"
if ($LASTEXITCODE -ne 0) { Fallo "fallo el levantamiento del sistema, revisa los mensajes de arriba" }

$h = Invoke-RestMethod http://localhost:5000/health
if ($CargarDatos -or [int]$h.puntos -eq 0) {
    Paso "3b. Cargando datos (Mongo estaba vacio o se pidio -CargarDatos)"
    & "$PSScriptRoot\preparar_sustentacion.ps1" -CargarDatos
    if ($LASTEXITCODE -ne 0) { Fallo "fallo la carga de datos" }
}

$linea = Select-String -Path (Join-Path $PSScriptRoot ".env") -Pattern '^JENKINS_ADMIN_PASSWORD=(.*)$' | Select-Object -First 1
if (-not $linea) { Fallo "no encuentro JENKINS_ADMIN_PASSWORD en el archivo .env" }
$pw = $linea.Matches[0].Groups[1].Value

Write-Host "Esperando a Jenkins..."
$jOk = $false
foreach ($i in 1..60) {
    try { if ((Invoke-WebRequest http://localhost:8080/login -UseBasicParsing).StatusCode -eq 200) { $jOk = $true; break } } catch { }
    Start-Sleep 3
}
if (-not $jOk) { Fallo "Jenkins no responde en http://localhost:8080" }

# ---------------------------------------------------------------- 4. Tuneles
Paso "4. Tuneles publicos"
CerrarTuneles   # si habia tuneles viejos de una ejecucion anterior, se cierran para no duplicar

function AbrirTunel($puerto, $log) {
    Remove-Item $log -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $cf -ArgumentList @("tunnel", "--url", "http://localhost:$puerto", "--no-autoupdate", "--logfile", $log) -WindowStyle Hidden -PassThru
    $url = $null
    foreach ($i in 1..40) {
        Start-Sleep 2
        if (Test-Path $log) {
            $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
            if ($m) { $url = $m.Matches[0].Value; break }
        }
    }
    if (-not $url) { Fallo "no se obtuvo la URL del tunel del puerto $puerto (mira el log: $log)" }
    return [pscustomobject]@{ Puerto = $puerto; Log = $log; Proceso = $p; Url = $url }
}

$tJenkins = AbrirTunel 8080 (Join-Path $env:TEMP "tunel_jenkins.log")
$tApi = AbrirTunel 5000 (Join-Path $env:TEMP "tunel_api.log")

# Comprueba que GitHub podria llegar a Jenkins: le manda un "ping" como el que manda GitHub
$webhookOk = $false
foreach ($i in 1..20) {
    try {
        $r = Invoke-WebRequest -Uri "$($tJenkins.Url)/github-webhook/" -Method POST -ContentType "application/json" `
            -Headers @{ "X-GitHub-Event" = "ping" } -Body '{"zen":"prueba"}' -UseBasicParsing
        if ($r.StatusCode -eq 200) { $webhookOk = $true; break }
    } catch { }
    Start-Sleep 3
}

$webhook = "$($tJenkins.Url)/github-webhook/"
try { Set-Clipboard -Value $webhook } catch { }

# Mantiene el equipo despierto mientras esta ventana siga abierta (no cambia la configuracion de energia)
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
# (los valores se escriben como [uint32] porque PowerShell 5.1 lee 0x80000001 como numero negativo)
[void][Win32.Power]::SetThreadExecutionState([uint32]2147483649)   # ES_CONTINUOUS + ES_SYSTEM_REQUIRED

function MostrarResumen {
    Write-Host ""
    Write-Host "=====================================================================" -ForegroundColor Green
    Write-Host " SISTEMA LISTO" -ForegroundColor Green
    Write-Host "=====================================================================" -ForegroundColor Green
    Write-Host " PEGAR EN EL WEBHOOK DE GITHUB (ya esta copiada al portapapeles):"
    Write-Host "   $webhook" -ForegroundColor Yellow
    Write-Host "   GitHub > Settings > Webhooks > editar > Payload URL. Content type: application/json."
    Write-Host "   Evento: Just the push event. Secret: vacio."
    if ($webhookOk) { Write-Host "   Prueba: Jenkins respondio al ping a traves del tunel (OK)." -ForegroundColor Green }
    else { Aviso "   AVISO: el ping de prueba no respondio todavia; espera 1 minuto y vuelve a probar." }
    Write-Host ""
    Write-Host " Jenkins   local:   http://localhost:8080"
    Write-Host "           publico: $($tJenkins.Url)"
    Write-Host "           usuario: admin    contrasena: $pw"
    Write-Host " API/mapa  local:   http://localhost:5000"
    Write-Host "           publico: $($tApi.Url)   (para ver el mapa y los endpoints desde otra red)"
    Write-Host " Spark: http://localhost:8081    Dask: http://localhost:8787"
    Write-Host ""
    Write-Host " Dejar esta ventana ABIERTA. Para apagar todo: .\iniciar_todo.ps1 -Detener"
    Write-Host "=====================================================================" -ForegroundColor Green
}
MostrarResumen

# ---------------------------------------------------------------- 5. Primera prueba del pipeline
if (-not $SinPruebaJenkins) {
    Paso "5. Probando el pipeline de Jenkins (solo la primera vez)"
    try {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$pw"))
        $hd = @{ Authorization = "Basic $b64" }
        $ses = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $job = "http://localhost:8080/job/geolife-geoespacial"
        $info = Invoke-RestMethod "$job/api/json" -Headers $hd -WebSession $ses
        if ($info.lastBuild) {
            Write-Host "El job ya tiene builds (ultimo: #$($info.lastBuild.number)), no se lanza uno nuevo."
        } else {
            $crumb = Invoke-RestMethod "http://localhost:8080/crumbIssuer/api/json" -Headers $hd -WebSession $ses
            $hd2 = @{ Authorization = "Basic $b64"; $crumb.crumbRequestField = $crumb.crumb }
            Invoke-WebRequest "$job/build" -Method POST -Headers $hd2 -WebSession $ses -UseBasicParsing | Out-Null
            Write-Host "Build #1 lanzado, esperando el resultado (puede tardar unos minutos)..."
            $res = $null
            foreach ($i in 1..120) {
                Start-Sleep 8
                try {
                    $b = Invoke-RestMethod "$job/1/api/json" -Headers $hd -WebSession $ses
                    if (-not $b.building) { $res = $b.result; break }
                } catch { }
            }
            if ($res -eq "SUCCESS") { Write-Host "Pipeline de Jenkins: SUCCESS" -ForegroundColor Green }
            else { Aviso "Pipeline de Jenkins: $res (revisa http://localhost:8080/job/geolife-geoespacial/1/console)" }
        }
    } catch {
        Aviso "No se pudo probar el pipeline automaticamente: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------- 6. Vigilancia
# Si un tunel se cae, se vuelve a abrir; la URL cambia, asi que hay que actualizar el webhook
Write-Host "`nVigilando los tuneles (Ctrl+C para salir)..." -ForegroundColor Cyan
try {
    while ($true) {
        Start-Sleep 20
        foreach ($t in @($tJenkins, $tApi)) {
            if ($t.Proceso.HasExited) {
                Aviso "`nEl tunel del puerto $($t.Puerto) se cayo, reabriendolo..."
                $nuevo = AbrirTunel $t.Puerto $t.Log
                $t.Proceso = $nuevo.Proceso
                $t.Url = $nuevo.Url
                if ($t.Puerto -eq 8080) {
                    $webhook = "$($t.Url)/github-webhook/"
                    try { Set-Clipboard -Value $webhook } catch { }
                }
                Aviso "LA URL CAMBIO. Actualiza el webhook de GitHub si era el de Jenkins."
                MostrarResumen
            }
        }
    }
} finally {
    [void][Win32.Power]::SetThreadExecutionState([uint32]2147483648)   # ES_CONTINUOUS: vuelve a permitir suspender
    CerrarTuneles
    Write-Host "Tuneles cerrados. Los contenedores siguen corriendo (apagar: .\iniciar_todo.ps1 -Detener)."
}

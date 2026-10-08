# prepara el sistema completo en un computador nuevo (windows + docker desktop)
# uso, desde la carpeta del proyecto (donde esta docker-compose.yml):
#   .\preparar_sustentacion.ps1                    levanta todo
#   .\preparar_sustentacion.ps1 -CargarDatos       ademas descarga, limpia, carga a mongo y corre spark (tarda)
#   .\preparar_sustentacion.ps1 -Detener           apaga todo (los datos se conservan)
param(
    [string]$RepoUrl = "https://github.com/biltormenta/parcial-big-data.git",
    [switch]$CargarDatos,
    [switch]$Detener
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fallo($t) { Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }

if (-not (Test-Path "docker-compose.yml")) { Fallo "ejecuta el script desde la carpeta del proyecto (la que tiene docker-compose.yml)" }

Paso "1. Docker"
docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fallo "Docker Desktop no esta corriendo, abrelo y espera a que diga 'running'" }

if ($Detener) {
    docker compose --profile jobs --profile tests down
    Write-Host "apagado, los datos siguen guardados en los volumenes" -ForegroundColor Green
    exit 0
}

$memGb = [math]::Round([long](docker info --format '{{.MemTotal}}') / 1GB, 1)
Write-Host "memoria disponible para docker: $memGb GB"
if ($memGb -lt 6) {
    Write-Host "AVISO: con menos de 6 GB el sistema puede quedarse sin memoria. Sube el limite en Docker Desktop > Settings > Resources, o baja la muestra con OBJETIVO_REGISTROS=1200000 en el .env" -ForegroundColor Yellow
}

Paso "2. Puertos libres"
$ocupados = @()
foreach ($puerto in 8080, 5000, 8081, 8787, 27017) {
    $uso = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue
    if ($uso) {
        # si ya es un contenedor de este proyecto no es problema
        $mio = docker ps --filter "publish=$puerto" --filter "label=com.docker.compose.project=geolife" --format '{{.Names}}'
        if (-not $mio) { $ocupados += $puerto }
    }
}
if ($ocupados.Count -gt 0) { Fallo "puertos ocupados por otros programas: $($ocupados -join ', '). Cierralos y vuelve a correr" }
Write-Host "ok"

Paso "3. Archivo .env"
if (-not (Test-Path ".env")) {
    $pw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
    @"
JENKINS_ADMIN_PASSWORD=$pw
REPO_URL=$RepoUrl
KAGGLE_USERNAME=
KAGGLE_KEY=
OBJETIVO_REGISTROS=2000000
"@ | Set-Content ".env" -Encoding ascii
    Write-Host ".env creado. Usuario de Jenkins: admin   Contrasena: $pw" -ForegroundColor Green
    Write-Host "guarda esa contrasena, tambien queda dentro del archivo .env (no se sube a github)"
} else {
    Write-Host ".env ya existe, se conserva"
}

Paso "4. Construir y levantar los servicios (la primera vez tarda 10 a 15 minutos)"
docker compose up -d --build --wait mongo dask-scheduler dask-worker spark-master spark-worker api jenkins
if ($LASTEXITCODE -ne 0) { Fallo "no se pudieron levantar los servicios, revisa: docker compose logs" }

Paso "5. Revisar la API"
$ok = $false
foreach ($i in 1..20) {
    try { $h = Invoke-RestMethod http://localhost:5000/health; $ok = $true; break } catch { Start-Sleep 3 }
}
if (-not $ok) { Fallo "la API no responde en http://localhost:5000/health" }
Write-Host "API ok, puntos en mongo: $($h.puntos)"

if ($CargarDatos) {
    Paso "6. Cargar datos (descarga de Kaggle, limpieza con Dask, carga a Mongo)"
    docker compose --profile jobs run --rm ingesta
    if ($LASTEXITCODE -ne 0) { Fallo "fallo la ingesta" }

    Paso "7. Agregaciones con Spark"
    docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 `
        --conf spark.driver.host=spark-master --driver-memory 512m --executor-memory 700m /opt/jobs/agregaciones.py
    if ($LASTEXITCODE -ne 0) { Fallo "fallo el job de Spark" }
} elseif ([int]$h.puntos -eq 0) {
    Write-Host "`nAVISO: mongo esta vacio. Corre de nuevo con -CargarDatos (o marca RECARGAR_DATOS en Jenkins)" -ForegroundColor Yellow
}

Paso "Listo"
Write-Host "API y mapa:   http://localhost:5000"
Write-Host "Jenkins:      http://localhost:8080   (usuario admin, contrasena en .env)"
Write-Host "Spark UI:     http://localhost:8081"
Write-Host "Dask:         http://localhost:8787"
Write-Host "`nfalta el tunel y el webhook (ver README, seccion 'Maquina de la sustentacion', pasos 5 y 6)"

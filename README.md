# Big Data: procesamiento y consulta de datos geoespaciales con despliegue continuo

Sistema completo sobre trayectorias GPS reales (Geolife, Pekín): descarga automática desde Kaggle, limpieza con Dask, almacenamiento en MongoDB como GeoJSON con índice `2dsphere`, agregaciones espaciales y temporales con Spark, consultas geoespaciales, API Flask y pipeline de Jenkins que despliega solo cuando el código cambia.

Dataset: [Microsoft Geolife GPS Trajectory Dataset](https://www.kaggle.com/datasets/arashnic/microsoft-geolife-gps-trajectory-dataset) (Microsoft Research Asia). Se descarga con la API de Kaggle (`kagglehub`) desde el propio pipeline. Es público y no exige token; si hay `KAGGLE_USERNAME`/`KAGGLE_KEY` en el `.env` o en las credenciales de Jenkins, se usan.

Informe técnico: [`docs/Informe_Tecnico_Geolife.docx`](docs/Informe_Tecnico_Geolife.docx).

## Arquitectura

```
Kaggle --(kagglehub)--> ingesta ---> Dask (scheduler + 2 workers) ---> MongoDB (GeoJSON + 2dsphere)
                                          |                                   |  ^
                                          v                                   v  |
                                   Parquet limpio (/data)            Spark (master + 2 workers)
                                                                     MongoDB Spark Connector
                                                                              |
                                                                              v
GitHub --push/webhook--> Jenkins --build/pytest/smoke/deploy--> API Flask (consultas + resultados Spark) + mapa Leaflet
```

| Servicio | Imagen | Puerto |
|---|---|---|
| mongo | mongo:7 | 27017 |
| dask-scheduler / dask-worker (x2) | build propio (`docker/app.Dockerfile`) | 8787 (dashboard) |
| spark-master / spark-worker (x2) | build propio (`docker/spark.Dockerfile`, con el connector) | 8081 (UI) |
| api | build propio | 5000 |
| jenkins | build propio (`docker/jenkins`), con JCasC | 8080 |

## Requisitos
Docker Desktop (con WSL2) con al menos 6 GB de memoria asignada, Git, y los puertos 8080, 5000, 8081, 8787 y 27017 libres.

## Levantar el sistema desde cero (Windows)
```powershell
git clone https://github.com/biltormenta/parcial-big-data.git
cd parcial-big-data
.\preparar_sustentacion.ps1 -CargarDatos
```
El script crea el `.env` (con una contraseña aleatoria para Jenkins, que imprime al final), revisa la memoria y los puertos, construye las imágenes, levanta todo, comprueba la API y carga los datos. La primera vez tarda entre 15 y 25 minutos. Sin `-CargarDatos` solo levanta los servicios. Para apagar: `.\preparar_sustentacion.ps1 -Detener` (los datos se conservan en volúmenes de Docker).

Paso a paso manual, equivalente:
```bash
cp .env.example .env            # editar la contraseña de Jenkins y REPO_URL
docker compose up -d --build --wait mongo dask-scheduler dask-worker spark-master spark-worker api jenkins
docker compose --profile jobs run --rm ingesta
docker compose exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 \
    --conf spark.driver.host=spark-master --driver-memory 512m --executor-memory 700m /opt/jobs/agregaciones.py
```

## Qué hace cada parte
**Ingesta y limpieza (Dask).** Lee los `.plt` de forma particionada (un archivo, una partición), y descarta: coordenadas nulas, coordenadas fuera de rango (lat -90..90, lon -180..180), fechas inválidas y duplicados exactos (mismo usuario, trayectoria y momento). La altitud `-777` es el valor "sin dato" de Geolife y se guarda como nula. La hora se guarda en UTC y los campos `hora`, `dia_semana` y `mes` en hora local de Pekín (UTC+8). Cada fila se transforma en un punto GeoJSON `[lon, lat]` y se carga a MongoDB por lotes desde los workers; el índice `2dsphere` se crea al final porque cargar con índice es mucho más lento.

Se trabaja con una muestra de unos 2 millones de registros (el mínimo exigido es 1 millón); el dataset completo tiene cerca de 25 millones de puntos, y la descarga completa está automatizada. Resultado de la última corrida: 1.922.109 registros leídos, 43.429 duplicados descartados y **1.878.680 cargados**. En esta muestra no hubo nulos ni coordenadas fuera de rango.

**Procesamiento (Spark).** Lee desde MongoDB con el MongoDB Spark Connector y escribe colecciones nuevas: `spark_grilla` (conteo por celda de 0,01°), `spark_zonas_calientes` (celdas sobre el percentil 99), `spark_por_hora`, `spark_por_dia` y `spark_por_mes`. La suma de la grilla (1.878.680) coincide con los puntos en Mongo.

**Consultas geoespaciales.** `$near` (por radio), `$geoWithin` (polígono) y una agregación con `$geoNear`. Todas reciben parámetros.

**API (Flask).**
| Endpoint | Descripción |
|---|---|
| `GET /health` | estado y cantidad de puntos |
| `GET /api/cercanos?lat=&lon=&radio=&limit=` | puntos dentro del radio (metros), del más cercano al más lejano |
| `POST /api/poligono?limit=` | cuerpo: GeoJSON `Polygon`/`MultiPolygon` (o `Feature`); devuelve lo que cae dentro |
| `GET /api/geonear?lat=&lon=&radio=&por=hora\|dia_semana\|mes\|anio` | agregación con `$geoNear` |
| `GET /api/spark/{grilla\|zonas\|hora\|dia\|mes}?limit=` | resultados calculados con Spark |
| `GET /` | mapa Leaflet (opcional) |

Ejemplos:
```bash
curl "http://localhost:5000/api/cercanos?lat=39.9985&lon=116.3265&radio=500&limit=10"
curl -X POST "http://localhost:5000/api/poligono?limit=100" -H "Content-Type: application/json" \
  -d '{"type":"Polygon","coordinates":[[[116.30,39.98],[116.34,39.98],[116.34,40.01],[116.30,40.01],[116.30,39.98]]]}'
curl "http://localhost:5000/api/geonear?lat=39.9985&lon=116.3265&radio=1000&por=hora"
curl "http://localhost:5000/api/spark/zonas?limit=5"
```

**Dask frente a Spark.** Misma operación (conteo por celda de grilla de 0,01° sobre el Parquet limpio, 1.878.680 puntos), mediana de 3 corridas tras una de calentamiento:

| Motor | Workers | Tiempo (s) | Memoria pico (MB, RSS) |
|---|---|---|---|
| Dask | 1 | 0,72 | 481 |
| Dask | 2 | 0,43 | 992 |
| Spark | 1 | 1,22 | 491 |
| Spark | 2 | 1,08 | 1033 |

Ambos motores devuelven lo mismo: 14.185 celdas y 1.878.680 puntos. El análisis completo está en el informe técnico. Se reproduce con `python -m app.benchmark_dask` (dentro del contenedor `api`) y `spark_jobs/benchmark_spark.py <n_workers>` (con `spark-submit`).

## Pruebas
- **Unitarias** (8, no necesitan Mongo): `docker run --rm geolife-app:latest pytest tests/unit -v`
- **De humo contra la API** (12, siembran puntos de prueba en el Atlántico y los borran al terminar): `docker compose --profile tests run --rm --build pruebas-api`

## Integración y despliegue continuo (Jenkins)
El `Jenkinsfile` hace: checkout, construcción de imágenes, pruebas con `pytest` (`tests/unit`), levantamiento de una pila de pruebas aislada (proyecto `geolife-ci`), pruebas contra la API (`tests/smoke`) y despliegue. Si una etapa falla, las siguientes no se ejecutan y no se despliega nada. Se comprobó rompiendo una prueba a propósito: el build falló en pytest y "Desplegar" quedó omitido. El parámetro `RECARGAR_DATOS` ejecuta además la descarga, la ingesta y Spark.

Jenkins se configura solo con JCasC (`docker/jenkins/casc.yaml`): usuario `admin` con la contraseña del `.env`, credenciales `kaggle-username` y `kaggle-key` tomadas del entorno (nunca del repositorio) y el job `geolife-geoespacial` con disparador `githubPush()`.

**Webhook de GitHub comprobado:** con el webhook creado, un `git push` a `main` dispara el build solo ("Started by GitHub push"), que construye, prueba y despliega.

## Cambios que puede pedir el profesor (ya preparados)
Dejamos cada modificación probable escrita y comentada, marcada con `>>> PARA LA SUSTENTACIÓN`: en vivo solo hay que comentar una cosa y descomentar otra, subir el cambio y dejar que Jenkins lo despliegue.

| Pedido | Archivo | Qué hacer |
|---|---|---|
| Agregar conteo y estado a la respuesta del polígono | `app/api.py`, endpoint `/api/poligono` | **Comentar** `return jsonify(consultas.coleccion_fc(docs))` y descomentar las 4 líneas de abajo. Si no se comenta el `return`, el cambio no hace nada |
| Cambiar el agrupador por defecto de `$geoNear` a día de la semana | `app/api.py`, endpoint `/api/geonear` | Comentar `campo = request.args.get("por", "hora")` y descomentar la de `dia_semana` |
| Crear un endpoint nuevo `/api/sustentacion` | `app/api.py`, al final | Descomentar el bloque completo |
| Ordenar `$geoNear` por cantidad de puntos (de mayor a menor) | `app/consultas.py`, `geonear_por_campo` | Comentar el pipeline activo y descomentar el alternativo (el que termina en `{"$sort": {"puntos": -1}}`) |
| Limitar el radio máximo a 50 km | `app/consultas.py`, `validar_radio` | Comentar la condición de 100000 y descomentar la de 50000 |
| Probar lo anterior con pruebas | `tests/smoke/test_api.py`, al final | Descomentar `test_endpoint_sustentacion` y `test_radio_negativo_da_400` |

Después: `git add . && git commit -m "..." && git push`. Jenkins arranca solo, corre las pruebas y despliega. Si se descomenta una prueba del endpoint nuevo pero no el endpoint, las pruebas fallan y Jenkins **no despliega**: así se muestra que el pipeline protege el despliegue. Para ver las pruebas sin Jenkins: `docker compose --profile tests run --rm --build pruebas-api`.

## Máquina de la sustentación (checklist)
Hacerlo el día antes, no el mismo día.

1. **Preparar el equipo.** Docker Desktop abierto y en "running". Git instalado. Mínimo 6 GB de memoria para Docker (Settings > Resources).
2. **Obtener el proyecto:** `git clone https://github.com/biltormenta/parcial-big-data.git` y entrar a la carpeta (o descomprimir el zip que se envió y entrar a la carpeta del proyecto, la que tiene `docker-compose.yml`).
3. **Levantar todo:** `.\preparar_sustentacion.ps1 -CargarDatos`. Anotar la contraseña de Jenkins que imprime (también queda en el archivo `.env`, que no se sube a GitHub). Si PowerShell bloquea el script: `powershell -ExecutionPolicy Bypass -File .\preparar_sustentacion.ps1 -CargarDatos`.
4. **Verificar:** abrir http://localhost:5000 (mapa), http://localhost:5000/api/spark/zonas (resultados de Spark) y http://localhost:8080 (Jenkins, usuario `admin`). Lanzar el job una vez con **Build Now**: en la primera ejecución Jenkins aún no conoce el parámetro `RECARGAR_DATOS`; desde la segunda aparece **Build with Parameters**.
5. **Abrir un túnel hacia Jenkins** para que GitHub pueda avisarle. Con cloudflared, que no necesita cuenta: instalarlo una vez con `winget install Cloudflare.cloudflared`, abrir una terminal nueva y correr `cloudflared tunnel --url http://localhost:8080`. Copiar la URL `https://....trycloudflare.com` que imprime. Esa URL cambia cada vez que se reinicia el túnel. Como expone Jenkins a internet, no usar la contraseña por defecto (`admin`): el script ya genera una aleatoria.
6. **Crear o actualizar el webhook** (lo hace el dueño del repositorio): GitHub > Settings > Webhooks > Add webhook. Payload URL: `https://LA-URL-DEL-TUNEL/github-webhook/` (la barra final es obligatoria), Content type `application/json`, evento "Just the push event". El campo Secret se deja vacío (Jenkins no está configurado para validarlo). Si ya existe, editar la URL.
7. **Probar el ciclo completo:** subir un cambio pequeño a `main` y comprobar que Jenkins arranque un build solo y despliegue.
8. **Durante la sustentación:** mantener abiertos Docker, el túnel y Jenkins. Si se reinicia el túnel, repetir el paso 6.

Problemas conocidos:
- Si el job falla al hacer checkout, revisar que `REPO_URL` del `.env` sea la del repositorio y que el repositorio sea público.
- Si Docker se queda sin memoria, bajar `OBJETIVO_REGISTROS` en el `.env` (por ejemplo a 1200000) y repetir la carga.
- Si Jenkins falla en una etapa, abrir el build fallido > Console Output para ver cuál. Plan de respaldo manual, desde la carpeta del proyecto: `docker compose build api spark-master`, luego `docker run --rm geolife-app:latest pytest tests/unit -v`, luego `docker compose up -d mongo api` y `docker compose --profile tests run --rm pruebas-api`, y por último `docker compose up -d --build`.

## Estructura del repositorio
```
app/                  descarga, limpieza, ingesta (Dask), consultas, API Flask, benchmark de Dask
app/templates/        mapa Leaflet
spark_jobs/           agregaciones y benchmark de Spark
tests/                unit (pytest) y smoke (contra la API)
docker/               Dockerfiles de la app, de Spark y de Jenkins (con JCasC)
docs/                 informe técnico
docker-compose.yml, docker-compose.ci.yml, Jenkinsfile, preparar_sustentacion.ps1
```

## Seguridad de credenciales
El `.env` y `kaggle.json` están en `.gitignore`. El token de Kaggle, si se usa, solo existe en el `.env` local y como credencial de Jenkins; nunca se escribe en el repositorio. Para buscar secretos antes de entregar: `git grep -i -e KAGGLE_KEY -e kaggle.json`.

// Pipeline declarativo: cada "stage" es una etapa; si una falla, las siguientes NO se ejecutan
pipeline {
    // corre en el propio Jenkins (que tiene el cliente de Docker instalado)
    agent any

    // casilla "Build with Parameters": con RECARGAR_DATOS en true se repite la descarga y la carga de datos
    // (aparece desde la segunda ejecución; en la primera Jenkins aún no conoce los parámetros)
    parameters {
        booleanParam(name: 'RECARGAR_DATOS', defaultValue: false,
                     description: 'Descarga de Kaggle + ingesta con Dask + agregaciones con Spark (tarda)')
    }

    options {
        // evita dos builds al mismo tiempo (se pisarían los contenedores)
        disableConcurrentBuilds()
    }

    environment {
        // Pila de pruebas aislada: otro nombre de proyecto (geolife-ci) y sin puertos fijos,
        // para no chocar con el sistema desplegado de verdad (proyecto geolife)
        CI_PROJECT = 'geolife-ci'
        CI_COMPOSE = 'docker compose -p geolife-ci -f docker-compose.yml -f docker-compose.ci.yml'
    }

    stages {
        // 1. descarga el código del repositorio configurado en el job
        stage('Checkout') {
            steps { checkout scm }
        }

        // 2. construye las imágenes de la API y de Spark con el código recién descargado
        stage('Construir imagenes') {
            steps { sh 'docker compose build api spark-master' }
        }

        // 3. pytest dentro de la imagen: pruebas unitarias de limpieza y validación de parámetros
        stage('Pruebas unitarias (pytest)') {
            steps { sh 'docker run --rm geolife-app:latest pytest tests/unit -v' }
        }

        // 4. levanta solo Mongo y la API en la pila de pruebas (--wait espera a que estén sanos)
        stage('Levantar pila de pruebas') {
            steps { sh '${CI_COMPOSE} up -d --wait mongo api' }
        }

        // 5. pruebas de humo: llaman de verdad a los endpoints y verifican las respuestas
        stage('Pruebas contra la API') {
            steps { sh '${CI_COMPOSE} run --rm pruebas-api' }
        }

        // si cualquier etapa de arriba falla el pipeline se corta aqui y no se despliega
        // 6. despliegue real: reconstruye y reinicia los servicios con el código nuevo (los datos se conservan en volúmenes)
        stage('Desplegar') {
            steps {
                sh 'docker compose up -d --build --wait mongo dask-scheduler dask-worker spark-master spark-worker api'
            }
        }

        // 7. opcional (solo si se marcó RECARGAR_DATOS): descarga, limpia, carga a Mongo y corre Spark.
        // withCredentials entrega las credenciales de Kaggle guardadas en Jenkins como variables de entorno,
        // sin que aparezcan escritas en el código ni en el repositorio.
        stage('Cargar datos') {
            when { expression { params.RECARGAR_DATOS } }
            steps {
                withCredentials([string(credentialsId: 'kaggle-username', variable: 'KAGGLE_USERNAME'),
                                 string(credentialsId: 'kaggle-key', variable: 'KAGGLE_KEY')]) {
                    sh 'docker compose --profile jobs run --rm -e KAGGLE_USERNAME -e KAGGLE_KEY ingesta'
                }
                sh '''docker compose exec -T spark-master /opt/spark/bin/spark-submit \
                      --master spark://spark-master:7077 --conf spark.driver.host=spark-master \
                      --driver-memory 512m --executor-memory 700m /opt/jobs/agregaciones.py'''
            }
        }
    }

    post {
        // pase lo que pase se apaga y borra la pila de pruebas (el "|| true" evita que esto marque error)
        always { sh '${CI_COMPOSE} down -v --remove-orphans || true' }
        failure { echo 'Fallo una etapa, no se desplego nada nuevo.' }
    }
}

pipeline {
    agent any

    parameters {
        booleanParam(name: 'RECARGAR_DATOS', defaultValue: false,
                     description: 'Descarga de Kaggle + ingesta con Dask + agregaciones con Spark (tarda)')
    }

    options {
        disableConcurrentBuilds()
    }

    environment {
        CI_PROJECT = 'geolife-ci'
        CI_COMPOSE = 'docker compose -p geolife-ci -f docker-compose.yml -f docker-compose.ci.yml'
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Construir imagenes') {
            steps { sh 'docker compose build api spark-master' }
        }

        stage('Pruebas unitarias (pytest)') {
            steps { sh 'docker run --rm geolife-app:latest pytest tests/unit -v' }
        }

        stage('Levantar pila de pruebas') {
            steps { sh '${CI_COMPOSE} up -d --wait mongo api' }
        }

        stage('Pruebas contra la API') {
            steps { sh '${CI_COMPOSE} run --rm pruebas-api' }
        }

        // si cualquier etapa de arriba falla el pipeline se corta aqui y no se despliega
        stage('Desplegar') {
            steps {
                sh 'docker compose up -d --build --wait mongo dask-scheduler dask-worker spark-master spark-worker api'
            }
        }

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
        always { sh '${CI_COMPOSE} down -v --remove-orphans || true' }
        failure { echo 'Fallo una etapa, no se desplego nada nuevo.' }
    }
}

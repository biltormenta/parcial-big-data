# Spark oficial 3.5 con Java 17 y Python
FROM apache/spark:3.5.3-scala2.12-java17-python3-ubuntu

USER root
# mongo spark connector 10.x y sus dependencias, bajadas una sola vez al construir la imagen
# (así Spark no necesita internet cuando se ejecuta el job, por ejemplo en la sustentación)
ARG MVN=https://repo1.maven.org/maven2/org/mongodb
RUN cd /opt/spark/jars \
 && curl -fsSLO ${MVN}/spark/mongo-spark-connector_2.12/10.4.0/mongo-spark-connector_2.12-10.4.0.jar \
 && curl -fsSLO ${MVN}/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar \
 && curl -fsSLO ${MVN}/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar \
 && curl -fsSLO ${MVN}/bson/5.1.4/bson-5.1.4.jar \
 && curl -fsSLO ${MVN}/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar

# Los jobs de Spark quedan en /opt/jobs: de ahí los lanza spark-submit (ver Jenkinsfile y README)
COPY spark_jobs /opt/jobs
RUN mkdir -p /data/benchmark && chmod -R 777 /data
USER spark

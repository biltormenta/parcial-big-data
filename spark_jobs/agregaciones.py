import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
DB = os.getenv("MONGO_DB", "geolife")
# Tamaño de la celda de la grilla en grados: 0,01° equivale a ~1 km en Pekín
TAM_CELDA = float(os.getenv("TAM_CELDA", "0.01"))

# Sesión de Spark conectada a Mongo mediante el MongoDB Spark Connector (el .jar que se
# copia a la imagen en docker/spark.Dockerfile). Se configuran las URIs de lectura y escritura.
spark = (SparkSession.builder.appName("geolife-agregaciones")
         .config("spark.mongodb.read.connection.uri", URI)
         .config("spark.mongodb.write.connection.uri", URI)
         .getOrCreate())
spark.sparkContext.setLogLevel("WARN")


def guardar(df, nombre):
    """Escribe un DataFrame como colección nueva en Mongo (la reemplaza si ya existía)."""
    # mode("overwrite") hace que repetir el job no duplique resultados
    df.write.format("mongodb").mode("overwrite") \
        .option("database", DB).option("collection", nombre).save()
    print(f"guardada coleccion {nombre}: {df.count()} filas")


# Lectura directa desde Mongo con el connector (no se lee ningún CSV).
# loc.coordinates es el arreglo [lon, lat] del GeoJSON: se separa en dos columnas.
puntos = (spark.read.format("mongodb").option("database", DB).option("collection", "puntos").load()
          .select(F.col("loc.coordinates")[0].alias("lon"), F.col("loc.coordinates")[1].alias("lat"),
                  "usuario", "hora", "dia_semana", "mes", "anio", "altitud_m"))
# cache(): se reutiliza en todas las agregaciones de abajo sin volver a leer Mongo cada vez
puntos.cache()
print("puntos leidos desde mongo:", puntos.count())

# ---- Agregación espacial: conteo por celda de grilla ----
# Cada punto se asigna a una celda con floor(coordenada / tamaño): todos los puntos de una
# misma celda comparten (ix, iy). Después se cuenta por celda y se calcula su centro.
celdas = (puntos
          .withColumn("ix", F.floor(F.col("lon") / TAM_CELDA).cast("int"))
          .withColumn("iy", F.floor(F.col("lat") / TAM_CELDA).cast("int"))
          .groupBy("ix", "iy")
          # approx_count_distinct: usuarios distintos aproximados (mucho más barato que el exacto)
          .agg(F.count("*").alias("n"), F.approx_count_distinct("usuario").alias("usuarios"))
          .withColumn("celda", F.concat_ws("_", "ix", "iy"))
          .withColumn("lon_centro", (F.col("ix") + 0.5) * TAM_CELDA)
          .withColumn("lat_centro", (F.col("iy") + 0.5) * TAM_CELDA)
          # se guarda el centro como punto GeoJSON, para poder dibujarlo o consultarlo en Mongo
          .withColumn("loc", F.struct(F.lit("Point").alias("type"),
                                      F.array("lon_centro", "lat_centro").alias("coordinates")))
          .select("celda", "n", "usuarios", "lat_centro", "lon_centro", "loc"))
celdas.cache()
guardar(celdas, "spark_grilla")

# ---- Zonas de alta concentración: celdas por encima del percentil 99 de puntos ----
# approxQuantile calcula el percentil de forma aproximada (por eso el umbral puede variar un poco)
corte = celdas.approxQuantile("n", [0.99], 0.001)[0]
print("percentil 99 de puntos por celda:", corte)
# row_number() sobre una ventana ordenada por n da el ranking: 1 = la celda más densa
zonas = (celdas.filter(F.col("n") >= corte)
         .withColumn("ranking", F.row_number().over(Window.orderBy(F.col("n").desc())))
         .withColumn("umbral_p99", F.lit(float(corte))))
guardar(zonas, "spark_zonas_calientes")

# ---- Comportamiento temporal: por hora del día, día de la semana y mes ----
guardar(puntos.groupBy("hora").agg(F.count("*").alias("n"), F.avg("altitud_m").alias("altitud_media_m"),
                                   F.approx_count_distinct("usuario").alias("usuarios")).orderBy("hora"),
        "spark_por_hora")
guardar(puntos.groupBy("dia_semana").agg(F.count("*").alias("n"),
                                         F.approx_count_distinct("usuario").alias("usuarios")).orderBy("dia_semana"),
        "spark_por_dia")
guardar(puntos.groupBy("anio", "mes").agg(F.count("*").alias("n"),
                                          F.approx_count_distinct("usuario").alias("usuarios")).orderBy("anio", "mes"),
        "spark_por_mes")

spark.stop()

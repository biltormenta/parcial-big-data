import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
DB = os.getenv("MONGO_DB", "geolife")
TAM_CELDA = float(os.getenv("TAM_CELDA", "0.01"))  # grados, ~1 km en pekin

spark = (SparkSession.builder.appName("geolife-agregaciones")
         .config("spark.mongodb.read.connection.uri", URI)
         .config("spark.mongodb.write.connection.uri", URI)
         .getOrCreate())
spark.sparkContext.setLogLevel("WARN")


def guardar(df, nombre):
    df.write.format("mongodb").mode("overwrite") \
        .option("database", DB).option("collection", nombre).save()
    print(f"guardada coleccion {nombre}: {df.count()} filas")


# leo directo de mongo con el connector, nada de csv
puntos = (spark.read.format("mongodb").option("database", DB).option("collection", "puntos").load()
          .select(F.col("loc.coordinates")[0].alias("lon"), F.col("loc.coordinates")[1].alias("lat"),
                  "usuario", "hora", "dia_semana", "mes", "anio", "altitud_m"))
puntos.cache()
print("puntos leidos desde mongo:", puntos.count())

# conteo por celda de grilla
celdas = (puntos
          .withColumn("ix", F.floor(F.col("lon") / TAM_CELDA).cast("int"))
          .withColumn("iy", F.floor(F.col("lat") / TAM_CELDA).cast("int"))
          .groupBy("ix", "iy")
          .agg(F.count("*").alias("n"), F.approx_count_distinct("usuario").alias("usuarios"))
          .withColumn("celda", F.concat_ws("_", "ix", "iy"))
          .withColumn("lon_centro", (F.col("ix") + 0.5) * TAM_CELDA)
          .withColumn("lat_centro", (F.col("iy") + 0.5) * TAM_CELDA)
          .withColumn("loc", F.struct(F.lit("Point").alias("type"),
                                      F.array("lon_centro", "lat_centro").alias("coordinates")))
          .select("celda", "n", "usuarios", "lat_centro", "lon_centro", "loc"))
celdas.cache()
guardar(celdas, "spark_grilla")

# zonas de alta concentracion: celdas por encima del percentil 99 de puntos
corte = celdas.approxQuantile("n", [0.99], 0.001)[0]
print("percentil 99 de puntos por celda:", corte)
zonas = (celdas.filter(F.col("n") >= corte)
         .withColumn("ranking", F.row_number().over(Window.orderBy(F.col("n").desc())))
         .withColumn("umbral_p99", F.lit(float(corte))))
guardar(zonas, "spark_zonas_calientes")

# comportamiento temporal
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

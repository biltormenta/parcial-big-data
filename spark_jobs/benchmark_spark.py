import json
import os
import statistics
import sys
import time
import urllib.request

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

# se llama una vez por configuracion: spark-submit ... benchmark_spark.py <n_workers>
n_workers = int(sys.argv[1])
TAM_CELDA = 0.01
REPETICIONES = 3
SALIDA = "/data/benchmark/spark_%d.json" % n_workers

# con estas opciones los executors reportan su rss real (igual que se mide en dask)
spark = (SparkSession.builder.appName(f"bench-grilla-{n_workers}w")
         .config("spark.executor.processTreeMetrics.enabled", "true")
         .config("spark.executor.metrics.pollingInterval", "200ms")
         .config("spark.executor.heartbeatInterval", "1s")
         .getOrCreate())
spark.sparkContext.setLogLevel("WARN")


def grilla():
    df = spark.read.parquet("/data/clean/puntos").select("lat", "lon")
    return (df.withColumn("ix", F.floor(F.col("lon") / TAM_CELDA))
              .withColumn("iy", F.floor(F.col("lat") / TAM_CELDA))
              .groupBy("ix", "iy").count())


def una_corrida():
    t0 = time.perf_counter()
    g = grilla()
    celdas = g.count()
    total = g.agg(F.sum("count")).collect()[0][0]
    return time.perf_counter() - t0, celdas, total


def memoria_pico_mb():
    time.sleep(3)  # espero un par de heartbeats para que lleguen las metricas
    # la api rest del driver guarda el pico de memoria de cada executor
    base = "http://localhost:4040/api/v1/applications"
    app_id = json.load(urllib.request.urlopen(base))[0]["id"]
    ejecutores = json.load(urllib.request.urlopen(f"{base}/{app_id}/allexecutors"))
    total = 0
    for e in ejecutores:
        if e["id"] == "driver":
            continue
        m = e.get("peakMemoryMetrics", {})
        total += m.get("ProcessTreeJVMRSSMemory", 0) or (m.get("JVMHeapMemory", 0) + m.get("JVMOffHeapMemory", 0))
    return total / 1e6


una_corrida()  # calentamiento, no se cuenta
tiempos = []
for _ in range(REPETICIONES):
    seg, celdas, total = una_corrida()
    tiempos.append(seg)

res = {"motor": "spark", "workers": n_workers, "tiempo_mediana_s": round(statistics.median(tiempos), 2),
       "tiempos_s": [round(t, 2) for t in tiempos], "memoria_pico_mb": round(memoria_pico_mb()),
       "celdas": celdas, "puntos": int(total)}
print(res)
os.makedirs("/data/benchmark", exist_ok=True)
json.dump(res, open(SALIDA, "w"), indent=2)
spark.stop()

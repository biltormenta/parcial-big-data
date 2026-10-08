import json
import os
import statistics
import threading
import time

import dask.dataframe as dd
import numpy as np
import psutil
from distributed import Client

from app import config

# Benchmark Dask vs Spark: misma operación (conteo por celda de grilla) sobre el mismo Parquet
TAM_CELDA = 0.01
REPETICIONES = 3  # se reporta la mediana de 3 corridas (más estable que una sola)
SALIDA = os.path.join(config.DATOS_DIR, "benchmark", "dask.json")


def rss_workers(client, workers):
    """Suma la memoria real (RSS, en MB) de los procesos de los workers indicados."""
    # client.run ejecuta la función dentro de cada worker y devuelve un diccionario worker -> valor
    r = client.run(lambda: psutil.Process().memory_info().rss, workers=workers)
    return sum(r.values()) / 1e6


def grilla(ruta):
    """Define la operación a medir: contar puntos por celda de grilla (aún no se ejecuta)."""
    # solo se leen lat y lon del Parquet (formato columnar: no se carga lo demás)
    df = dd.read_parquet(ruta, columns=["lat", "lon"])
    ix = (df["lon"] / TAM_CELDA).map_partitions(np.floor)
    iy = (df["lat"] / TAM_CELDA).map_partitions(np.floor)
    return df.assign(ix=ix, iy=iy).groupby(["ix", "iy"]).size()


def medir(client, ruta, workers):
    """Ejecuta la operación una vez y devuelve (segundos, memoria pico MB, nº celdas, nº puntos)."""
    # Un hilo aparte mira la memoria (RSS) de los workers cada 0,3 s mientras corre la operación
    # y se queda con el valor más alto: ese es el "pico".
    pico = [0.0]
    parar = threading.Event()

    def vigilar():
        while not parar.is_set():
            pico[0] = max(pico[0], rss_workers(client, workers))
            time.sleep(0.3)

    base = rss_workers(client, workers)
    h = threading.Thread(target=vigilar)
    h.start()
    t0 = time.perf_counter()
    # workers=workers restringe el cálculo a esos workers: así se compara "1 worker" contra "2 workers"
    res = client.compute(grilla(ruta), workers=workers).result()
    seg = time.perf_counter() - t0
    parar.set()
    h.join()
    return seg, max(pico[0], base), len(res), int(res.sum())


def main():
    client = Client(config.DASK_SCHEDULER)
    todos = list(client.scheduler_info()["workers"].keys())
    ruta = os.path.join(config.DATOS_DIR, "clean", "puntos")
    resultados = []
    # Dos configuraciones: 1 worker y todos los workers (2)
    for n in (1, len(todos)):
        usados = todos[:n]
        medir(client, ruta, usados)  # primera corrida de calentamiento, no se cuenta
        tiempos, picos = [], []
        for _ in range(REPETICIONES):
            seg, pico, celdas, total = medir(client, ruta, usados)
            tiempos.append(seg)
            picos.append(pico)
        resultados.append({"motor": "dask", "workers": n, "tiempo_mediana_s": round(statistics.median(tiempos), 2),
                           "tiempos_s": [round(t, 2) for t in tiempos], "memoria_pico_mb": round(max(picos)),
                           "celdas": celdas, "puntos": total})
        print(resultados[-1])
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    json.dump(resultados, open(SALIDA, "w"), indent=2)


if __name__ == "__main__":
    main()

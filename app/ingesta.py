import json
import os
import time

import dask.dataframe as dd
import pandas as pd
from distributed import Client
from pymongo import GEOSPHERE, MongoClient

from app import config
from app.descarga import descargar, seleccionar_archivos
from app.limpieza import COLUMNAS_PLT, META_LIMPIO, a_geojson, estadisticas, limpiar

META_STATS = pd.DataFrame({"leidos": pd.Series(dtype="int64"), "nulos": pd.Series(dtype="int64"),
                           "fuera_rango": pd.Series(dtype="int64"), "sin_fecha": pd.Series(dtype="int64")})


def cargar_lote(df, uri, db, coleccion, tam_lote):
    # esto corre dentro de cada worker de dask, cada uno abre su propia conexion a mongo
    docs = a_geojson(df)
    col = MongoClient(uri)[db][coleccion]
    for i in range(0, len(docs), tam_lote):
        col.insert_many(docs[i:i + tam_lote], ordered=False)
    return pd.DataFrame({"n": [len(docs)]})


def main():
    t0 = time.time()
    ruta = descargar()
    archivos = seleccionar_archivos(ruta)

    client = Client(config.DASK_SCHEDULER)
    print("dask:", client.dashboard_link, "workers:", len(client.scheduler_info()["workers"]))

    # lectura particionada: un archivo .plt = una particion, las 6 primeras lineas son encabezado
    crudo = dd.read_csv(archivos, skiprows=6, header=None,
                        names=["lat", "lon", "c0", "alt_ft", "c1", "fecha", "hora"],
                        usecols=["lat", "lon", "alt_ft", "fecha", "hora"],
                        include_path_column="ruta", blocksize=None, dtype=str)
    crudo["ruta"] = crudo["ruta"].astype(str)

    stats = crudo.map_partitions(estadisticas, meta=META_STATS).compute().sum()
    limpio = crudo.map_partitions(limpiar, meta=META_LIMPIO)
    limpio = limpio.repartition(npartitions=max(len(client.scheduler_info()["workers"]) * 8, 8))

    # guardo el parquet limpio, lo usan despues los benchmarks de dask y spark
    destino = os.path.join(config.DATOS_DIR, "clean", "puntos")
    # spark no lee timestamps en nanosegundos, por eso se guardan en microsegundos
    limpio.to_parquet(destino, overwrite=True, write_index=False,
                      coerce_timestamps="us", allow_truncated_timestamps=True)
    print("parquet limpio en", destino)

    # carga a mongo por lotes, de nuevo desde los workers
    col = MongoClient(config.MONGO_URI)[config.MONGO_DB][config.COLECCION_PUNTOS]
    col.drop()
    cargado = dd.read_parquet(destino).map_partitions(
        cargar_lote, config.MONGO_URI, config.MONGO_DB, config.COLECCION_PUNTOS,
        config.TAM_LOTE_MONGO, meta={"n": "int64"}).compute()
    total = int(cargado["n"].sum())

    # el indice se crea al final porque cargar con indice 2dsphere es mucho mas lento
    col.create_index([("loc", GEOSPHERE)])
    col.create_index("ts")
    en_mongo = col.count_documents({})

    resumen = {
        "archivos": len(archivos),
        "leidos": int(stats["leidos"]),
        "descartados_nulos": int(stats["nulos"]),
        "descartados_fuera_rango": int(stats["fuera_rango"]),
        "descartados_fecha_invalida": int(stats["sin_fecha"]),
        "descartados_duplicados": int(stats["leidos"] - stats["nulos"] - stats["fuera_rango"]
                                      - stats["sin_fecha"] - total),
        "cargados_en_mongo": en_mongo,
        "segundos": round(time.time() - t0, 1),
    }
    assert en_mongo == total, f"mongo tiene {en_mongo} y se enviaron {total}"
    assert en_mongo >= 1_000_000, "el taller pide al menos un millon de registros"
    with open(os.path.join(config.DATOS_DIR, "resumen_ingesta.json"), "w") as f:
        json.dump(resumen, f, indent=2)
    print(json.dumps(resumen, indent=2))


if __name__ == "__main__":
    main()
